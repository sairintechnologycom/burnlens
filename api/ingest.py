"""POST /api/v1/ingest — bulk record ingestion from OSS proxy."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from . import config
from .crypto import decrypt
from .models import IngestRequest, IngestResponse
from .telemetry.forwarder import get_forwarder

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory API key cache: {api_key: (workspace_id, plan, cached_at)}
_key_cache: dict[str, tuple[str, str, float]] = {}


async def _lookup_workspace(api_key: str) -> tuple[str, str] | None:
    """Lookup workspace by api_key with 60s in-memory cache."""
    now = time.time()
    if api_key in _key_cache:
        ws_id, plan, cached_at = _key_cache[api_key]
        if now - cached_at < config.API_KEY_CACHE_TTL:
            return (ws_id, plan)
        del _key_cache[api_key]

    from .database import pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, plan FROM workspaces WHERE api_key = $1 AND active = true",
            api_key,
        )
    if not row:
        return None

    ws_id = str(row["id"])
    plan = row["plan"]
    _key_cache[api_key] = (ws_id, plan, now)
    return (ws_id, plan)


@router.post("/api/v1/ingest", response_model=IngestResponse)
async def ingest(body: IngestRequest):
    """Bulk ingest cost records from the OSS proxy."""
    import hmac
    import hashlib
    import json

    result = await _lookup_workspace(body.api_key)
    if not result:
        raise HTTPException(status_code=401, detail={"error": "invalid_api_key"})

    workspace_id, plan = result

    # Verify signature if present (Phase 2 hardening)
    if body.signature:
        # Re-calculate signature from records
        # Use sort_keys=True for consistent JSON serialization
        record_dicts = [r.model_dump() for r in body.records]
        # model_dump with dates results in ISO strings which is what we need
        # but we must match the format used by the client.
        # CloudSync uses [_sanitize_record(r) for r in records] then json.dumps(..., sort_keys=True)
        # We need to replicate that exactly.
        
        # Helper to match client sanitization
        from .models import RecordIn
        allowed_fields = {
            "timestamp", "provider", "model", "input_tokens", "output_tokens",
            "reasoning_tokens", "cache_read_tokens", "cache_write_tokens",
            "cost_usd", "duration_ms", "status_code", "system_prompt_hash",
            "tag_feature", "tag_team", "tag_customer", "tag_key_label"
        }
        
        def _sanitize(r: RecordIn) -> dict:
            d = r.model_dump()
            # ts in body is datetime, but client serialized it to string
            d["timestamp"] = d.pop("ts").isoformat()
            return {k: v for k, v in d.items() if k in allowed_fields}

        sanitized = [_sanitize(r) for r in body.records]
        expected_json = json.dumps(sanitized, sort_keys=True, separators=(',', ':'))
        
        # Wait, I need to check if client uses separators. 
        # CloudSync just uses json.dumps(sanitized, sort_keys=True). 
        # Python's default json.dumps adds spaces after commas/colons.
        expected_json_default = json.dumps(sanitized, sort_keys=True)
        
        expected_signature = hmac.new(
            body.api_key.encode(),
            expected_json_default.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(body.signature, expected_signature):
            logger.warning("Invalid ingest signature for workspace %s", workspace_id)
            raise HTTPException(status_code=403, detail={"error": "invalid_signature"})

    # Fetch OTEL config (needed after insert)
    otel_config = None
    try:
        from .database import pool as _pool
        async with _pool.acquire() as conn:
            otel_row = await conn.fetchrow(
                "SELECT otel_endpoint, otel_api_key_encrypted, otel_enabled FROM workspaces WHERE id = $1",
                workspace_id,
            )
        if otel_row and hasattr(otel_row, "get"):
            otel_config = otel_row
    except Exception:
        logger.debug("Could not fetch OTEL config for workspace %s", workspace_id)

    # Free tier check
    if plan == "free":
        from .database import pool
        async with pool.acquire() as conn:
            month_start = datetime.now(timezone.utc).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM requests WHERE workspace_id = $1 AND received_at >= $2",
                workspace_id,
                month_start,
            )
        if count >= config.FREE_TIER_MONTHLY_LIMIT:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "free_tier_limit",
                    "count": count,
                    "limit": config.FREE_TIER_MONTHLY_LIMIT,
                    "upgrade_url": "https://burnlens.app/signup",
                },
            )

    if not body.records:
        return IngestResponse(accepted=0, rejected=0)

    # Bulk INSERT with executemany in a single transaction
    now = datetime.now(timezone.utc)
    rows = [
        (
            workspace_id,
            r.ts,
            r.provider,
            r.model,
            r.input_tokens,
            r.output_tokens,
            r.reasoning_tokens,
            r.cache_read_tokens,
            r.cache_write_tokens,
            float(r.cost_usd),
            r.latency_ms,
            r.tag_feature,
            r.tag_team,
            r.tag_customer,
            r.system_prompt_hash,
            now,
        )
        for r in body.records
    ]

    try:
        from .database import pool
        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO requests
                    (workspace_id, ts, provider, model,
                     input_tokens, output_tokens, reasoning_tokens,
                     cache_read_tokens, cache_write_tokens,
                     cost_usd, latency_ms,
                     tag_feature, tag_team, tag_customer,
                     system_prompt_hash, received_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                """,
                rows,
            )
        logger.info("Ingested %d records for workspace %s", len(rows), workspace_id)

        # Queue OTEL forward (fire-and-forget, never blocks ingest)
        if (
            otel_config
            and otel_config.get("otel_enabled")
            and otel_config.get("otel_endpoint")
            and otel_config.get("otel_api_key_encrypted")
        ):
            try:
                api_key = decrypt(otel_config["otel_api_key_encrypted"])
                record_dicts = [r.model_dump() for r in body.records]
                forwarder = get_forwarder()

                async def _forward():
                    ok, _ = await forwarder.forward_batch(
                        record_dicts,
                        otel_config["otel_endpoint"],
                        api_key,
                        workspace_id=workspace_id,
                    )
                    # Update last_push regardless of success
                    try:
                        async with _pool.acquire() as c:
                            await c.execute(
                                "UPDATE workspaces SET otel_last_push = NOW() WHERE id = $1",
                                workspace_id,
                            )
                    except Exception:
                        logger.warning("Failed to update otel_last_push")

                asyncio.create_task(_forward())
            except Exception as e:
                logger.warning("Failed to queue OTEL forward: %s", e)

        return IngestResponse(accepted=len(rows), rejected=0)

    except Exception:
        logger.exception("Ingest DB error for workspace %s", workspace_id)
        return IngestResponse(accepted=0, rejected=len(body.records))
