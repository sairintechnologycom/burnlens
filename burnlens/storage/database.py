"""SQLite database setup with WAL mode and async access via aiosqlite."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import aiosqlite

from burnlens.storage.models import AiAsset, DiscoveryEvent, ProviderSignature, RequestRecord

logger = logging.getLogger(__name__)

_CREATE_REQUESTS_TABLE = """
CREATE TABLE IF NOT EXISTS requests (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT    NOT NULL,
    provider            TEXT    NOT NULL,
    model               TEXT    NOT NULL,
    request_path        TEXT    NOT NULL DEFAULT '',
    input_tokens        INTEGER NOT NULL DEFAULT 0,
    output_tokens       INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens    INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens   INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_usd            REAL    NOT NULL DEFAULT 0.0,
    duration_ms         INTEGER NOT NULL DEFAULT 0,
    status_code         INTEGER NOT NULL DEFAULT 200,
    tags                TEXT    NOT NULL DEFAULT '{}',
    system_prompt_hash  TEXT
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_requests_timestamp ON requests(timestamp);
"""
_CREATE_MODEL_INDEX = """
CREATE INDEX IF NOT EXISTS idx_requests_model ON requests(model);
"""

# ---------------------------------------------------------------------------
# Phase 1: Data Foundation — AI Asset Discovery tables
# ---------------------------------------------------------------------------

_CREATE_AI_ASSETS_TABLE = """
CREATE TABLE IF NOT EXISTS ai_assets (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    provider            TEXT    NOT NULL,
    model_name          TEXT    NOT NULL,
    endpoint_url        TEXT    NOT NULL,
    api_key_hash        TEXT,
    owner_team          TEXT,
    project             TEXT,
    status              TEXT    NOT NULL DEFAULT 'shadow'
                            CHECK(status IN ('active','inactive','shadow','approved','deprecated')),
    risk_tier           TEXT    NOT NULL DEFAULT 'unclassified'
                            CHECK(risk_tier IN ('unclassified','low','medium','high')),
    first_seen_at       TEXT    NOT NULL,
    last_active_at      TEXT    NOT NULL,
    monthly_spend_usd   REAL    NOT NULL DEFAULT 0.0,
    monthly_requests    INTEGER NOT NULL DEFAULT 0,
    tags                TEXT    NOT NULL DEFAULT '{}',
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);
"""

_CREATE_PROVIDER_SIGNATURES_TABLE = """
CREATE TABLE IF NOT EXISTS provider_signatures (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    provider            TEXT    NOT NULL UNIQUE,
    endpoint_pattern    TEXT    NOT NULL,
    header_signature    TEXT    NOT NULL DEFAULT '{}',
    model_field_path    TEXT    NOT NULL DEFAULT 'body.model'
);
"""

_CREATE_DISCOVERY_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS discovery_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type          TEXT    NOT NULL
                            CHECK(event_type IN ('new_asset_detected','model_changed','provider_changed','key_rotated','asset_inactive')),
    asset_id            INTEGER REFERENCES ai_assets(id),
    details             TEXT    NOT NULL DEFAULT '{}',
    detected_at         TEXT    NOT NULL
);
"""

# Append-only triggers for discovery_events
_TRIGGER_NO_UPDATE = """
CREATE TRIGGER IF NOT EXISTS prevent_discovery_events_update
BEFORE UPDATE ON discovery_events
BEGIN
    SELECT RAISE(ABORT, 'discovery_events is append-only: updates not allowed');
END;
"""

_TRIGGER_NO_DELETE = """
CREATE TRIGGER IF NOT EXISTS prevent_discovery_events_delete
BEFORE DELETE ON discovery_events
BEGIN
    SELECT RAISE(ABORT, 'discovery_events is append-only: deletes not allowed');
END;
"""

# Indexes for Phase 2+ query patterns
_CREATE_AI_ASSETS_PROVIDER_INDEX = """
CREATE INDEX IF NOT EXISTS idx_ai_assets_provider ON ai_assets(provider);
"""
_CREATE_AI_ASSETS_STATUS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_ai_assets_status ON ai_assets(status);
"""
_CREATE_AI_ASSETS_OWNER_TEAM_INDEX = """
CREATE INDEX IF NOT EXISTS idx_ai_assets_owner_team ON ai_assets(owner_team);
"""
_CREATE_AI_ASSETS_LAST_ACTIVE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_ai_assets_last_active ON ai_assets(last_active_at);
"""
_CREATE_DISCOVERY_EVENTS_ASSET_DETECTED_INDEX = """
CREATE INDEX IF NOT EXISTS idx_discovery_events_asset_detected ON discovery_events(asset_id, detected_at);
"""
_CREATE_PROVIDER_SIGNATURES_PROVIDER_INDEX = """
CREATE INDEX IF NOT EXISTS idx_provider_signatures_provider ON provider_signatures(provider);
"""

# Seed data for 7 providers — INSERT OR IGNORE is idempotent due to UNIQUE on provider
_SEED_PROVIDER_SIGNATURES = [
    ("openai", "api.openai.com/*", '{"keys":["authorization","openai-organization"]}', "body.model"),
    ("anthropic", "api.anthropic.com/*", '{"keys":["x-api-key","anthropic-version"]}', "body.model"),
    ("google", "generativelanguage.googleapis.com/*", '{"keys":["x-goog-api-key"]}', "body.model"),
    ("azure_openai", "*.openai.azure.com/*", '{"keys":["api-key"]}', "body.model"),
    ("bedrock", "bedrock-runtime.*.amazonaws.com/*", '{"keys":["authorization","x-amz-date"]}', "body.modelId"),
    ("cohere", "api.cohere.com/*", '{"keys":["authorization"]}', "body.model"),
    ("mistral", "api.mistral.ai/*", '{"keys":["authorization"]}', "body.model"),
]


async def init_db(db_path: str) -> None:
    """Create database directory, set WAL mode, and create tables."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")

        # Existing requests table
        await db.execute(_CREATE_REQUESTS_TABLE)
        await db.execute(_CREATE_INDEX)
        await db.execute(_CREATE_MODEL_INDEX)

        # Phase 1: Data Foundation tables
        await db.execute(_CREATE_AI_ASSETS_TABLE)
        await db.execute(_CREATE_PROVIDER_SIGNATURES_TABLE)
        await db.execute(_CREATE_DISCOVERY_EVENTS_TABLE)

        # Append-only triggers
        await db.execute(_TRIGGER_NO_UPDATE)
        await db.execute(_TRIGGER_NO_DELETE)

        # Indexes
        await db.execute(_CREATE_AI_ASSETS_PROVIDER_INDEX)
        await db.execute(_CREATE_AI_ASSETS_STATUS_INDEX)
        await db.execute(_CREATE_AI_ASSETS_OWNER_TEAM_INDEX)
        await db.execute(_CREATE_AI_ASSETS_LAST_ACTIVE_INDEX)
        await db.execute(_CREATE_DISCOVERY_EVENTS_ASSET_DETECTED_INDEX)
        await db.execute(_CREATE_PROVIDER_SIGNATURES_PROVIDER_INDEX)

        # Seed provider signatures (idempotent via INSERT OR IGNORE + UNIQUE constraint)
        await db.executemany(
            """
            INSERT OR IGNORE INTO provider_signatures
                (provider, endpoint_pattern, header_signature, model_field_path)
            VALUES (?, ?, ?, ?)
            """,
            _SEED_PROVIDER_SIGNATURES,
        )

        await db.commit()

    # Run cloud sync migration (safe to call on every startup)
    from burnlens.cloud.sync import migrate_add_synced_at
    await migrate_add_synced_at(db_path)

    logger.debug("Database initialized at %s", db_path)


async def get_requests_for_export(
    db_path: str,
    days: int = 7,
    team: str | None = None,
    feature: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch requests for CSV export, optionally filtered by team/feature tag."""
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    query = "SELECT * FROM requests WHERE timestamp >= ?"
    params: list[Any] = [since]

    if team:
        query += " AND json_extract(tags, '$.team') = ?"
        params.append(team)
    if feature:
        query += " AND json_extract(tags, '$.feature') = ?"
        params.append(feature)

    query += " ORDER BY timestamp ASC"

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_spend_by_team_this_month(db_path: str) -> dict[str, float]:
    """Return total spend per team tag for the current calendar month.

    Teams are identified by the ``team`` key inside the JSON ``tags`` column.
    Requests without a team tag are excluded.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT json_extract(tags, '$.team') AS team,
                   SUM(cost_usd) AS total_cost
            FROM requests
            WHERE timestamp >= ?
              AND json_extract(tags, '$.team') IS NOT NULL
            GROUP BY json_extract(tags, '$.team')
            """,
            (month_start,),
        )
        rows = await cursor.fetchall()

    return {row["team"]: float(row["total_cost"] or 0.0) for row in rows}


async def get_spend_by_customer_this_month(db_path: str) -> dict[str, float]:
    """Return total spend per customer tag for the current calendar month.

    Customers are identified by the ``customer`` key inside the JSON ``tags`` column.
    Requests without a customer tag are excluded.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT json_extract(tags, '$.customer') AS customer,
                   SUM(cost_usd) AS total_cost
            FROM requests
            WHERE timestamp >= ?
              AND json_extract(tags, '$.customer') IS NOT NULL
            GROUP BY json_extract(tags, '$.customer')
            """,
            (month_start,),
        )
        rows = await cursor.fetchall()

    return {row["customer"]: float(row["total_cost"] or 0.0) for row in rows}


async def get_customer_request_count(db_path: str, customer: str, days: int = 30) -> int:
    """Return total request count for a customer over the last N days."""
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            SELECT COUNT(*) FROM requests
            WHERE timestamp >= ?
              AND json_extract(tags, '$.customer') = ?
            """,
            (since, customer),
        )
        row = await cursor.fetchone()

    return int(row[0]) if row else 0


async def get_top_customers_by_cost(db_path: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return top customers by total cost for the current month.

    Each dict has: customer, request_count, input_tokens, output_tokens, total_cost.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT json_extract(tags, '$.customer') AS customer,
                   COUNT(*) AS request_count,
                   SUM(input_tokens) AS input_tokens,
                   SUM(output_tokens) AS output_tokens,
                   SUM(cost_usd) AS total_cost
            FROM requests
            WHERE timestamp >= ?
              AND json_extract(tags, '$.customer') IS NOT NULL
            GROUP BY json_extract(tags, '$.customer')
            ORDER BY total_cost DESC
            LIMIT ?
            """,
            (month_start, limit),
        )
        rows = await cursor.fetchall()

    return [
        {
            "customer": row["customer"],
            "request_count": row["request_count"],
            "input_tokens": row["input_tokens"] or 0,
            "output_tokens": row["output_tokens"] or 0,
            "total_cost": float(row["total_cost"] or 0.0),
        }
        for row in rows
    ]


async def insert_asset(db_path: str, asset: AiAsset) -> int:
    """Insert an AiAsset record and return its new row id.

    Tags are serialized to JSON. All datetime fields are stored as ISO format strings.
    """
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO ai_assets (
                provider, model_name, endpoint_url, api_key_hash,
                owner_team, project, status, risk_tier,
                first_seen_at, last_active_at,
                monthly_spend_usd, monthly_requests,
                tags, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset.provider,
                asset.model_name,
                asset.endpoint_url,
                asset.api_key_hash,
                asset.owner_team,
                asset.project,
                asset.status,
                asset.risk_tier,
                asset.first_seen_at.isoformat(),
                asset.last_active_at.isoformat(),
                asset.monthly_spend_usd,
                asset.monthly_requests,
                json.dumps(asset.tags),
                asset.created_at.isoformat(),
                asset.updated_at.isoformat(),
            ),
        )
        await db.commit()
        row_id: int = cursor.lastrowid  # type: ignore[assignment]
        return row_id


async def insert_discovery_event(db_path: str, event: DiscoveryEvent) -> int:
    """Insert a DiscoveryEvent record and return its new row id.

    Details are serialized to JSON. asset_id may be None for org-level events.
    """
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO discovery_events (event_type, asset_id, details, detected_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                event.event_type,
                event.asset_id,
                json.dumps(event.details),
                event.detected_at.isoformat(),
            ),
        )
        await db.commit()
        row_id = cursor.lastrowid  # type: ignore[assignment]
        return row_id


async def insert_provider_signature(db_path: str, sig: ProviderSignature) -> int:
    """Insert a ProviderSignature record and return its new row id.

    header_signature is serialized to JSON. Uses INSERT OR IGNORE semantics
    to avoid duplicating seeded providers; callers that need strict uniqueness
    should check the returned id (0 means the row already existed).
    """
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO provider_signatures
                (provider, endpoint_pattern, header_signature, model_field_path)
            VALUES (?, ?, ?, ?)
            """,
            (
                sig.provider,
                sig.endpoint_pattern,
                json.dumps(sig.header_signature),
                sig.model_field_path,
            ),
        )
        await db.commit()
        row_id: int = cursor.lastrowid  # type: ignore[assignment]
        return row_id


async def update_asset_status(db_path: str, asset_id: int, new_status: str) -> None:
    """Update the status of an ai_asset and auto-log a discovery_event.

    Both the UPDATE and the discovery_event INSERT happen in the same connection
    and are committed atomically.

    Raises:
        ValueError: If no asset with asset_id exists.
    """
    from datetime import datetime

    async with aiosqlite.connect(db_path) as db:
        # Read current status first
        cursor = await db.execute(
            "SELECT status FROM ai_assets WHERE id = ?", (asset_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError(f"Asset {asset_id} not found")

        old_status = row[0]
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        # Update status and updated_at
        await db.execute(
            "UPDATE ai_assets SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now, asset_id),
        )

        # Auto-log discovery event for the status change
        await db.execute(
            """
            INSERT INTO discovery_events (event_type, asset_id, details, detected_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "model_changed",
                asset_id,
                json.dumps({
                    "old_status": old_status,
                    "new_status": new_status,
                    "change": "status_update",
                }),
                now,
            ),
        )

        await db.commit()


async def insert_request(db_path: str, record: RequestRecord) -> int:
    """Insert a RequestRecord and return its new row id."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO requests (
                timestamp, provider, model, request_path,
                input_tokens, output_tokens, reasoning_tokens,
                cache_read_tokens, cache_write_tokens,
                cost_usd, duration_ms, status_code,
                tags, system_prompt_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.timestamp.isoformat(),
                record.provider,
                record.model,
                record.request_path,
                record.input_tokens,
                record.output_tokens,
                record.reasoning_tokens,
                record.cache_read_tokens,
                record.cache_write_tokens,
                record.cost_usd,
                record.duration_ms,
                record.status_code,
                json.dumps(record.tags),
                record.system_prompt_hash,
            ),
        )
        await db.commit()
        row_id: int = cursor.lastrowid  # type: ignore[assignment]
        return row_id
