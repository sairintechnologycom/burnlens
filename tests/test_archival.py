"""Tests for discovery_events archival to archive table."""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest

from burnlens.storage.database import (
    archive_old_discovery_events,
    init_db,
)


@pytest.fixture
async def db_path(tmp_path: Path) -> str:
    """Create a temporary database with schema initialized."""
    path = str(tmp_path / "test.db")
    await init_db(path)
    return path


async def _insert_event(
    db_path: str,
    event_type: str,
    asset_id: int | None,
    details: str,
    detected_at: str,
) -> int:
    """Insert a discovery_event via raw SQL and return its id."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO discovery_events (event_type, asset_id, details, detected_at)
            VALUES (?, ?, ?, ?)
            """,
            (event_type, asset_id, details, detected_at),
        )
        await db.commit()
        return cursor.lastrowid


async def _count_rows(db_path: str, table: str) -> int:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
        row = await cursor.fetchone()
        return row[0]


async def _get_all_rows(db_path: str, table: str) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(f"SELECT * FROM {table}")  # noqa: S608
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


def _days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


@pytest.mark.asyncio
async def test_archive_moves_old_events(db_path: str) -> None:
    """Old events move to archive, recent events stay in live table."""
    old_ts = _days_ago(91)
    new_ts = _days_ago(10)

    for i in range(5):
        await _insert_event(db_path, "new_asset_detected", i + 1, "{}", old_ts)
    for i in range(3):
        await _insert_event(db_path, "new_asset_detected", i + 10, "{}", new_ts)

    count = await archive_old_discovery_events(db_path, retention_days=90)

    assert count == 5
    assert await _count_rows(db_path, "discovery_events") == 3
    assert await _count_rows(db_path, "discovery_events_archive") == 5


@pytest.mark.asyncio
async def test_archive_preserves_all_fields(db_path: str) -> None:
    """Archived rows retain id, asset_id, event_type, detected_at, details; archived_at is set."""
    old_ts = _days_ago(100)
    details = '{"info": "test_data"}'
    row_id = await _insert_event(db_path, "model_changed", 42, details, old_ts)

    await archive_old_discovery_events(db_path, retention_days=90)

    archived = await _get_all_rows(db_path, "discovery_events_archive")
    assert len(archived) == 1

    row = archived[0]
    assert row["id"] == row_id
    assert row["asset_id"] == 42
    assert row["event_type"] == "model_changed"
    assert row["detected_at"] == old_ts
    assert row["details"] == details
    # archived_at should be a valid ISO timestamp
    datetime.fromisoformat(row["archived_at"])


@pytest.mark.asyncio
async def test_archive_trigger_recreated(db_path: str) -> None:
    """After archival, the append-only trigger must still block deletes."""
    old_ts = _days_ago(100)
    await _insert_event(db_path, "new_asset_detected", 1, "{}", old_ts)

    await archive_old_discovery_events(db_path, retention_days=90)

    # Insert a new event, then try to delete it — trigger should block
    new_ts = _days_ago(1)
    await _insert_event(db_path, "new_asset_detected", 2, "{}", new_ts)

    async with aiosqlite.connect(db_path) as db:
        with pytest.raises(Exception, match="append-only"):
            await db.execute("DELETE FROM discovery_events WHERE id = 2")


@pytest.mark.asyncio
async def test_archive_returns_count(db_path: str) -> None:
    """Returns the correct count of archived events."""
    old_ts = _days_ago(95)
    for _ in range(7):
        await _insert_event(db_path, "new_asset_detected", 1, "{}", old_ts)

    count = await archive_old_discovery_events(db_path, retention_days=90)
    assert count == 7


@pytest.mark.asyncio
async def test_archive_empty_table_no_crash(db_path: str) -> None:
    """Archival on empty discovery_events returns 0 without error."""
    count = await archive_old_discovery_events(db_path, retention_days=90)
    assert count == 0


@pytest.mark.asyncio
async def test_archive_does_not_touch_recent_events(db_path: str) -> None:
    """Events from today must be left untouched by archival."""
    today_ts = datetime.now(timezone.utc).isoformat()
    await _insert_event(db_path, "new_asset_detected", 1, "{}", today_ts)

    count = await archive_old_discovery_events(db_path, retention_days=90)

    assert count == 0
    assert await _count_rows(db_path, "discovery_events") == 1
    assert await _count_rows(db_path, "discovery_events_archive") == 0
