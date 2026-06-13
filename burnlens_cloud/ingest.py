import asyncio
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Header, HTTPException

from .auth import get_workspace_by_api_key
from .database import execute_query, execute_bulk_insert
from .email import send_usage_warning_email, track_email_task
from .encryption import get_encryption_manager
from .models import IngestRequest, IngestResponse, QuotaExceededDetail
from .plans import resolve_limits
from .telemetry.forwarder import get_forwarder
from .config import settings
from .streaming import send_records_to_stream

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ingest"])


async def _check_quota_or_raise(
    workspace_id: str,
    plan: str,
    batch_size: int,
) -> None:
    """Pre-insert quota gate — raises HTTPException(429) if any quota dimension is breached.

    Must be called AFTER auth (workspace_id known) and BEFORE execute_bulk_insert.
    Do NOT wrap in try/except — the 429 must propagate to FastAPI's response handler.

    Checks in order: requests → tokens → spend_usd → seats.
    None cap on any dimension means unlimited — that dimension is skipped.

    Implementation note: reading current cycle counters (request_count, token_count,
    spend_usd) uses a no-op UPSERT (ON CONFLICT DO UPDATE SET updated_at = updated_at
    RETURNING ...) rather than a plain SELECT. This avoids racing with the post-ingest
    UPSERT in _record_usage_and_maybe_notify: a plain SELECT on a not-yet-existing row
    returns empty; the no-op UPSERT seeds the row with zero counters if missing and
    returns the actual values otherwise.

    Race condition: read-then-check has a small overshoot window. This is accepted per
    Phase 9 precedent (see ingest.py comment at _record_usage_and_maybe_notify). The
    alternative (SELECT FOR UPDATE) would serialize all ingest through one DB row lock.

    QUOTA-04 interpretation: seat enforcement is active-member-count vs seat_count limit.
    Active member count is the natural proxy (A2 from RESEARCH.md).
    """
    limits = await resolve_limits(workspace_id)
    if limits is None:
        return  # workspace passed auth; resolve_limits None is a belt-and-suspenders guard

    # Determine which dimension caps are active.
    check_requests = limits.monthly_request_cap is not None and limits.monthly_request_cap > 0
    check_tokens = limits.monthly_token_cap is not None and limits.monthly_token_cap > 0
    check_spend = limits.monthly_spend_cap_usd is not None and limits.monthly_spend_cap_usd > 0
    check_seats = limits.seat_count is not None and limits.seat_count > 0

    # --- QUOTA-01, QUOTA-02, QUOTA-03: cycle-based counters ---
    if check_requests or check_tokens or check_spend:
        # Resolve cycle bounds (same logic as _record_usage_and_maybe_notify).
        if plan == "free":
            cycle_row = await execute_query(
                """
                SELECT
                    date_trunc('month', now() AT TIME ZONE 'UTC') AS cycle_start,
                    (date_trunc('month', now() AT TIME ZONE 'UTC') + INTERVAL '1 month') AS cycle_end
                """
            )
        else:
            cycle_row = await execute_query(
                """
                SELECT cycle_start, cycle_end
                FROM workspace_usage_cycles
                WHERE workspace_id = $1 AND cycle_end > NOW()
                ORDER BY cycle_start DESC
                LIMIT 1
                """,
                workspace_id,
            )
            if not cycle_row:
                # Webhook lagged — fall back to calendar month (same as _record_usage_and_maybe_notify).
                cycle_row = await execute_query(
                    """
                    SELECT
                        date_trunc('month', now() AT TIME ZONE 'UTC') AS cycle_start,
                        (date_trunc('month', now() AT TIME ZONE 'UTC') + INTERVAL '1 month') AS cycle_end
                    """
                )

        if (
            not cycle_row
            or cycle_row[0]["cycle_start"] is None
            or cycle_row[0]["cycle_end"] is None
        ):
            # Cannot determine cycle bounds — skip enforcement (fail-open).
            logger.warning(
                "quota.cycle_bounds_missing workspace=%s plan=%s — skipping quota check",
                workspace_id,
                plan,
            )
        else:
            cycle_start = cycle_row[0]["cycle_start"]
            cycle_end = cycle_row[0]["cycle_end"]

            # Read current cycle counters via a no-op UPSERT: seeds a zero row if the
            # cycle row is not yet created, otherwise leaves counters unchanged and
            # returns their current values. Matches dispatcher pattern used in tests.
            usage_rows = await execute_query(
                """
                INSERT INTO workspace_usage_cycles
                    (workspace_id, cycle_start, cycle_end, request_count, token_count, spend_usd, updated_at)
                VALUES ($1, $2, $3, 0, 0, 0, NOW())
                ON CONFLICT (workspace_id, cycle_start) DO UPDATE
                    SET updated_at = workspace_usage_cycles.updated_at
                RETURNING request_count, token_count, spend_usd
                """,
                workspace_id,
                cycle_start,
                cycle_end,
            )
            if usage_rows:
                row = usage_rows[0]
                current_requests = int(row.get("request_count", 0))
                current_tokens = int(row.get("token_count", 0))
                current_spend = float(row.get("spend_usd", 0.0))

                # --- QUOTA-01: monthly request cap ---
                if check_requests and current_requests >= limits.monthly_request_cap:
                    raise HTTPException(
                        status_code=429,
                        detail=QuotaExceededDetail(
                            dimension="requests",
                            current=float(current_requests),
                            limit=float(limits.monthly_request_cap),
                        ).model_dump(),
                    )

                # --- QUOTA-02: monthly token cap ---
                if check_tokens and current_tokens >= limits.monthly_token_cap:
                    raise HTTPException(
                        status_code=429,
                        detail=QuotaExceededDetail(
                            dimension="tokens",
                            current=float(current_tokens),
                            limit=float(limits.monthly_token_cap),
                        ).model_dump(),
                    )

                # --- QUOTA-03: cumulative spend ceiling ---
                if check_spend and current_spend >= float(limits.monthly_spend_cap_usd):
                    raise HTTPException(
                        status_code=429,
                        detail=QuotaExceededDetail(
                            dimension="spend_usd",
                            current=current_spend,
                            limit=float(limits.monthly_spend_cap_usd),
                        ).model_dump(),
                    )

    # --- QUOTA-04: seat cap (active member count vs plan seat_count) ---
    if check_seats:
        member_rows = await execute_query(
            """
            SELECT COUNT(*) as count FROM workspace_members
            WHERE workspace_id = $1 AND active = true
            """,
            str(workspace_id),
        )
        member_count = int(member_rows[0]["count"]) if member_rows else 0
        if member_count > limits.seat_count:
            raise HTTPException(
                status_code=429,
                detail=QuotaExceededDetail(
                    dimension="seats",
                    current=float(member_count),
                    limit=float(limits.seat_count),
                ).model_dump(),
            )


async def _record_usage_and_maybe_notify(
    workspace_id: str,
    plan: str,
    records_count: int,
    batch_tokens: int = 0,
    batch_spend_usd: float = 0.0,
) -> None:
    """UPSERT the cycle counter; if we just crossed 80% or 100%, enqueue the email.

    Fire-and-forget: EVERY exception is caught and logged at WARNING. This function
    must NEVER raise — it runs after the ingest 200 path has succeeded and must
    not flip success to failure (fail-open per QUOTA-03 contract + ingest.py's
    established OTEL forward pattern).
    """
    try:
        # 1) Compute cycle bounds per D-02 / D-03.
        if plan == "free":
            cycle_row = await execute_query(
                """
                SELECT
                    date_trunc('month', now() AT TIME ZONE 'UTC') AS cycle_start,
                    (date_trunc('month', now() AT TIME ZONE 'UTC') + INTERVAL '1 month') AS cycle_end
                """
            )
        else:
            # Read the current cycle bounds from workspace_usage_cycles, which the
            # Paddle subscription webhooks (billing.py) seed on activation/update.
            # The `workspaces.current_period_started_at` column does NOT exist in
            # the schema (only current_period_ends_at is added), so we cannot
            # reconstruct cycle bounds from the workspaces row. Source of truth
            # for paid-plan cycles is workspace_usage_cycles.
            cycle_row = await execute_query(
                """
                SELECT cycle_start, cycle_end
                FROM workspace_usage_cycles
                WHERE workspace_id = $1 AND cycle_end > NOW()
                ORDER BY cycle_start DESC
                LIMIT 1
                """,
                workspace_id,
            )
            if not cycle_row:
                # Webhook lagged / not yet delivered — fall back to calendar month
                # so we don't silently drop paid-plan usage tracking. The row will
                # be reconciled once the billing webhook arrives (ON CONFLICT DO
                # NOTHING preserves any running counter).
                cycle_row = await execute_query(
                    """
                    SELECT
                        date_trunc('month', now() AT TIME ZONE 'UTC') AS cycle_start,
                        (date_trunc('month', now() AT TIME ZONE 'UTC') + INTERVAL '1 month') AS cycle_end
                    """
                )
        if (
            not cycle_row
            or cycle_row[0]["cycle_start"] is None
            or cycle_row[0]["cycle_end"] is None
        ):
            logger.warning(
                "usage.cycle_bounds_missing workspace=%s plan=%s",
                workspace_id,
                plan,
            )
            return
        cycle_start = cycle_row[0]["cycle_start"]
        cycle_end = cycle_row[0]["cycle_end"]

        # 2) UPSERT the counter (D-04). RETURNING gives us the new count inline.
        #    Phase 15: also increments token_count and spend_usd (QUOTA-02/03 tracking).
        upserted = await execute_query(
            """
            INSERT INTO workspace_usage_cycles
                (workspace_id, cycle_start, cycle_end, request_count, token_count, spend_usd, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW())
            ON CONFLICT (workspace_id, cycle_start) DO UPDATE
                SET request_count = workspace_usage_cycles.request_count + EXCLUDED.request_count,
                    token_count   = workspace_usage_cycles.token_count   + EXCLUDED.token_count,
                    spend_usd     = workspace_usage_cycles.spend_usd     + EXCLUDED.spend_usd,
                    updated_at    = NOW()
            RETURNING id, request_count, token_count, spend_usd, notified_80_at, notified_100_at
            """,
            workspace_id,
            cycle_start,
            cycle_end,
            records_count,
            batch_tokens,
            batch_spend_usd,
        )
        if not upserted:
            logger.warning("usage.upsert_returned_empty workspace=%s", workspace_id)
            return
        row = upserted[0]
        cycle_id = row["id"]
        new_count = int(row["request_count"])
        # Reconstruct the pre-UPSERT value without an extra round-trip.
        prev_count = new_count - records_count

        # 3) Resolve cap. None => unlimited => skip all threshold work.
        limits = await resolve_limits(workspace_id)
        if limits is None:
            return
        cap = limits.monthly_request_cap
        if cap is None or cap <= 0:
            return

        pct_new = new_count / cap
        pct_prev = prev_count / cap

        # 4) Threshold claims (D-06 atomic check-and-set). Race-safe: the UPDATE's
        # rowcount tells us whether we won; only the winner enqueues the email.
        #
        # WR-04: Cycle-rollover race. Now that cycle bounds are read from
        # workspace_usage_cycles directly (CR-01), a webhook seeding the NEXT
        # cycle while this ingest is mid-flight no longer targets a phantom
        # old row on workspaces. The UPSERT above targets whichever cycle we
        # selected at the top of this function: if the webhook seeded the new
        # cycle AFTER our SELECT but BEFORE our UPSERT, we still increment the
        # OLD cycle (which is now effectively closed). That is acceptable —
        # usage from the bleed window is accounted to the outgoing cycle, and
        # the new cycle starts from zero for the next ingest. Not an anomaly
        # worth an extra round-trip to re-select.
        plan_label = limits.plan.capitalize() if limits.plan else plan.capitalize()
        cycle_end_date_str = (
            f"{cycle_end:%B} {cycle_end.day}, {cycle_end.year}" if cycle_end else ""
        )

        # 100% takes precedence — if we crossed both in one batch, send the 100 email.
        if pct_prev < 1.0 <= pct_new:
            claim = await execute_query(
                """
                UPDATE workspace_usage_cycles
                SET notified_100_at = NOW()
                WHERE id = $1 AND notified_100_at IS NULL
                RETURNING id
                """,
                cycle_id,
            )
            if claim:
                # WR-03: track the fire-and-forget task so GC doesn't drop it
                # and lifespan shutdown can drain outstanding sends.
                track_email_task(asyncio.create_task(
                    send_usage_warning_email(
                        workspace_id=workspace_id,
                        threshold="100",
                        current=new_count,
                        limit=cap,
                        cycle_end_date=cycle_end_date_str,
                        plan_label=plan_label,
                    )
                ))
        elif pct_prev < 0.8 <= pct_new:
            claim = await execute_query(
                """
                UPDATE workspace_usage_cycles
                SET notified_80_at = NOW()
                WHERE id = $1 AND notified_80_at IS NULL
                RETURNING id
                """,
                cycle_id,
            )
            if claim:
                # WR-03: track the fire-and-forget task so GC doesn't drop it
                # and lifespan shutdown can drain outstanding sends.
                track_email_task(asyncio.create_task(
                    send_usage_warning_email(
                        workspace_id=workspace_id,
                        threshold="80",
                        current=new_count,
                        limit=cap,
                        cycle_end_date=cycle_end_date_str,
                        plan_label=plan_label,
                    )
                ))
    except Exception as exc:
        logger.warning(
            "usage.record_failed workspace=%s err=%s",
            workspace_id,
            exc,
            exc_info=True,
        )


@router.post("/v1/ingest", response_model=IngestResponse)
async def ingest(
    request: IngestRequest,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """
    Bulk ingest cost records from OSS proxy.

    The API key is accepted from either the `X-API-Key` request header
    (the OSS proxy's wire format) or the JSON body's `api_key` field.
    If both are present, the body wins.

    Expected request body:
    {
        "api_key": "bl_live_...",
        "records": [
            {
                "timestamp": "2024-01-15T10:30:00Z",
                "provider": "openai",
                "model": "gpt-4o",
                "input_tokens": 100,
                "output_tokens": 50,
                ...
            }
        ]
    }

    Returns:
    {
        "accepted": 500,
        "rejected": 0
    }
    """
    # Resolve API key from body (preferred) or X-API-Key header (OSS proxy compat).
    api_key = request.api_key or x_api_key
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    # Validate API key and get workspace
    workspace_result = await get_workspace_by_api_key(api_key)
    if not workspace_result:
        logger.warning("Ingest request with invalid API key")
        raise HTTPException(status_code=401, detail="Invalid API key")

    workspace_id, plan = workspace_result

    # Phase 15 (QUOTA-01–04): hard quota pre-check — raises 429 before any write.
    # Must run after auth (workspace_id available) and before execute_bulk_insert.
    await _check_quota_or_raise(workspace_id, plan, len(request.records))

    # Fetch full workspace details (including OTEL config)
    workspace_details = await execute_query(
        "SELECT otel_endpoint, otel_api_key_encrypted, otel_enabled FROM workspaces WHERE id = $1",
        workspace_id,
    )
    otel_config = workspace_details[0] if workspace_details else None

    # Prepare bulk insert data
    insert_data = []
    for record in request.records:
        insert_data.append(
            (
                workspace_id,
                record.timestamp,
                record.provider,
                record.model,
                record.input_tokens,
                record.output_tokens,
                record.reasoning_tokens,
                record.cache_read_tokens,
                record.cache_write_tokens,
                float(record.cost_usd),
                record.duration_ms,
                record.status_code,
                record.tags,
                record.system_prompt_hash,
                datetime.utcnow(),
            )
        )

    # Ingest records — stream to Kafka/Redpanda if enabled, else insert to PostgreSQL
    try:
        if settings.streaming_enabled:
            # Map Pydantic record schema to stream event dict
            stream_records = []
            for r in request.records:
                tags = r.tags or {}
                stream_records.append({
                    "ts": r.timestamp.isoformat() if hasattr(r.timestamp, "isoformat") else str(r.timestamp),
                    "provider": r.provider,
                    "model": r.model,
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                    "reasoning_tokens": r.reasoning_tokens,
                    "cache_read_tokens": r.cache_read_tokens,
                    "cache_write_tokens": r.cache_write_tokens,
                    "cost_usd": float(r.cost_usd),
                    "duration_ms": r.duration_ms,
                    "status_code": r.status_code,
                    "tag_feature": tags.get("feature", ""),
                    "tag_team": tags.get("team", ""),
                    "tag_customer": tags.get("customer", ""),
                    "system_prompt_hash": r.system_prompt_hash or "",
                })
            await send_records_to_stream(workspace_id, stream_records)
            logger.info(
                f"Streamed {len(request.records)} records for workspace {workspace_id} to stream plane"
            )
        else:
            await execute_bulk_insert(
                """
                INSERT INTO request_records
                (workspace_id, ts, provider, model, input_tokens, output_tokens,
                 reasoning_tokens, cache_read_tokens, cache_write_tokens,
                 cost_usd, duration_ms, status_code, tags, system_prompt_hash, received_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                """,
                insert_data,
            )
            logger.info(
                f"Ingested {len(request.records)} records for workspace {workspace_id} directly to PostgreSQL"
            )

        # Phase 9 QUOTA-01/02/03: record usage, check 80/100% thresholds, enqueue email.
        # Wrapped internally; failures MUST NOT affect the ingest 200 response.
        # Compute batch token and spend totals for usage tracking (Phase 15 QUOTA-02/03).
        batch_tokens = sum(
            r.input_tokens + r.output_tokens + (r.reasoning_tokens or 0)
            for r in request.records
        )
        batch_spend_usd = sum(float(r.cost_usd) for r in request.records)

        try:
            await _record_usage_and_maybe_notify(
                workspace_id, plan, len(request.records),
                batch_tokens=batch_tokens,
                batch_spend_usd=batch_spend_usd,
            )
        except Exception as exc:
            logger.warning(
                "usage.record_outer_guard workspace=%s err=%s", workspace_id, exc
            )

        # Queue OTEL forward as background task (never block on this)
        if otel_config and otel_config.get("otel_enabled"):
            try:
                forwarder = get_forwarder()
                endpoint = otel_config.get("otel_endpoint")
                encrypted_key = otel_config.get("otel_api_key_encrypted")

                if endpoint and encrypted_key:
                    # Decrypt API key
                    encryption_manager = get_encryption_manager()
                    api_key = encryption_manager.decrypt(encrypted_key)

                    # Convert records to dicts for OTEL forwarding
                    otel_records = []
                    for record in request.records:
                        otel_records.append(record.dict())

                    # Forward as background task (fire and forget)
                    asyncio.create_task(
                        forwarder.forward_batch(otel_records, endpoint, api_key)
                    )
            except Exception as e:
                logger.warning(f"Failed to queue OTEL forward: {e}")
                # Don't fail ingest on OTEL error

        return IngestResponse(accepted=len(request.records), rejected=0)

    except Exception as e:
        logger.error(f"Failed to ingest records: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to ingest records. Please retry.",
        )
