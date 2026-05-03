"""Tests for the Gemini CLI session disk reader (SCAN-4)."""
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
from burnlens.scan.gemini_cli import (
    GeminiScanResult,
    GeminiSession,
    discover_sessions,
    gemini_sessions_dir,
    parse_session,
    scan_gemini_cli,
)
from burnlens.storage.database import init_db

# ---------------------------------------------------------------------------
# Fixtures directory (mirrors the ~/.gemini structure)
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "gemini_sessions"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gemini_dir(tmp_path: Path) -> Path:
    """Create a minimal ~/.gemini-like directory tree under tmp_path."""
    gemini_dir = tmp_path / "gemini_home"
    gemini_dir.mkdir()
    return gemini_dir


def _make_project(gemini_dir: Path, slug: str, cwd: str) -> Path:
    """Create a project directory with .project_root and chats/."""
    project_dir = gemini_dir / "tmp" / slug
    project_dir.mkdir(parents=True)
    (project_dir / ".project_root").write_text(cwd, encoding="utf-8")
    (project_dir / "chats").mkdir()
    return project_dir / "chats"


def _write_json_session(chats_dir: Path, name: str, messages: list[dict]) -> Path:
    """Write a JSON-format session file."""
    session = {
        "sessionId": f"test-session-{name}",
        "projectHash": "aabbcc" * 10,
        "startTime": "2026-01-09T10:00:00.000Z",
        "lastUpdated": "2026-01-09T10:05:00.000Z",
        "kind": "main",
        "messages": messages,
    }
    path = chats_dir / f"session-2026-01-09T10-00-{name}.json"
    path.write_text(json.dumps(session), encoding="utf-8")
    return path


def _write_jsonl_session(chats_dir: Path, name: str, lines: list[dict | str]) -> Path:
    """Write a JSONL-format session file."""
    path = chats_dir / f"session-2026-01-10T08-00-{name}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for line in lines:
            fh.write((line if isinstance(line, str) else json.dumps(line)) + "\n")
    return path


def _gemini_msg(
    *,
    msg_id: str = "gemini-abc",
    model: str = "gemini-2.5-flash",
    input_tokens: int = 1000,
    output_tokens: int = 100,
    cached: int = 0,
    thoughts: int = 0,
    tool: int = 0,
    timestamp: str = "2026-01-09T10:00:20.000Z",
) -> dict:
    return {
        "id": msg_id,
        "timestamp": timestamp,
        "type": "gemini",
        "content": "Response text.",
        "thoughts": [],
        "model": model,
        "tokens": {
            "input": input_tokens,
            "output": output_tokens,
            "cached": cached,
            "thoughts": thoughts,
            "tool": tool,
            "total": input_tokens + output_tokens + thoughts,
        },
    }


def _user_msg(text: str = "Hello") -> dict:
    return {
        "id": "user-msg-001",
        "timestamp": "2026-01-09T10:00:10.000Z",
        "type": "user",
        "content": [{"text": text}],
    }


# ---------------------------------------------------------------------------
# gemini_sessions_dir tests
# ---------------------------------------------------------------------------


def test_gemini_sessions_dir_returns_none_when_not_installed(tmp_path, monkeypatch):
    """Returns None when no Gemini CLI installation is found."""
    monkeypatch.delenv("GEMINI_HOME", raising=False)
    # Patch probe paths to non-existent temp dirs
    import burnlens.scan.gemini_cli as mod
    original = mod.GEMINI_PROBE_PATHS
    mod.GEMINI_PROBE_PATHS = [tmp_path / "no_gemini", tmp_path / "also_no_gemini"]
    try:
        assert gemini_sessions_dir() is None
    finally:
        mod.GEMINI_PROBE_PATHS = original


def test_gemini_sessions_dir_honors_gemini_home_env(tmp_path, monkeypatch):
    """$GEMINI_HOME overrides probe paths when it exists."""
    custom = tmp_path / "custom_gemini"
    custom.mkdir()
    monkeypatch.setenv("GEMINI_HOME", str(custom))
    assert gemini_sessions_dir() == custom


def test_gemini_sessions_dir_honors_gemini_home_env_missing(tmp_path, monkeypatch):
    """$GEMINI_HOME that doesn't exist is ignored; falls through to probes."""
    monkeypatch.setenv("GEMINI_HOME", str(tmp_path / "nonexistent"))
    import burnlens.scan.gemini_cli as mod
    original = mod.GEMINI_PROBE_PATHS
    actual = tmp_path / "dot_gemini"
    actual.mkdir()
    mod.GEMINI_PROBE_PATHS = [actual]
    try:
        assert gemini_sessions_dir() == actual
    finally:
        mod.GEMINI_PROBE_PATHS = original


def test_gemini_sessions_dir_finds_dot_gemini_first(tmp_path, monkeypatch):
    """First matching probe path is returned."""
    monkeypatch.delenv("GEMINI_HOME", raising=False)
    import burnlens.scan.gemini_cli as mod
    original = mod.GEMINI_PROBE_PATHS
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    mod.GEMINI_PROBE_PATHS = [first, second]
    try:
        result = gemini_sessions_dir()
        assert result == first
    finally:
        mod.GEMINI_PROBE_PATHS = original


# ---------------------------------------------------------------------------
# discover_sessions tests
# ---------------------------------------------------------------------------


def test_discover_sessions_returns_empty_when_dir_missing(tmp_path):
    """Returns empty list when gemini_dir doesn't exist."""
    assert discover_sessions(gemini_dir=tmp_path / "nonexistent") == []


def test_discover_sessions_returns_empty_when_no_tmp_dir(tmp_path):
    """Returns empty list when ~/.gemini exists but has no tmp/ subdir."""
    assert discover_sessions(gemini_dir=tmp_path) == []


def test_discover_sessions_finds_both_json_and_jsonl(tmp_path):
    """Discovers both .json and .jsonl session files."""
    chats = _make_project(tmp_path, "myproject", "/some/path")
    _write_json_session(chats, "s001", [_user_msg()])
    _write_jsonl_session(chats, "s002", [
        {"sessionId": "id", "kind": "main"},
        _gemini_msg(),
    ])
    sessions = discover_sessions(gemini_dir=tmp_path)
    assert len(sessions) == 2


def test_discover_sessions_applies_since_filter(tmp_path):
    """Skips session files older than `since`."""
    chats = _make_project(tmp_path, "myproject", "/some/path")
    sf = _write_json_session(chats, "old", [_user_msg()])
    # Back-date the file
    past = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
    os.utime(sf, (past, past))
    since = datetime(2025, 1, 1, tzinfo=timezone.utc)
    sessions = discover_sessions(since=since, gemini_dir=tmp_path)
    assert sessions == []


def test_discover_sessions_sets_cwd_from_project_root(tmp_path):
    """GeminiSession.cwd comes from the .project_root file."""
    chats = _make_project(tmp_path, "myproject", "/users/alice/repos/myapp")
    _write_json_session(chats, "s001", [_user_msg()])
    sessions = discover_sessions(gemini_dir=tmp_path)
    assert len(sessions) == 1
    assert sessions[0].cwd == "/users/alice/repos/myapp"


def test_discover_sessions_sets_project_slug(tmp_path):
    """GeminiSession.project_slug matches the directory name."""
    chats = _make_project(tmp_path, "burnlens-app", "/some/path")
    _write_json_session(chats, "s001", [_user_msg()])
    sessions = discover_sessions(gemini_dir=tmp_path)
    assert sessions[0].project_slug == "burnlens-app"


# ---------------------------------------------------------------------------
# parse_session — JSON format tests
# ---------------------------------------------------------------------------


def test_parse_session_extracts_turns_with_usage_metadata(tmp_path):
    """JSON-format session yields a record per gemini message with tokens."""
    _reset_dev_identity_cache()
    chats = _make_project(tmp_path, "proj", "/tmp/proj")
    sf = _write_json_session(chats, "s001", [
        _user_msg(),
        _gemini_msg(msg_id="gm-1", input_tokens=1000, output_tokens=100),
        _gemini_msg(msg_id="gm-2", input_tokens=2000, output_tokens=200),
    ])
    session = discover_sessions(gemini_dir=tmp_path)[0]
    records = list(parse_session(session))
    assert len(records) == 2
    assert records[0].input_tokens == 1000
    assert records[0].output_tokens == 100
    assert records[1].input_tokens == 2000


def test_parse_session_skips_turns_without_usage_metadata(tmp_path):
    """Gemini messages without a tokens block are skipped."""
    _reset_dev_identity_cache()
    chats = _make_project(tmp_path, "proj", "/tmp/proj")
    no_tokens_msg = {
        "id": "gm-no-tok",
        "timestamp": "2026-01-09T10:01:00.000Z",
        "type": "gemini",
        "content": "I have no tokens.",
        "model": "gemini-2.5-flash",
    }
    sf = _write_json_session(chats, "s001", [_user_msg(), no_tokens_msg])
    session = discover_sessions(gemini_dir=tmp_path)[0]
    records = list(parse_session(session))
    assert records == []


def test_parse_session_extracts_cached_content_tokens(tmp_path):
    """cache_read_tokens maps from tokens.cached."""
    _reset_dev_identity_cache()
    chats = _make_project(tmp_path, "proj", "/tmp/proj")
    _write_json_session(chats, "s001", [
        _gemini_msg(msg_id="gm-1", input_tokens=2000, output_tokens=100, cached=500),
    ])
    session = discover_sessions(gemini_dir=tmp_path)[0]
    records = list(parse_session(session))
    assert records[0].cache_read_tokens == 500
    assert records[0].cache_write_tokens == 0


def test_parse_session_extracts_thoughts_tokens_for_25_models(tmp_path):
    """reasoning_tokens maps from tokens.thoughts (Gemini 2.5 thinking)."""
    _reset_dev_identity_cache()
    chats = _make_project(tmp_path, "proj", "/tmp/proj")
    _write_json_session(chats, "s001", [
        _gemini_msg(
            msg_id="gm-1",
            model="gemini-2.5-pro",
            input_tokens=5000,
            output_tokens=200,
            thoughts=300,
        ),
    ])
    session = discover_sessions(gemini_dir=tmp_path)[0]
    records = list(parse_session(session))
    assert records[0].reasoning_tokens == 300


def test_parse_session_request_id_is_session_plus_message_id(tmp_path):
    """request_id is '<session_stem>:<message_id>' for dedup."""
    _reset_dev_identity_cache()
    chats = _make_project(tmp_path, "proj", "/tmp/proj")
    sf = _write_json_session(chats, "myses", [
        _gemini_msg(msg_id="unique-msg-id-123"),
    ])
    session = discover_sessions(gemini_dir=tmp_path)[0]
    records = list(parse_session(session))
    assert "unique-msg-id-123" in records[0].request_id
    assert session.session_id in records[0].request_id


def test_parse_session_handles_malformed_json_file(tmp_path):
    """Malformed JSON file produces no records (logged at DEBUG, no crash)."""
    _reset_dev_identity_cache()
    chats = _make_project(tmp_path, "proj", "/tmp/proj")
    bad = chats / "session-2026-01-09T10-00-bad001.json"
    bad.write_text("this is not json {{{{", encoding="utf-8")
    # Manually construct a GeminiSession since discover_sessions uses mtime filter
    session = GeminiSession(
        session_id="session-2026-01-09T10-00-bad001",
        project_slug="proj",
        file_path=bad,
        modified_at=datetime.now(timezone.utc),
        cwd="/tmp/proj",
    )
    records = list(parse_session(session))
    assert records == []


# ---------------------------------------------------------------------------
# parse_session — JSONL format tests
# ---------------------------------------------------------------------------


def test_parse_session_jsonl_extracts_turns(tmp_path):
    """JSONL-format session yields records for gemini messages with tokens."""
    _reset_dev_identity_cache()
    chats = _make_project(tmp_path, "proj", "/tmp/proj")
    _write_jsonl_session(chats, "s001", [
        {"sessionId": "sid-001", "kind": "main", "startTime": "2026-01-10T08:00:00.000Z"},
        _user_msg(),
        {"$set": {"lastUpdated": "2026-01-10T08:00:10.001Z"}},
        _gemini_msg(msg_id="gm-j1", input_tokens=3000, output_tokens=150),
        {"$set": {"lastUpdated": "2026-01-10T08:01:00.001Z"}},
        _gemini_msg(msg_id="gm-j2", input_tokens=3500, output_tokens=180),
    ])
    session = discover_sessions(gemini_dir=tmp_path)[0]
    records = list(parse_session(session))
    assert len(records) == 2
    assert records[0].input_tokens == 3000
    assert records[1].input_tokens == 3500


def test_parse_session_jsonl_skips_set_events(tmp_path):
    """$set mutation events are skipped silently."""
    _reset_dev_identity_cache()
    chats = _make_project(tmp_path, "proj", "/tmp/proj")
    _write_jsonl_session(chats, "s001", [
        {"$set": {"lastUpdated": "2026-01-10T08:00:00.001Z"}},
        _gemini_msg(msg_id="gm-j1"),
    ])
    session = discover_sessions(gemini_dir=tmp_path)[0]
    records = list(parse_session(session))
    assert len(records) == 1


def test_parse_session_jsonl_handles_malformed_line(tmp_path):
    """Malformed JSONL lines are skipped without crashing."""
    _reset_dev_identity_cache()
    chats = _make_project(tmp_path, "proj", "/tmp/proj")
    _write_jsonl_session(chats, "s001", [
        _gemini_msg(msg_id="gm-j1"),
        "this is not json {{{{",
        _gemini_msg(msg_id="gm-j2", input_tokens=2000, output_tokens=100),
    ])
    session = discover_sessions(gemini_dir=tmp_path)[0]
    records = list(parse_session(session))
    assert len(records) == 2


def test_parse_session_jsonl_extracts_thoughts_tokens(tmp_path):
    """reasoning_tokens extracted from tokens.thoughts in JSONL format."""
    _reset_dev_identity_cache()
    chats = _make_project(tmp_path, "proj", "/tmp/proj")
    _write_jsonl_session(chats, "s001", [
        _gemini_msg(
            msg_id="gm-j1",
            model="gemini-2.5-pro",
            input_tokens=5000,
            output_tokens=200,
            thoughts=400,
        ),
    ])
    session = discover_sessions(gemini_dir=tmp_path)[0]
    records = list(parse_session(session))
    assert records[0].reasoning_tokens == 400


def test_parse_session_jsonl_extracts_cached_tokens(tmp_path):
    """cache_read_tokens extracted from tokens.cached in JSONL format."""
    _reset_dev_identity_cache()
    chats = _make_project(tmp_path, "proj", "/tmp/proj")
    _write_jsonl_session(chats, "s001", [
        _gemini_msg(msg_id="gm-j1", input_tokens=2000, output_tokens=100, cached=800),
    ])
    session = discover_sessions(gemini_dir=tmp_path)[0]
    records = list(parse_session(session))
    assert records[0].cache_read_tokens == 800


# ---------------------------------------------------------------------------
# Cost calculation tests
# ---------------------------------------------------------------------------


def test_gemini_uses_google_pricing(tmp_path):
    """parse_session routes to provider='google' and calculates cost."""
    _reset_dev_identity_cache()
    chats = _make_project(tmp_path, "proj", "/tmp/proj")
    _write_json_session(chats, "s001", [
        _gemini_msg(
            msg_id="gm-1",
            model="gemini-2.5-flash",
            input_tokens=1_000_000,
            output_tokens=0,
        ),
    ])
    session = discover_sessions(gemini_dir=tmp_path)[0]
    records = list(parse_session(session))
    assert len(records) == 1
    expected = calculate_cost(
        "google",
        "gemini-2.5-flash",
        TokenUsage(input_tokens=1_000_000),
    )
    assert abs(records[0].cost_usd - expected) < 1e-9
    assert records[0].provider == "google"
    assert records[0].source == "scan_gemini"


def test_gemini_thoughts_tokens_billed_at_output_rate(tmp_path):
    """thoughts tokens are passed as reasoning_tokens → billed at output rate."""
    _reset_dev_identity_cache()
    chats = _make_project(tmp_path, "proj", "/tmp/proj")
    # Record with thoughts but zero regular output
    _write_json_session(chats, "s001", [
        _gemini_msg(
            msg_id="gm-1",
            model="gemini-2.5-pro",
            input_tokens=1000,
            output_tokens=0,
            thoughts=1_000_000,
        ),
    ])
    session = discover_sessions(gemini_dir=tmp_path)[0]
    records = list(parse_session(session))
    expected = calculate_cost(
        "google",
        "gemini-2.5-pro",
        TokenUsage(input_tokens=1000, reasoning_tokens=1_000_000),
    )
    assert abs(records[0].cost_usd - expected) < 1e-9


# ---------------------------------------------------------------------------
# Fixture-based integration tests
# ---------------------------------------------------------------------------


def test_static_fixtures_exist():
    """The pre-written fixture files exist and can be loaded."""
    flash_dir = FIXTURES_DIR / "tmp" / "flash_project" / "chats"
    pro_dir = FIXTURES_DIR / "tmp" / "pro_project" / "chats"
    assert any(flash_dir.glob("session-*.json"))
    assert any(pro_dir.glob("session-*.jsonl"))


def test_fixtures_flash_session_parsed():
    """Flash fixture (JSON format) parses correctly."""
    _reset_dev_identity_cache()
    sessions = discover_sessions(gemini_dir=FIXTURES_DIR)
    flash_sessions = [s for s in sessions if s.project_slug == "flash_project"]
    assert len(flash_sessions) == 1
    records = list(parse_session(flash_sessions[0]))
    assert len(records) == 2
    assert all(r.model == "gemini-2.5-flash" for r in records)


def test_fixtures_pro_session_parsed():
    """Pro fixture (JSONL format) parses thoughts tokens and skips no-token message."""
    _reset_dev_identity_cache()
    sessions = discover_sessions(gemini_dir=FIXTURES_DIR)
    pro_sessions = [s for s in sessions if s.project_slug == "pro_project"]
    assert len(pro_sessions) == 1
    records = list(parse_session(pro_sessions[0]))
    # 3 gemini messages in JSONL, but 1 has no tokens → 2 records
    assert len(records) == 2
    assert all(r.model == "gemini-2.5-pro" for r in records)
    assert records[0].reasoning_tokens == 300
    assert records[1].cache_read_tokens == 2000


# ---------------------------------------------------------------------------
# scan_gemini_cli (async integration)
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_gemini.db")


@pytest_asyncio.fixture
async def init_test_db(db_path):
    await init_db(db_path)
    return db_path


@pytest.mark.asyncio
async def test_dry_run_does_not_insert(init_test_db):
    """dry_run=True parses records but does not insert them."""
    _reset_dev_identity_cache()
    result = await scan_gemini_cli(
        init_test_db,
        dry_run=True,
        gemini_dir=FIXTURES_DIR,
    )
    assert result.turns_parsed > 0
    assert result.records_inserted == 0
    async with aiosqlite.connect(init_test_db) as db:
        async with db.execute("SELECT count(*) FROM requests") as cur:
            (count,) = await cur.fetchone()
    assert count == 0


@pytest.mark.asyncio
async def test_dedup_prevents_duplicate_turns_on_rescan(init_test_db):
    """Running scan twice inserts records only on the first run."""
    _reset_dev_identity_cache()
    result1 = await scan_gemini_cli(init_test_db, gemini_dir=FIXTURES_DIR)
    _reset_dev_identity_cache()
    result2 = await scan_gemini_cli(init_test_db, gemini_dir=FIXTURES_DIR)

    assert result1.records_inserted > 0
    assert result2.records_inserted == 0
    assert result2.records_skipped == result1.records_inserted


@pytest.mark.asyncio
async def test_scan_sets_source_to_scan_gemini(init_test_db):
    """All imported records have source='scan_gemini'."""
    _reset_dev_identity_cache()
    await scan_gemini_cli(init_test_db, gemini_dir=FIXTURES_DIR)
    async with aiosqlite.connect(init_test_db) as db:
        async with db.execute(
            "SELECT DISTINCT source FROM requests"
        ) as cur:
            sources = {row[0] async for row in cur}
    assert sources == {"scan_gemini"}


@pytest.mark.asyncio
async def test_scan_returns_correct_counts(init_test_db):
    """ScanResult.turns_parsed matches the number of valid gemini messages."""
    _reset_dev_identity_cache()
    result = await scan_gemini_cli(init_test_db, gemini_dir=FIXTURES_DIR)
    # flash_project: 2 messages, pro_project: 2 messages (1 no-token skipped)
    assert result.turns_parsed == 4
    assert result.sessions_found == 2


@pytest.mark.asyncio
async def test_scan_no_sessions_returns_empty_result(tmp_path):
    """scan_gemini_cli returns an empty result when no sessions exist."""
    db = str(tmp_path / "empty.db")
    await init_db(db)
    _reset_dev_identity_cache()
    result = await scan_gemini_cli(db, gemini_dir=tmp_path / "nonexistent")
    assert result.sessions_found == 0
    assert result.turns_parsed == 0
    assert result.records_inserted == 0
