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

_CREATE_DISCOVERY_EVENTS_ARCHIVE_TABLE = """
CREATE TABLE IF NOT EXISTS discovery_events_archive (
    id              INTEGER PRIMARY KEY,
    asset_id        INTEGER,
    event_type      TEXT NOT NULL,
    detected_at     TEXT NOT NULL,
    details         TEXT,
    archived_at     TEXT NOT NULL
);
"""

_CREATE_ARCHIVE_DETECTED_AT_INDEX = """
CREATE INDEX IF NOT EXISTS idx_archive_detected_at ON discovery_events_archive(detected_at);
"""

_CREATE_ARCHIVE_ASSET_ID_INDEX = """
CREATE INDEX IF NOT EXISTS idx_archive_asset_id ON discovery_events_archive(asset_id);
"""

_CREATE_FIRED_ALERTS_TABLE = """
CREATE TABLE IF NOT EXISTS fired_alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_key       TEXT NOT NULL,
    alert_type      TEXT NOT NULL,
    fired_at        TEXT NOT NULL,
    UNIQUE(alert_key, alert_type)
);
"""

_CREATE_FIRED_ALERTS_KEY_INDEX = """
CREATE INDEX IF NOT EXISTS idx_fired_alerts_key ON fired_alerts(alert_key, alert_type);
"""

_CREATE_FIRED_ALERTS_FIRED_AT_INDEX = """
CREATE INDEX IF NOT EXISTS idx_fired_alerts_fired_at ON fired_alerts(fired_at);
"""

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

        # Create tables
        await db.execute(_CREATE_REQUESTS_TABLE)
        await db.execute(_CREATE_INDEX)
        await db.execute(_CREATE_MODEL_INDEX)

        # Phase 4 tables
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

        # Discovery events archive table
        await db.execute(_CREATE_DISCOVERY_EVENTS_ARCHIVE_TABLE)
        await db.execute(_CREATE_ARCHIVE_DETECTED_AT_INDEX)
        await db.execute(_CREATE_ARCHIVE_ASSET_ID_INDEX)

        # Fired alerts dedup table
        await db.execute(_CREATE_FIRED_ALERTS_TABLE)
        await db.execute(_CREATE_FIRED_ALERTS_KEY_INDEX)
        await db.execute(_CREATE_FIRED_ALERTS_FIRED_AT_INDEX)

        # Seed provider signatures
        await db.executemany(
            """
            INSERT OR IGNORE INTO provider_signatures
                (provider, endpoint_pattern, header_signature, model_field_path)
            VALUES (?, ?, ?, ?)
            """,
            _SEED_PROVIDER_SIGNATURES,
        )

        await db.commit()

    # Run cloud sync migration
    from burnlens.cloud.sync import migrate_add_synced_at
    await migrate_add_synced_at(db_path)

    # CODE-1: git-aware tag columns
    await migrate_add_git_tags(db_path)

    # CODE-2: per-API-key daily caps
    await migrate_add_key_label(db_path)

    logger.debug("Database initialized at %s", db_path)


async def migrate_add_git_tags(db_path: str) -> None:
    """Add ``tag_repo / tag_dev / tag_pr / tag_branch`` columns + indices.

    Safe to call multiple times — uses ``PRAGMA table_info`` to detect
    existing columns. Indices use ``CREATE INDEX IF NOT EXISTS``.
    """
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA table_info(requests)")
        columns = {row[1] for row in await cursor.fetchall()}

        added = []
        for col in ("tag_repo", "tag_dev", "tag_pr", "tag_branch"):
            if col not in columns:
                await db.execute(f"ALTER TABLE requests ADD COLUMN {col} TEXT")
                added.append(col)

        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_requests_tag_repo ON requests(tag_repo)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_requests_tag_dev ON requests(tag_dev)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_requests_tag_pr ON requests(tag_pr)"
        )
        await db.commit()

        if added:
            logger.info(
                "Migration: added git tag columns to requests table: %s",
                ", ".join(added),
            )


async def migrate_add_key_label(db_path: str) -> None:
    """Add ``tag_key_label`` column to requests + create ``api_keys`` table.

    Safe to call multiple times — uses ``PRAGMA table_info`` to detect the
    existing column, and ``CREATE TABLE / INDEX IF NOT EXISTS`` for the rest.
    """
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA table_info(requests)")
        columns = {row[1] for row in await cursor.fetchall()}

        added_column = False
        if "tag_key_label" not in columns:
            await db.execute("ALTER TABLE requests ADD COLUMN tag_key_label TEXT")
            added_column = True

        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_requests_tag_key_label "
            "ON requests(tag_key_label)"
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                label         TEXT PRIMARY KEY,
                provider      TEXT NOT NULL,
                key_hash      TEXT NOT NULL,
                key_prefix    TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                last_used_at  TEXT
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash)"
        )

        await db.commit()

        if added_column:
            logger.info(
                "Migration: added tag_key_label column + api_keys table"
            )


async def get_requests_for_export(
    db_path: str,
    days: int = 7,
    team: str | None = None,
    feature: str | None = None,
    repo: str | None = None,
    dev: str | None = None,
    pr: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch requests for CSV export, optionally filtered by tag values.

    Supported filters: team, feature, repo, dev, pr — each maps to a key
    inside the JSON ``tags`` column.
    """
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

    if repo:
        query += " AND json_extract(tags, '$.repo') = ?"
        params.append(repo)

    if dev:
        query += " AND json_extract(tags, '$.dev') = ?"
        params.append(dev)

    if pr:
        query += " AND json_extract(tags, '$.pr') = ?"
        params.append(pr)

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

    return {row["team"]: row["total_cost"] for row in rows}


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

    return {row["customer"]: row["total_cost"] for row in rows}


async def get_customer_request_count(
    db_path: str,
    customer: str,
    days: int = 30,
) -> int:
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


async def get_top_customers_by_cost(
    db_path: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
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

    return [dict(row) for row in rows]


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
        row_id = cursor.lastrowid

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
        row_id = cursor.lastrowid

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
        row_id = cursor.lastrowid

    return row_id


async def update_asset_status(
    db_path: str,
    asset_id: int,
    new_status: str,
) -> None:
    """Update the status of an ai_asset and auto-log a discovery_event.

    Both the UPDATE and the discovery_event INSERT happen in the same connection
    and are committed atomically.

    Raises:
        ValueError: If no asset with asset_id exists.
    """
    from datetime import datetime

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT status FROM ai_assets WHERE id = ?",
            (asset_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError(f"Asset {asset_id} not found")

        old_status = row[0]

        from datetime import timezone

        now = datetime.now(timezone.utc).isoformat()

        await db.execute(
            "UPDATE ai_assets SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now, asset_id),
        )

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


async def was_alert_fired(
    db_path: str,
    alert_key: str,
    alert_type: str,
    within_hours: int = 24,
) -> bool:
    """Return True if this alert fired within the last ``within_hours`` hours."""
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=within_hours)).isoformat()

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            SELECT 1 FROM fired_alerts
            WHERE alert_key = ? AND alert_type = ? AND fired_at >= ?
            LIMIT 1
            """,
            (alert_key, alert_type, cutoff),
        )
        row = await cursor.fetchone()

    return row is not None


async def mark_alert_fired(
    db_path: str,
    alert_key: str,
    alert_type: str,
) -> None:
    """Insert or replace the fired record.

    Uses INSERT OR REPLACE so repeated calls update ``fired_at``
    (sliding window behaviour).
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO fired_alerts (alert_key, alert_type, fired_at)
            VALUES (?, ?, ?)
            """,
            (alert_key, alert_type, now),
        )
        await db.commit()


async def purge_old_fired_alerts(db_path: str, older_than_days: int = 30) -> int:
    """Delete fired_alerts records older than ``older_than_days`` days.

    Returns the number of rows deleted.
    """
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "DELETE FROM fired_alerts WHERE fired_at < ?",
            (cutoff,),
        )
        await db.commit()
        return cursor.rowcount


async def archive_old_discovery_events(db_path: str, retention_days: int = 90) -> int:
    """Move discovery_events older than retention_days to discovery_events_archive.

    Returns count of events archived.

    Strategy:
    1. BEGIN TRANSACTION
    2. INSERT INTO discovery_events_archive SELECT ... WHERE detected_at < cutoff
    3. Temporarily drop the append-only triggers
    4. DELETE FROM discovery_events WHERE detected_at < cutoff
    5. Recreate the append-only triggers
    6. COMMIT
    7. Run VACUUM to reclaim disk space (outside transaction)

    Returns 0 and logs warning on any exception — never raises.
    """
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    archived_at = datetime.now(timezone.utc).isoformat()

    try:
        async with aiosqlite.connect(db_path) as db:
            # Copy old events to archive
            await db.execute(
                """
                INSERT INTO discovery_events_archive
                    (id, asset_id, event_type, detected_at, details, archived_at)
                SELECT id, asset_id, event_type, detected_at, details, ?
                FROM discovery_events
                WHERE detected_at < ?
                """,
                (archived_at, cutoff),
            )

            # Count how many were archived
            cursor = await db.execute(
                "SELECT changes()",
            )
            row = await cursor.fetchone()
            count = row[0] if row else 0

            if count > 0:
                # Drop append-only triggers so we can delete
                await db.execute("DROP TRIGGER IF EXISTS prevent_discovery_events_update")
                await db.execute("DROP TRIGGER IF EXISTS prevent_discovery_events_delete")

                # Delete archived rows from the live table
                await db.execute(
                    "DELETE FROM discovery_events WHERE detected_at < ?",
                    (cutoff,),
                )

                # Recreate the append-only triggers
                await db.execute(_TRIGGER_NO_UPDATE)
                await db.execute(_TRIGGER_NO_DELETE)

            await db.commit()

        # VACUUM outside the transaction to reclaim disk space
        if count > 0:
            async with aiosqlite.connect(db_path) as db:
                await db.execute("VACUUM")

        return count
    except Exception as e:
        logger.warning("Discovery events archival failed (non-fatal): %s", e)
        return 0


async def get_spend_by_key_label_today(
    db_path: str,
    key_label: str,
    tz: Any,
) -> float:
    """Sum ``cost_usd`` for ``tag_key_label`` rows since local midnight in ``tz``.

    Compares against UTC-ISO strings since that is how ``requests.timestamp``
    is persisted. ``tz`` is a ``ZoneInfo`` (or ``timezone.utc``) — see
    ``burnlens.key_budget.resolve_timezone``.
    """
    # Lazy import to avoid an import cycle — key_budget imports from us.
    from burnlens.key_budget import today_window_utc

    start_utc, _ = today_window_utc(tz)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) FROM requests "
            "WHERE tag_key_label = ? AND timestamp >= ?",
            (key_label, start_utc.isoformat()),
        )
        row = await cursor.fetchone()
    return float(row[0] or 0.0)


async def get_spend_by_key_label_this_month(
    db_path: str,
    key_label: str,
    tz: Any,
) -> float:
    """Sum ``cost_usd`` for ``tag_key_label`` since the first of this month in ``tz``."""
    from burnlens.key_budget import month_start_utc

    start_utc = month_start_utc(tz)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) FROM requests "
            "WHERE tag_key_label = ? AND timestamp >= ?",
            (key_label, start_utc.isoformat()),
        )
        row = await cursor.fetchone()
    return float(row[0] or 0.0)


async def get_all_keys_today_spend(
    db_path: str,
    tz: Any,
) -> dict[str, float]:
    """Return ``{key_label: spent_usd}`` for every label with traffic today in ``tz``.

    Rows with a NULL ``tag_key_label`` (unregistered keys) are skipped — only
    labelled traffic shows up in the dashboard / ``burnlens keys`` output.
    """
    from burnlens.key_budget import today_window_utc

    start_utc, _ = today_window_utc(tz)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT tag_key_label, COALESCE(SUM(cost_usd), 0.0) FROM requests "
            "WHERE tag_key_label IS NOT NULL AND timestamp >= ? "
            "GROUP BY tag_key_label",
            (start_utc.isoformat(),),
        )
        rows = await cursor.fetchall()
    return {label: float(spent or 0.0) for label, spent in rows}


async def insert_request(db_path: str, record: RequestRecord) -> int:
    """Insert a RequestRecord and return its new row id."""
    tags = record.tags or {}
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO requests (
                timestamp, provider, model, request_path,
                input_tokens, output_tokens, reasoning_tokens,
                cache_read_tokens, cache_write_tokens,
                cost_usd, duration_ms, status_code,
                tags, system_prompt_hash,
                tag_repo, tag_dev, tag_pr, tag_branch, tag_key_label
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                tags.get("repo") or None,
                tags.get("dev") or None,
                tags.get("pr") or None,
                tags.get("branch") or None,
                tags.get("key_label") or None,
            ),
        )
        await db.commit()
        row_id = cursor.lastrowid

    return row_id
