"""SQLite database setup with WAL mode and async access via aiosqlite."""
from __future__ import annotations

import json
import logging
from pathlib import Path

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
