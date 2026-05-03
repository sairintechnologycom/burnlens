"""Tests for the Cursor session disk reader (SCAN-2)."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from burnlens.cost.calculator import TokenUsage, calculate_cost
from burnlens.scan import cursor as cur
from burnlens.scan._common import _reset_dev_identity_cache
from burnlens.scan.cursor import (
    AUTO_MODEL_LABEL,
    CursorBubble,
    bubble_to_record,
    cursor_db_path,
    read_bubbles,
    scan_cursor,
)
from burnlens.storage.database import init_db


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _make_cursor_db(
    path: Path,
    bubbles: list[tuple[str, dict | str]],
    extra_rows: list[tuple[str, str]] | None = None,
) -> Path:
    """Build a synthetic Cursor state.vscdb for tests.

    Each bubble entry is (bubble_id, json_dict_or_raw_string). If a raw
    string is passed it's stored verbatim (used for malformed-JSON tests).
    Extra rows let the test mix in non-bubble keys to prove the LIKE filter.
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE cursorDiskKV (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)"
        )
        for bubble_id, payload in bubbles:
            value = payload if isinstance(payload, str) else json.dumps(payload)
            conn.execute(
                "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
                (f"bubbleId:{bubble_id}", value),
            )
        for key, value in extra_rows or []:
            conn.execute(
                "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)", (key, value)
            )
        conn.commit()
    finally:
        conn.close()
    return path


def _bubble_payload(
    *,
    conv: str = "conv-1",
    model: str = "claude-sonnet-4-6",
    input_tokens: int = 1000,
    output_tokens: int = 200,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    timestamp_ms: int = 1_777_777_700_000,
    workspace: str | None = "/tmp/fake/burnlens",
) -> dict:
    payload = {
        "conversationId": conv,
        "model": model,
        "timestamp": timestamp_ms,
        "tokenCount": {
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "cacheReadTokens": cache_read_tokens,
            "cacheWriteTokens": cache_write_tokens,
        },
    }
    if workspace is not None:
        payload["workspacePath"] = workspace
    return payload


@pytest.fixture
def populated_cursor_db(tmp_path: Path) -> Path:
    """Build a Cursor DB with a representative spread of bubbles."""
    db = tmp_path / "state.vscdb"
    return _make_cursor_db(
        db,
        bubbles=[
            ("b-001", _bubble_payload(conv="conv-1")),
            (
                "b-002",
                _bubble_payload(
                    conv="conv-1",
                    model="auto",
                    input_tokens=300,
                    output_tokens=80,
                ),
            ),
            (
                "b-003",
                _bubble_payload(
                    conv="conv-2",
                    model="gpt-4o",
                    input_tokens=400,
                    output_tokens=50,
                ),
            ),
            (
                "b-zero",
                _bubble_payload(
                    conv="conv-3",
                    input_tokens=0,
                    output_tokens=0,
                    cache_read_tokens=0,
                    cache_write_tokens=0,
                ),
            ),
            ("b-malformed", "{not-valid-json"),
        ],
        extra_rows=[("composerData:abc", "{}")],
    )


@pytest_asyncio.fixture
async def initialized_db(tmp_path: Path) -> str:
    db = str(tmp_path / "burnlens.db")
    await init_db(db)
    return db


@pytest.fixture(autouse=True)
def _isolate_caches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect the on-disk Cursor cache to tmp_path so tests don't pollute $HOME."""
    cache_dir = tmp_path / "burnlens_cache"
    cache_file = cache_dir / "cursor_parsed.json"
    monkeypatch.setattr(cur, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(cur, "CACHE_FILE", cache_file)
    _reset_dev_identity_cache()
    yield
    _reset_dev_identity_cache()


# ---------------------------------------------------------------------------
# cursor_db_path
# ---------------------------------------------------------------------------


def test_cursor_db_path_returns_none_when_missing(monkeypatch, tmp_path):
    fake_home = tmp_path / "no-home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("APPDATA", str(fake_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    assert cursor_db_path() is None


def test_cursor_db_path_returns_path_when_present(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    if sys.platform == "darwin":
        target = (
            fake_home
            / "Library"
            / "Application Support"
            / "Cursor"
            / "User"
            / "globalStorage"
            / "state.vscdb"
        )
    elif sys.platform.startswith("linux"):
        target = (
            fake_home / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb"
        )
    elif sys.platform == "win32":
        target = (
            fake_home / "Cursor" / "User" / "globalStorage" / "state.vscdb"
        )
        monkeypatch.setenv("APPDATA", str(fake_home))
    else:
        pytest.skip(f"No cursor_db_path coverage for platform {sys.platform!r}")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"fake")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    assert cursor_db_path() == target


# ---------------------------------------------------------------------------
# read_bubbles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_bubbles_extracts_token_counts(populated_cursor_db: Path):
    bubbles = await read_bubbles(populated_cursor_db)
    by_id = {b.bubble_id: b for b in bubbles}
    assert "b-001" in by_id
    b = by_id["b-001"]
    assert b.input_tokens == 1000
    assert b.output_tokens == 200
    assert b.conversation_id == "conv-1"
    assert b.model == "claude-sonnet-4-6"
    assert b.workspace_path == "/tmp/fake/burnlens"


@pytest.mark.asyncio
async def test_read_bubbles_skips_zero_token_rows(populated_cursor_db: Path):
    ids = {b.bubble_id for b in await read_bubbles(populated_cursor_db)}
    assert "b-zero" not in ids


@pytest.mark.asyncio
async def test_read_bubbles_skips_non_bubble_rows(populated_cursor_db: Path):
    ids = {b.bubble_id for b in await read_bubbles(populated_cursor_db)}
    # composerData:abc was inserted but should not surface.
    assert all(not i.startswith("composerData") for i in ids)


@pytest.mark.asyncio
async def test_read_bubbles_handles_malformed_json(populated_cursor_db: Path):
    bubbles = await read_bubbles(populated_cursor_db)
    # b-malformed must be silently skipped, not crash the read.
    assert "b-malformed" not in {b.bubble_id for b in bubbles}
    # And we still got the well-formed bubbles.
    assert {"b-001", "b-002", "b-003"}.issubset({b.bubble_id for b in bubbles})


@pytest.mark.asyncio
async def test_auto_model_relabeled_as_sonnet_estimate(populated_cursor_db: Path):
    by_id = {b.bubble_id: b for b in await read_bubbles(populated_cursor_db)}
    assert by_id["b-002"].model == AUTO_MODEL_LABEL


@pytest.mark.asyncio
async def test_read_bubbles_filters_by_since(populated_cursor_db: Path):
    cutoff = datetime.fromtimestamp(1_777_777_700, tz=timezone.utc) + timedelta(days=1)
    bubbles = await read_bubbles(populated_cursor_db, since=cutoff)
    assert bubbles == []


# ---------------------------------------------------------------------------
# Cost routing for provider='cursor'
# ---------------------------------------------------------------------------


def test_cursor_provider_falls_back_to_anthropic_pricing():
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=0)
    via_cursor = calculate_cost("cursor", "claude-sonnet-4-6", usage)
    direct = calculate_cost("anthropic", "claude-sonnet-4-6", usage)
    assert via_cursor == pytest.approx(direct)
    assert via_cursor > 0


def test_cursor_auto_relabel_routes_to_sonnet_pricing():
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=0)
    via_auto = calculate_cost("cursor", AUTO_MODEL_LABEL, usage)
    sonnet = calculate_cost("anthropic", "claude-sonnet-4-6", usage)
    assert via_auto == pytest.approx(sonnet)


def test_cursor_provider_falls_back_to_openai_pricing():
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=0)
    via_cursor = calculate_cost("cursor", "gpt-4o", usage)
    direct = calculate_cost("openai", "gpt-4o", usage)
    assert via_cursor == pytest.approx(direct)
    assert via_cursor > 0


def test_cursor_provider_unknown_model_returns_zero():
    usage = TokenUsage(input_tokens=100, output_tokens=100)
    assert calculate_cost("cursor", "weird-unknown-model", usage) == 0.0


# ---------------------------------------------------------------------------
# bubble_to_record
# ---------------------------------------------------------------------------


def test_bubble_to_record_populates_provenance_fields(monkeypatch):
    monkeypatch.setenv("USER", "test-runner")
    bubble = CursorBubble(
        bubble_id="b-1",
        conversation_id="conv-x",
        model="claude-sonnet-4-6",
        input_tokens=1000,
        output_tokens=100,
        cache_read_tokens=0,
        cache_write_tokens=0,
        timestamp=datetime(2026, 5, 3, tzinfo=timezone.utc),
        workspace_path="/tmp/fake/burnlens",
    )
    rec = bubble_to_record(bubble)
    assert rec.provider == "cursor"
    assert rec.source == "scan_cursor"
    assert rec.request_id == "b-1"
    assert rec.tags["repo"] == "burnlens"
    assert rec.tags["session"] == "conv-x"
    assert rec.cost_usd > 0


# ---------------------------------------------------------------------------
# scan_cursor end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_cursor_inserts_records_and_skips_dupes(
    initialized_db: str, populated_cursor_db: Path
):
    first = await scan_cursor(initialized_db, cursor_db=populated_cursor_db)
    assert first.bubbles_parsed == 3  # b-001, b-002, b-003 (zero + malformed dropped)
    assert first.records_inserted == 3
    assert first.records_skipped == 0
    assert first.auto_mode_bubbles == 1

    second = await scan_cursor(
        initialized_db, cursor_db=populated_cursor_db, use_cache=False
    )
    # mtime + size unchanged but use_cache=False forces a real scan.
    assert second.records_inserted == 0
    assert second.records_skipped == 3

    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM requests WHERE source = 'scan_cursor'"
        )
        (count,) = await cursor.fetchone()
    assert count == 3


@pytest.mark.asyncio
async def test_scan_cursor_dry_run_does_not_insert(
    initialized_db: str, populated_cursor_db: Path
):
    result = await scan_cursor(
        initialized_db, cursor_db=populated_cursor_db, dry_run=True
    )
    assert result.bubbles_parsed == 3
    assert result.records_inserted == 0
    assert result.records_skipped == 0

    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM requests WHERE source = 'scan_cursor'"
        )
        (count,) = await cursor.fetchone()
    assert count == 0


@pytest.mark.asyncio
async def test_cache_skips_unchanged_db(
    initialized_db: str, populated_cursor_db: Path
):
    first = await scan_cursor(initialized_db, cursor_db=populated_cursor_db)
    assert first.skipped_due_to_cache is False
    assert first.records_inserted == 3

    second = await scan_cursor(initialized_db, cursor_db=populated_cursor_db)
    assert second.skipped_due_to_cache is True
    assert second.bubbles_parsed == 0


@pytest.mark.asyncio
async def test_cache_invalidates_on_mtime_change(
    initialized_db: str, populated_cursor_db: Path
):
    first = await scan_cursor(initialized_db, cursor_db=populated_cursor_db)
    assert first.records_inserted == 3

    # Bump mtime to invalidate cache; content unchanged so dedup index handles it.
    import os
    new_ts = first.db_mtime + 100
    os.utime(populated_cursor_db, (new_ts, new_ts))

    second = await scan_cursor(initialized_db, cursor_db=populated_cursor_db)
    assert second.skipped_due_to_cache is False
    assert second.bubbles_parsed == 3
    assert second.records_inserted == 0  # all dedup'd by idx_scan_dedup
    assert second.records_skipped == 3


@pytest.mark.asyncio
async def test_scan_cursor_returns_empty_when_db_missing(initialized_db: str, tmp_path: Path):
    missing = tmp_path / "does-not-exist.vscdb"
    result = await scan_cursor(initialized_db, cursor_db=missing)
    assert result.bubbles_parsed == 0
    assert result.records_inserted == 0
    assert result.db_path is None


@pytest.mark.asyncio
async def test_dedup_unique_index_prevents_duplicate_bubbles(
    initialized_db: str, populated_cursor_db: Path
):
    # Run scan twice, bypassing cache both times, and confirm no duplicates land.
    await scan_cursor(initialized_db, cursor_db=populated_cursor_db, use_cache=False)
    await scan_cursor(initialized_db, cursor_db=populated_cursor_db, use_cache=False)

    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute(
            "SELECT request_id, COUNT(*) FROM requests "
            "WHERE source = 'scan_cursor' GROUP BY request_id"
        )
        rows = await cursor.fetchall()
    assert rows
    assert all(count == 1 for _, count in rows)
