"""Tests for the Codex (OpenAI) session disk reader (SCAN-3)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from burnlens.cost.calculator import TokenUsage, calculate_cost
from burnlens.scan._common import _reset_dev_identity_cache
from burnlens.scan.codex import (
    CodexScanResult,
    CodexSession,
    codex_sessions_dir,
    discover_sessions,
    parse_session,
    scan_codex,
)
from burnlens.storage.database import init_db

# ---------------------------------------------------------------------------
# Fixtures directory
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "codex_sessions"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_session(path: Path, lines: list[dict | str]) -> Path:
    """Write a rollout JSONL file. Strings are written verbatim for malformed-line tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for line in lines:
            fh.write((line if isinstance(line, str) else json.dumps(line)) + "\n")
    return path


def _token_count_event(
    *,
    input_tokens: int = 1000,
    cached_input_tokens: int = 0,
    output_tokens: int = 200,
    reasoning_output_tokens: int = 0,
    timestamp: str = "2026-01-09T10:00:05.000Z",
) -> dict:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "last_token_usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached_input_tokens,
                    "output_tokens": output_tokens,
                    "reasoning_output_tokens": reasoning_output_tokens,
                    "total_tokens": input_tokens + output_tokens + reasoning_output_tokens,
                },
                "total_token_usage": {},
            },
            "rate_limits": {},
        },
    }


def _turn_context(model: str = "gpt-4o") -> dict:
    return {"timestamp": "2026-01-09T10:00:00.001Z", "type": "turn_context", "payload": {"model": model}}


def _session_meta(cwd: str = "/tmp/project") -> dict:
    return {
        "timestamp": "2026-01-09T10:00:00.000Z",
        "type": "session_meta",
        "payload": {"id": "test-session", "cwd": cwd},
    }


@pytest_asyncio.fixture
async def initialized_db(tmp_path: Path) -> str:
    db = str(tmp_path / "burnlens.db")
    await init_db(db)
    return db


@pytest.fixture(autouse=True)
def _reset_identity_cache():
    _reset_dev_identity_cache()
    yield
    _reset_dev_identity_cache()


# ---------------------------------------------------------------------------
# codex_sessions_dir
# ---------------------------------------------------------------------------


def test_codex_sessions_dir_default(monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    expected = Path.home() / ".codex" / "sessions"
    assert codex_sessions_dir() == expected


def test_codex_sessions_dir_respects_codex_home_env(monkeypatch, tmp_path):
    custom = tmp_path / "my-codex"
    monkeypatch.setenv("CODEX_HOME", str(custom))
    assert codex_sessions_dir() == custom / "sessions"


# ---------------------------------------------------------------------------
# discover_sessions
# ---------------------------------------------------------------------------


def test_discover_sessions_walks_yyyy_mm_dd_structure(tmp_path):
    # 3 session files across 2 days
    _write_session(tmp_path / "2026" / "01" / "09" / "rollout-2026-01-09T10-00-00-abc.jsonl", [])
    _write_session(tmp_path / "2026" / "01" / "09" / "rollout-2026-01-09T11-00-00-def.jsonl", [])
    _write_session(tmp_path / "2026" / "01" / "10" / "rollout-2026-01-10T08-00-00-xyz.jsonl", [])

    sessions = discover_sessions(sessions_dir=tmp_path)
    assert len(sessions) == 3


def test_discover_sessions_only_includes_rollout_files(tmp_path):
    # rollout file vs other files
    _write_session(tmp_path / "2026" / "01" / "09" / "rollout-2026-01-09T10-00-00-abc.jsonl", [])
    (tmp_path / "2026" / "01" / "09" / "other-file.jsonl").write_text("{}")

    sessions = discover_sessions(sessions_dir=tmp_path)
    assert len(sessions) == 1
    assert sessions[0].session_id == "2026-01-09T10-00-00-abc"


def test_discover_sessions_filters_by_since(tmp_path):
    p1 = tmp_path / "2026" / "01" / "09" / "rollout-2026-01-09T10-00-00-abc.jsonl"
    _write_session(p1, [])

    cutoff = datetime.fromtimestamp(p1.stat().st_mtime, tz=timezone.utc) + timedelta(seconds=1)
    sessions = discover_sessions(since=cutoff, sessions_dir=tmp_path)
    assert sessions == []


def test_discover_sessions_returns_empty_when_dir_missing(tmp_path):
    sessions = discover_sessions(sessions_dir=tmp_path / "nonexistent")
    assert sessions == []


# ---------------------------------------------------------------------------
# parse_session — token extraction
# ---------------------------------------------------------------------------


def test_parse_session_extracts_token_count_events(tmp_path):
    path = tmp_path / "2026" / "01" / "09" / "rollout-s1.jsonl"
    _write_session(path, [
        _session_meta("/tmp/myapp"),
        _turn_context("gpt-4o"),
        _token_count_event(input_tokens=1000, output_tokens=200),
        _token_count_event(input_tokens=500, output_tokens=100),
    ])
    session = CodexSession(session_id="s1", file_path=path, date=None)
    records = list(parse_session(session))
    assert len(records) == 2
    assert records[0].input_tokens == 1000
    assert records[0].output_tokens == 200
    assert records[1].input_tokens == 500


def test_parse_session_skips_null_info_events(tmp_path):
    """Rate-limit-only token_count events (info=null) must be skipped."""
    path = tmp_path / "2026" / "01" / "09" / "rollout-s2.jsonl"
    _write_session(path, [
        _session_meta(),
        _turn_context("gpt-4o"),
        {
            "type": "event_msg",
            "payload": {"type": "token_count", "info": None, "rate_limits": {}},
        },
        _token_count_event(input_tokens=300, output_tokens=50),
    ])
    session = CodexSession(session_id="s2", file_path=path, date=None)
    records = list(parse_session(session))
    assert len(records) == 1
    assert records[0].input_tokens == 300


def test_parse_session_skips_function_call_events(tmp_path):
    path = tmp_path / "2026" / "01" / "09" / "rollout-s3.jsonl"
    _write_session(path, [
        _session_meta(),
        _turn_context("gpt-4o"),
        {
            "type": "response_item",
            "payload": {"type": "function_call", "name": "shell_command", "arguments": "{}"},
        },
        _token_count_event(input_tokens=100, output_tokens=10),
    ])
    session = CodexSession(session_id="s3", file_path=path, date=None)
    records = list(parse_session(session))
    assert len(records) == 1  # only the token_count, not the function_call


def test_parse_session_skips_message_events(tmp_path):
    path = tmp_path / "2026" / "01" / "09" / "rollout-s4.jsonl"
    _write_session(path, [
        _session_meta(),
        _turn_context("gpt-4o"),
        {"type": "event_msg", "payload": {"type": "agent_message", "message": "hello"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "hi"}},
        _token_count_event(input_tokens=200, output_tokens=30),
    ])
    session = CodexSession(session_id="s4", file_path=path, date=None)
    records = list(parse_session(session))
    assert len(records) == 1


def test_parse_session_extracts_reasoning_tokens(tmp_path):
    path = tmp_path / "2026" / "01" / "10" / "rollout-s5.jsonl"
    _write_session(path, [
        _session_meta("/tmp/webapp"),
        _turn_context("o3"),
        _token_count_event(
            input_tokens=2000,
            cached_input_tokens=0,
            output_tokens=400,
            reasoning_output_tokens=1500,
        ),
    ])
    session = CodexSession(session_id="s5", file_path=path, date=None)
    records = list(parse_session(session))
    assert len(records) == 1
    assert records[0].reasoning_tokens == 1500
    assert records[0].model == "o3"


def test_parse_session_request_id_is_session_plus_ordinal(tmp_path):
    path = tmp_path / "2026" / "01" / "09" / "rollout-my-session.jsonl"
    _write_session(path, [
        _session_meta(),
        _turn_context("gpt-4o"),
        # null-info event bumps ordinal to 0, no record yielded
        {"type": "event_msg", "payload": {"type": "token_count", "info": None, "rate_limits": {}}},
        # ordinal 1 — first yielded record
        _token_count_event(input_tokens=100, output_tokens=10),
        # ordinal 2 — second yielded record
        _token_count_event(input_tokens=200, output_tokens=20),
    ])
    session = CodexSession(session_id="my-session", file_path=path, date=None)
    records = list(parse_session(session))
    assert len(records) == 2
    assert records[0].request_id == "my-session:1"
    assert records[1].request_id == "my-session:2"


def test_parse_session_handles_malformed_jsonl_line(tmp_path):
    path = tmp_path / "2026" / "01" / "09" / "rollout-s6.jsonl"
    _write_session(path, [
        _session_meta(),
        _turn_context("gpt-4o"),
        "not valid json at all }{",
        _token_count_event(input_tokens=100, output_tokens=10),
    ])
    session = CodexSession(session_id="s6", file_path=path, date=None)
    records = list(parse_session(session))
    # malformed line skipped, valid event still parsed
    assert len(records) == 1


def test_parse_session_skips_event_without_preceding_model(tmp_path):
    """token_count events before any turn_context must be skipped."""
    path = tmp_path / "2026" / "01" / "09" / "rollout-s7.jsonl"
    _write_session(path, [
        _session_meta(),
        # no turn_context before the token count
        _token_count_event(input_tokens=500, output_tokens=100),
        _turn_context("gpt-4o"),
        _token_count_event(input_tokens=300, output_tokens=50),
    ])
    session = CodexSession(session_id="s7", file_path=path, date=None)
    records = list(parse_session(session))
    assert len(records) == 1
    assert records[0].input_tokens == 300


def test_parse_session_missing_file_no_crash(tmp_path):
    session = CodexSession(
        session_id="ghost",
        file_path=tmp_path / "nonexistent" / "rollout-ghost.jsonl",
        date=None,
    )
    assert list(parse_session(session)) == []


# ---------------------------------------------------------------------------
# Cost routing
# ---------------------------------------------------------------------------


def test_codex_uses_openai_pricing_for_known_model():
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=0)
    codex_cost = calculate_cost("openai", "gpt-4o", usage)
    assert codex_cost > 0


def test_codex_unknown_model_returns_zero_cost():
    """Unknown models (e.g. gpt-5.2-codex not in pricing) return 0 — not an error."""
    usage = TokenUsage(input_tokens=10_000, output_tokens=1_000)
    cost = calculate_cost("openai", "gpt-5.2-codex", usage)
    assert cost == 0.0


def test_codex_reasoning_tokens_included_in_o3_cost():
    """o3 reasoning tokens are billed at the reasoning rate."""
    usage_with = TokenUsage(input_tokens=1000, output_tokens=100, reasoning_tokens=5000)
    usage_without = TokenUsage(input_tokens=1000, output_tokens=100, reasoning_tokens=0)
    cost_with = calculate_cost("openai", "o3", usage_with)
    cost_without = calculate_cost("openai", "o3", usage_without)
    assert cost_with > cost_without


# ---------------------------------------------------------------------------
# scan_codex end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_does_not_insert(initialized_db: str, tmp_path: Path):
    sessions_dir = tmp_path / "codex_sessions"
    path = sessions_dir / "2026" / "01" / "09" / "rollout-dry.jsonl"
    _write_session(path, [_session_meta(), _turn_context("gpt-4o"), _token_count_event()])

    result = await scan_codex(initialized_db, dry_run=True, sessions_dir=sessions_dir)
    assert result.events_parsed == 1
    assert result.records_inserted == 0

    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM requests WHERE source = 'scan_codex'")
        (count,) = await cursor.fetchone()
    assert count == 0


@pytest.mark.asyncio
async def test_dedup_prevents_duplicate_events_on_rescan(initialized_db: str, tmp_path: Path):
    sessions_dir = tmp_path / "codex_sessions"
    path = sessions_dir / "2026" / "01" / "09" / "rollout-dedup.jsonl"
    _write_session(path, [
        _session_meta(),
        _turn_context("gpt-4o"),
        _token_count_event(input_tokens=1000, output_tokens=200),
        _token_count_event(input_tokens=500, output_tokens=100),
    ])

    first = await scan_codex(initialized_db, sessions_dir=sessions_dir)
    assert first.records_inserted == 2
    assert first.records_skipped == 0

    second = await scan_codex(initialized_db, sessions_dir=sessions_dir)
    assert second.records_inserted == 0
    assert second.records_skipped == 2

    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute(
            "SELECT request_id, COUNT(*) FROM requests WHERE source='scan_codex' GROUP BY request_id"
        )
        rows = await cursor.fetchall()
    assert all(count == 1 for _, count in rows)


@pytest.mark.asyncio
async def test_missing_codex_dir_no_crash(initialized_db: str, tmp_path: Path):
    result = await scan_codex(initialized_db, sessions_dir=tmp_path / "no-such-dir")
    assert result.sessions_found == 0
    assert result.events_parsed == 0
    assert result.records_inserted == 0


@pytest.mark.asyncio
async def test_scan_codex_uses_real_fixtures(initialized_db: str):
    """Smoke test against the committed fixture files."""
    if not FIXTURES_DIR.exists():
        pytest.skip("Fixture directory not found")

    result = await scan_codex(initialized_db, sessions_dir=FIXTURES_DIR)
    # gpt5codex-session has 2 valid events; o3-session has 2 valid events
    assert result.sessions_found == 2
    assert result.events_parsed == 4
    assert result.records_inserted == 4

    # o3 records should have reasoning tokens
    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute(
            "SELECT SUM(reasoning_tokens) FROM requests WHERE model='o3' AND source='scan_codex'"
        )
        (total_reasoning,) = await cursor.fetchone()
    assert (total_reasoning or 0) > 0


@pytest.mark.asyncio
async def test_scan_codex_source_label(initialized_db: str, tmp_path: Path):
    sessions_dir = tmp_path / "codex_sessions"
    path = sessions_dir / "2026" / "01" / "09" / "rollout-src.jsonl"
    _write_session(path, [_session_meta(), _turn_context("gpt-4o"), _token_count_event()])

    await scan_codex(initialized_db, sessions_dir=sessions_dir)

    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute(
            "SELECT source FROM requests WHERE source = 'scan_codex' LIMIT 1"
        )
        row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "scan_codex"
