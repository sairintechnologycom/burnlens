"""CODE-2: schema migration for per-API-key daily caps.

Covers ``migrate_add_key_label`` — adds ``tag_key_label`` column to the
``requests`` table and creates the ``api_keys`` table + index. Must be
idempotent so ``burnlens start`` can call it on every boot.
"""
from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from burnlens.storage.database import init_db, migrate_add_key_label


@pytest.mark.asyncio
async def test_init_db_creates_tag_key_label_column(tmp_path: Path) -> None:
    db_path = str(tmp_path / "burnlens.db")
    await init_db(db_path)

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA table_info(requests)")
        columns = {row[1] for row in await cursor.fetchall()}

    assert "tag_key_label" in columns


@pytest.mark.asyncio
async def test_init_db_creates_api_keys_table(tmp_path: Path) -> None:
    db_path = str(tmp_path / "burnlens.db")
    await init_db(db_path)

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA table_info(api_keys)")
        rows = await cursor.fetchall()

    columns = {row[1]: row for row in rows}
    assert set(columns) == {
        "label",
        "provider",
        "key_hash",
        "key_prefix",
        "created_at",
        "last_used_at",
    }
    assert columns["label"][5] == 1  # pk flag


@pytest.mark.asyncio
async def test_api_keys_label_is_unique(tmp_path: Path) -> None:
    db_path = str(tmp_path / "burnlens.db")
    await init_db(db_path)

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO api_keys (label, provider, key_hash, key_prefix, created_at) "
            "VALUES ('cursor-main', 'anthropic', 'abc', 'sk-ant-x', '2026-04-28T00:00:00Z')"
        )
        await db.commit()

        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                "INSERT INTO api_keys (label, provider, key_hash, key_prefix, created_at) "
                "VALUES ('cursor-main', 'openai', 'def', 'sk-x', '2026-04-28T00:00:00Z')"
            )


@pytest.mark.asyncio
async def test_migration_creates_required_indexes(tmp_path: Path) -> None:
    db_path = str(tmp_path / "burnlens.db")
    await init_db(db_path)

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        indexes = {row[0] for row in await cursor.fetchall()}

    assert "idx_requests_tag_key_label" in indexes
    assert "idx_api_keys_hash" in indexes


@pytest.mark.asyncio
async def test_migration_is_idempotent(tmp_path: Path) -> None:
    db_path = str(tmp_path / "burnlens.db")
    await init_db(db_path)

    # Re-run the migration directly. Must not raise (no duplicate column,
    # no duplicate table) even though both already exist.
    await migrate_add_key_label(db_path)
    await migrate_add_key_label(db_path)

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA table_info(requests)")
        columns = [row[1] for row in await cursor.fetchall()]

    # tag_key_label appears exactly once
    assert columns.count("tag_key_label") == 1


@pytest.mark.asyncio
async def test_migration_preserves_existing_request_data(tmp_path: Path) -> None:
    """Re-running the migration must not blow away rows already in requests."""
    db_path = str(tmp_path / "burnlens.db")
    await init_db(db_path)

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO requests (timestamp, provider, model) "
            "VALUES ('2026-04-28T00:00:00Z', 'anthropic', 'claude-3-5-sonnet-20241022')"
        )
        await db.commit()

    await migrate_add_key_label(db_path)

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM requests")
        (count,) = await cursor.fetchone()

    assert count == 1
