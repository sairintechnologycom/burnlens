"""Workspace-scoped source-event identity for cloud cost ingestion.

`request_records.cost_usd` remains the canonical amount supplied by the local
proxy.  This module only decides whether an already-calculated record is new,
an idempotent replay, or a conflicting reuse of an external event identifier.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .database import get_pool
from .config import settings


@dataclass(frozen=True)
class ExistingEventClassification:
    new_records: list[Any]
    duplicate_count: int
    conflict_count: int


@dataclass(frozen=True)
class PersistedEventRecords:
    inserted_records: list[Any]
    duplicate_count: int
    conflict_count: int


def source_event_id(record: Any) -> str | None:
    """Return a usable client-supplied event id, preserving legacy no-id flow."""
    value = getattr(record, "event_id", None)
    value = str(value).strip() if value is not None else ""
    return value or None


def payload_hash(record: Any) -> str:
    """Fingerprint immutable financial fields without retaining another payload copy."""
    timestamp = record.timestamp.isoformat() if isinstance(record.timestamp, datetime) else str(record.timestamp)
    payload = {
        "timestamp": timestamp,
        "provider": record.provider,
        "model": record.model,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "reasoning_tokens": record.reasoning_tokens,
        "cache_read_tokens": record.cache_read_tokens,
        "cache_write_tokens": record.cache_write_tokens,
        "cost_usd": str(record.cost_usd),
        "duration_ms": record.duration_ms,
        "status_code": record.status_code,
        "tags": record.tags or {},
        "system_prompt_hash": record.system_prompt_hash,
        "cache_hit": record.cache_hit,
        "cache_saved_usd": str(record.cache_saved_usd),
        "trace_id": record.trace_id,
        "request_id": record.request_id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def classify_existing_events(
    workspace_id: str,
    records: list[Any],
) -> ExistingEventClassification:
    """Classify source ids before quota evaluation without writing financial data."""
    event_records = [record for record in records if source_event_id(record)]
    if not event_records:
        return ExistingEventClassification([], 0, 0)

    ids = list({source_event_id(record) for record in event_records})
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT source_event_id, payload_sha256
            FROM ingest_event_identities
            WHERE workspace_id = $1 AND source_event_id = ANY($2::text[])
            """,
            workspace_id,
            ids,
        )
    existing = {row["source_event_id"]: row["payload_sha256"] for row in rows}
    seen: dict[str, str] = {}
    new_records: list[Any] = []
    duplicates = conflicts = 0
    for record in event_records:
        event_id = source_event_id(record)
        assert event_id is not None
        digest = payload_hash(record)
        prior = seen.get(event_id, existing.get(event_id))
        if prior is None:
            seen[event_id] = digest
            new_records.append(record)
        elif prior == digest:
            duplicates += 1
        else:
            conflicts += 1
    return ExistingEventClassification(new_records, duplicates, conflicts)


def _request_values(workspace_id: str, record: Any) -> tuple[Any, ...]:
    return (
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
        json.dumps(record.tags or {}),
        record.system_prompt_hash,
        datetime.utcnow(),
        record.cache_hit,
        record.cache_saved_usd,
        source_event_id(record),
        record.trace_id,
        record.request_id,
    )


async def persist_event_records(
    workspace_id: str,
    records: list[Any],
    *,
    queue_for_streaming: bool,
) -> PersistedEventRecords:
    """Atomically claim source identities and insert their canonical cost records.

    A conflicting source id never updates the original cost.  The identity row,
    canonical record, and optional stream outbox row commit together.
    """
    if not records:
        return PersistedEventRecords([], 0, 0)

    pool = get_pool()
    inserted: list[Any] = []
    duplicates = conflicts = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for record in records:
                event_id = source_event_id(record)
                assert event_id is not None
                digest = payload_hash(record)
                claimed = await conn.fetchrow(
                    """
                    INSERT INTO ingest_event_identities
                        (workspace_id, source_event_id, payload_sha256)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (workspace_id, source_event_id) DO NOTHING
                    RETURNING source_event_id
                    """,
                    workspace_id,
                    event_id,
                    digest,
                )
                if claimed:
                    inserted.append(record)
                    continue
                current = await conn.fetchrow(
                    """
                    SELECT payload_sha256 FROM ingest_event_identities
                    WHERE workspace_id = $1 AND source_event_id = $2
                    """,
                    workspace_id,
                    event_id,
                )
                if current and current["payload_sha256"] == digest:
                    duplicates += 1
                else:
                    conflicts += 1
                    await conn.execute(
                        """
                        UPDATE ingest_event_identities
                        SET conflict_count = conflict_count + 1, last_conflict_at = NOW()
                        WHERE workspace_id = $1 AND source_event_id = $2
                        """,
                        workspace_id, event_id,
                    )

            if inserted:
                await conn.executemany(
                    """
                    INSERT INTO request_records
                    (workspace_id, ts, provider, model, input_tokens, output_tokens,
                     reasoning_tokens, cache_read_tokens, cache_write_tokens,
                     cost_usd, duration_ms, status_code, tags, system_prompt_hash, received_at,
                     cache_hit, cache_saved_usd, source_event_id, trace_id, provider_request_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
                            $16, $17, $18, $19, $20)
                    """,
                    [_request_values(workspace_id, record) for record in inserted],
                )
                rows = await conn.fetch(
                    """
                    SELECT id, source_event_id FROM request_records
                    WHERE workspace_id = $1 AND source_event_id = ANY($2::text[])
                    """,
                    workspace_id,
                    [source_event_id(record) for record in inserted],
                )
                request_ids = {row["source_event_id"]: row["id"] for row in rows}
                await conn.executemany(
                    """
                    UPDATE ingest_event_identities
                    SET request_record_id = $3
                    WHERE workspace_id = $1 AND source_event_id = $2
                    """,
                    [(workspace_id, event_id, request_ids[event_id]) for event_id in request_ids],
                )
                if queue_for_streaming:
                    await conn.executemany(
                        """
                        INSERT INTO stream_ingest_outbox
                            (workspace_id, source_event_id, payload)
                        VALUES ($1, $2, $3::jsonb)
                        ON CONFLICT (workspace_id, source_event_id) DO NOTHING
                        """,
                        [
                            (workspace_id, source_event_id(record), json.dumps(stream_payload(record)))
                            for record in inserted
                        ],
                    )
    return PersistedEventRecords(inserted, duplicates, conflicts)


def stream_payload(record: Any) -> dict[str, Any]:
    """The existing stream shape plus the original source event identity."""
    tags = record.tags or {}
    return {
        "ts": record.timestamp.isoformat() if hasattr(record.timestamp, "isoformat") else str(record.timestamp),
        "provider": record.provider,
        "model": record.model,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "reasoning_tokens": record.reasoning_tokens,
        "cache_read_tokens": record.cache_read_tokens,
        "cache_write_tokens": record.cache_write_tokens,
        "cost_usd": float(record.cost_usd),
        "duration_ms": record.duration_ms,
        "status_code": record.status_code,
        "tag_feature": tags.get("feature", ""),
        "tag_team": tags.get("team", ""),
        "tag_customer": tags.get("customer", ""),
        "tag_key_label": tags.get("key_label", ""),
        "system_prompt_hash": record.system_prompt_hash or "",
        "source_event_id": source_event_id(record),
    }


async def flush_stream_outbox(workspace_id: str, source_event_ids: list[str] | None = None) -> int:
    """Publish pending identity-bearing records and mark the outbox after broker ack.

    Broker delivery is at-least-once across a process crash; ClickHouse queries
    deduplicate non-empty ``source_event_id`` values, while Postgres remains the
    financial system of record.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        if source_event_ids:
            rows = await conn.fetch(
                """
                SELECT source_event_id, payload FROM stream_ingest_outbox
                WHERE workspace_id = $1 AND delivered_at IS NULL AND dead_lettered_at IS NULL
                  AND source_event_id = ANY($2::text[])
                ORDER BY created_at
                """,
                workspace_id,
                source_event_ids,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT source_event_id, payload FROM stream_ingest_outbox
                WHERE workspace_id = $1 AND delivered_at IS NULL AND dead_lettered_at IS NULL
                ORDER BY created_at LIMIT 1000
                """,
                workspace_id,
            )
    if not rows:
        return 0
    from .streaming import send_records_to_stream

    event_ids = [row["source_event_id"] for row in rows]
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE stream_ingest_outbox SET attempts = attempts + 1, last_attempt_at = NOW()
            WHERE workspace_id = $1 AND source_event_id = ANY($2::text[])
            """,
            workspace_id,
            event_ids,
        )
    try:
        payloads = [json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"] for row in rows]
        await send_records_to_stream(workspace_id, payloads, topic=settings.kafka_identity_topic)
    except Exception as exc:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE stream_ingest_outbox
                SET failed_attempts = failed_attempts + 1,
                    last_error = $3,
                    dead_lettered_at = CASE
                        WHEN attempts >= $4 THEN NOW() ELSE dead_lettered_at END
                WHERE workspace_id = $1 AND source_event_id = ANY($2::text[])
                """,
                workspace_id, event_ids, str(exc)[:1000], settings.outbox_max_attempts,
            )
        raise
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE stream_ingest_outbox SET delivered_at = NOW(), last_error = NULL
            WHERE workspace_id = $1 AND source_event_id = ANY($2::text[])
            """,
            workspace_id, event_ids,
        )
    return len(rows)


async def drain_stream_outbox() -> int:
    """Replay pending source-id stream records after a deploy or broker outage."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT workspace_id FROM stream_ingest_outbox
            WHERE delivered_at IS NULL AND dead_lettered_at IS NULL
            ORDER BY workspace_id
            LIMIT 100
            """
        )
    delivered = 0
    for row in rows:
        delivered += await flush_stream_outbox(str(row["workspace_id"]))
    return delivered
