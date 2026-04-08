"""SQLite database setup with WAL mode and async access via aiosqlite."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import aiosqlite

from burnlens.storage.models import RequestRecord

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


async def init_db(db_path: str) -> None:
    """Create database directory, set WAL mode, and create tables."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute(_CREATE_REQUESTS_TABLE)
        await db.execute(_CREATE_INDEX)
        await db.execute(_CREATE_MODEL_INDEX)
        await db.commit()

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
