"""Tests for the Claude Code session disk reader (SCAN-1)."""
from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from burnlens.scan import claude_code as cc
from burnlens.scan.claude_code import (
    ClaudeSession,
    decode_project_path,
    discover_sessions,
    parse_session,
    resolve_dev_identity,
    scan_claude_code,
)
from burnlens.storage.database import init_db

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "claude_sessions"


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_projects_dir(tmp_path: Path) -> Path:
    """Build a temporary ~/.claude/projects/ tree with two projects."""
    root = tmp_path / "projects"
    proj_a = root / "-tmp-fake-burnlens"
    proj_b = root / "-tmp-fake-other"
    proj_a.mkdir(parents=True)
    proj_b.mkdir(parents=True)

    shutil.copy(FIXTURES_DIR / "normal_session.jsonl", proj_a / "session-aaa.jsonl")
    shutil.copy(FIXTURES_DIR / "edge_cases.jsonl", proj_a / "session-bbb.jsonl")
    shutil.copy(FIXTURES_DIR / "empty.jsonl", proj_b / "session-ccc.jsonl")
    return root


@pytest.fixture(autouse=True)
def _isolate_dev_cache():
    """Ensure each test starts with a clean dev-identity cache."""
    cc._reset_dev_identity_cache()
    yield
    cc._reset_dev_identity_cache()


@pytest_asyncio.fixture
async def initialized_db(tmp_path: Path) -> str:
    db = str(tmp_path / "scan.db")
    await init_db(db)
    return db


# ---------------------------------------------------------------------------
# decode_project_path
# ---------------------------------------------------------------------------


def test_decode_project_path_reverses_sanitization():
    assert (
        decode_project_path("-Users-bhushan-Documents-Projects-burnlens")
        == "/Users/bhushan/Documents/Projects/burnlens"
    )


def test_decode_project_path_handles_dashes_in_real_dirnames():
    # A leading dash means absolute path; remaining dashes become slashes.
    # This is lossy but matches Claude Code's own (lossy) encoding.
    assert decode_project_path("-tmp-fake-burnlens") == "/tmp/fake/burnlens"
    # No leading dash → treat as relative-ish.
    assert decode_project_path("foo-bar") == "foo/bar"
    assert decode_project_path("") == ""


# ---------------------------------------------------------------------------
# parse_session
# ---------------------------------------------------------------------------


def _session_for(file: Path, basename: str = "burnlens") -> ClaudeSession:
    return ClaudeSession(
        session_id=file.stem,
        project_path=f"/tmp/fake/{basename}",
        project_basename=basename,
        file_path=file,
        modified_at=datetime.now(timezone.utc),
    )


def test_parse_session_extracts_assistant_messages_only():
    session = _session_for(FIXTURES_DIR / "normal_session.jsonl")
    records = list(parse_session(session))
    assert len(records) == 3
    assert {r.request_id for r in records} == {"msg_test_001", "msg_test_002", "msg_test_003"}
    assert all(r.source == "scan_claude" for r in records)
    assert all(r.provider == "anthropic" for r in records)


def test_parse_session_skips_user_and_tool_messages():
    session = _session_for(FIXTURES_DIR / "normal_session.jsonl")
    records = list(parse_session(session))
    # No record corresponds to a user or tool_result line.
    for r in records:
        assert r.request_id.startswith("msg_test_")


def test_parse_session_extracts_cache_tokens():
    session = _session_for(FIXTURES_DIR / "normal_session.jsonl")
    records = {r.request_id: r for r in parse_session(session)}
    msg2 = records["msg_test_002"]
    assert msg2.cache_read_tokens == 1000
    assert msg2.cache_write_tokens == 500
    assert msg2.input_tokens == 2
    assert msg2.output_tokens == 120


def test_parse_session_handles_malformed_jsonl_line():
    # edge_cases.jsonl includes a garbage line; it must be skipped, not crash.
    session = _session_for(FIXTURES_DIR / "edge_cases.jsonl")
    records = list(parse_session(session))
    # Only the well-formed assistant record with both model + usage survives.
    assert len(records) == 1
    assert records[0].request_id == "msg_ok"


def test_parse_session_handles_empty_file():
    session = _session_for(FIXTURES_DIR / "empty.jsonl")
    assert list(parse_session(session)) == []


def test_parse_session_skips_assistant_messages_without_usage():
    session = _session_for(FIXTURES_DIR / "edge_cases.jsonl")
    ids = {r.request_id for r in parse_session(session)}
    assert "msg_no_usage" not in ids
    assert "msg_no_model" not in ids


def test_parse_session_skips_synthetic_model():
    session = _session_for(FIXTURES_DIR / "edge_cases.jsonl")
    ids = {r.request_id for r in parse_session(session)}
    assert "msg_synth" not in ids


def test_parse_session_calculates_cost():
    session = _session_for(FIXTURES_DIR / "normal_session.jsonl")
    records = {r.request_id: r for r in parse_session(session)}
    # Sonnet 4.6: input $3/M, output $15/M, cache_read $0.30/M, cache_write $3.75/M
    # msg_test_001: input=3, cache_write=1000, cache_read=0, output=50
    # billable_input = max(0, 3-0)=3; cost = 3*3/1e6 + 50*15/1e6 + 1000*3.75/1e6
    expected = 3 * 3 / 1_000_000 + 50 * 15 / 1_000_000 + 1000 * 3.75 / 1_000_000
    assert records["msg_test_001"].cost_usd == pytest.approx(expected)


# ---------------------------------------------------------------------------
# discover_sessions
# ---------------------------------------------------------------------------


def test_discover_sessions_finds_all_jsonl(fake_projects_dir: Path):
    sessions = discover_sessions(projects_dir=fake_projects_dir)
    assert len(sessions) == 3
    assert {s.project_basename for s in sessions} == {"burnlens", "other"}


def test_scan_filters_by_project_substring(fake_projects_dir: Path):
    sessions = discover_sessions(
        project_filter="burnlens", projects_dir=fake_projects_dir
    )
    assert {s.project_basename for s in sessions} == {"burnlens"}


def test_scan_filters_by_since_date(fake_projects_dir: Path):
    # Backdate one file to be older than the cutoff; the other stays current.
    proj_a = fake_projects_dir / "-tmp-fake-burnlens"
    old_file = proj_a / "session-aaa.jsonl"
    fresh_file = proj_a / "session-bbb.jsonl"

    old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
    os.utime(old_file, (old_ts, old_ts))

    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    sessions = discover_sessions(since=cutoff, projects_dir=fake_projects_dir)
    file_paths = {s.file_path for s in sessions}
    assert fresh_file in file_paths
    assert old_file not in file_paths


def test_empty_claude_dir_no_crash(tmp_path: Path):
    missing = tmp_path / "does-not-exist"
    assert discover_sessions(projects_dir=missing) == []
    empty = tmp_path / "empty-projects"
    empty.mkdir()
    assert discover_sessions(projects_dir=empty) == []


# ---------------------------------------------------------------------------
# resolve_dev_identity
# ---------------------------------------------------------------------------


def test_resolve_dev_identity_falls_back_to_user_env(monkeypatch, tmp_path: Path):
    cc._reset_dev_identity_cache()
    fake_path = str(tmp_path / "no-such-project")
    monkeypatch.setenv("USER", "test-runner")
    assert resolve_dev_identity(fake_path) == "test-runner"


def test_resolve_dev_identity_caches_per_run(monkeypatch, tmp_path: Path):
    cc._reset_dev_identity_cache()
    fake_path = str(tmp_path / "another-no-such-project")
    monkeypatch.setenv("USER", "first")
    first = resolve_dev_identity(fake_path)
    monkeypatch.setenv("USER", "second")
    # Cached value wins until reset.
    assert resolve_dev_identity(fake_path) == first


# ---------------------------------------------------------------------------
# scan_claude_code (end-to-end with real DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_unique_index_prevents_duplicates(
    initialized_db: str, fake_projects_dir: Path
):
    first = await scan_claude_code(initialized_db, projects_dir=fake_projects_dir)
    second = await scan_claude_code(initialized_db, projects_dir=fake_projects_dir)

    assert first.records_inserted > 0
    assert first.records_skipped == 0
    assert second.records_inserted == 0
    assert second.records_skipped == first.records_inserted

    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM requests WHERE source = 'scan_claude'"
        )
        (count,) = await cursor.fetchone()
    assert count == first.records_inserted


@pytest.mark.asyncio
async def test_dry_run_does_not_insert(
    initialized_db: str, fake_projects_dir: Path
):
    result = await scan_claude_code(
        initialized_db, projects_dir=fake_projects_dir, dry_run=True
    )
    assert result.messages_parsed > 0
    assert result.records_inserted == 0
    assert result.records_skipped == 0

    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM requests")
        (count,) = await cursor.fetchone()
    assert count == 0


@pytest.mark.asyncio
async def test_scan_populates_tag_repo_and_source(
    initialized_db: str, fake_projects_dir: Path
):
    await scan_claude_code(initialized_db, projects_dir=fake_projects_dir)
    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute(
            "SELECT source, tag_repo, request_id FROM requests "
            "WHERE source = 'scan_claude' ORDER BY request_id"
        )
        rows = await cursor.fetchall()
    assert rows
    assert all(r[0] == "scan_claude" for r in rows)
    assert all(r[1] in {"burnlens", "other"} for r in rows)
    assert all(r[2] is not None for r in rows)
