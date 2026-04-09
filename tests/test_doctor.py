"""Tests for burnlens doctor health checks."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from burnlens.doctor import (
    CheckResult,
    check_anthropic,
    check_database,
    check_google,
    check_openai,
    check_proxy,
    check_recent_activity,
    check_token_extraction,
    run_all_checks,
)


# ---------------------------------------------------------------------------
# Proxy checks
# ---------------------------------------------------------------------------


def test_proxy_check_pass_when_running():
    """Proxy check passes when health endpoint returns 200."""
    mock_resp = httpx.Response(200, json={"status": "ok"})
    with patch("burnlens.doctor.httpx.get", return_value=mock_resp):
        result = check_proxy("127.0.0.1", 8420)
    assert result.status == "pass"
    assert "8420" in result.message


def test_proxy_check_fail_when_not_running():
    """Proxy check fails when connection is refused."""
    with patch("burnlens.doctor.httpx.get", side_effect=httpx.ConnectError("refused")):
        result = check_proxy("127.0.0.1", 8420)
    assert result.status == "fail"
    assert result.fix == "burnlens start"


# ---------------------------------------------------------------------------
# OpenAI checks
# ---------------------------------------------------------------------------


def test_openai_pass_when_url_correct():
    """OpenAI check passes when BASE_URL includes /v1."""
    env = {
        "OPENAI_API_KEY": "sk-test",
        "OPENAI_BASE_URL": "http://127.0.0.1:8420/proxy/openai/v1",
    }
    with patch.dict("os.environ", env, clear=False):
        result = check_openai()
    assert result.status == "pass"
    assert "/v1" in result.message


def test_openai_warn_when_url_missing_v1():
    """OpenAI check warns when BASE_URL is missing /v1 suffix."""
    env = {
        "OPENAI_API_KEY": "sk-test",
        "OPENAI_BASE_URL": "http://127.0.0.1:8420/proxy/openai",
    }
    with patch.dict("os.environ", env, clear=False):
        result = check_openai()
    assert result.status == "warn"
    assert "/v1" in result.message
    assert "/v1" in result.fix


def test_openai_warn_when_no_api_key():
    """OpenAI check warns when API key is not set."""
    env = {"OPENAI_API_KEY": "", "OPENAI_BASE_URL": ""}
    with patch.dict("os.environ", env, clear=False):
        result = check_openai()
    assert result.status == "warn"
    assert "OPENAI_API_KEY" in result.message


# ---------------------------------------------------------------------------
# Anthropic checks
# ---------------------------------------------------------------------------


def test_anthropic_pass_when_env_set():
    """Anthropic check passes when both env vars are correctly set."""
    env = {
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "ANTHROPIC_BASE_URL": "http://127.0.0.1:8420/proxy/anthropic",
    }
    with patch.dict("os.environ", env, clear=False):
        result = check_anthropic()
    assert result.status == "pass"


def test_anthropic_warn_when_base_url_not_set():
    """Anthropic check warns when BASE_URL is missing."""
    env = {"ANTHROPIC_API_KEY": "sk-ant-test", "ANTHROPIC_BASE_URL": ""}
    with patch.dict("os.environ", env, clear=False):
        result = check_anthropic()
    assert result.status == "warn"
    assert "not set" in result.message


# ---------------------------------------------------------------------------
# Database checks
# ---------------------------------------------------------------------------


def test_database_pass_when_exists(tmp_path: Path):
    """Database check passes with a valid SQLite database."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE requests (id INTEGER PRIMARY KEY, cost_usd REAL, status_code INTEGER, timestamp TEXT)"
    )
    conn.execute(
        "INSERT INTO requests (cost_usd, status_code, timestamp) VALUES (0.01, 200, '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()

    result = check_database(db_path)
    assert result.status == "pass"
    assert "1" in result.message


def test_database_fail_when_missing(tmp_path: Path):
    """Database check fails when the file doesn't exist."""
    result = check_database(str(tmp_path / "nonexistent.db"))
    assert result.status == "fail"
    assert "not found" in result.message


# ---------------------------------------------------------------------------
# Token extraction check
# ---------------------------------------------------------------------------


def test_token_extraction_warn_when_zero_cost_requests_exist(tmp_path: Path):
    """Token extraction check warns when successful requests have zero cost."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE requests (id INTEGER PRIMARY KEY, cost_usd REAL, status_code INTEGER, timestamp TEXT)"
    )
    conn.execute("INSERT INTO requests (cost_usd, status_code, timestamp) VALUES (0, 200, '2026-01-01')")
    conn.execute("INSERT INTO requests (cost_usd, status_code, timestamp) VALUES (0.01, 200, '2026-01-01')")
    conn.commit()
    conn.close()

    result = check_token_extraction(db_path)
    assert result.status == "warn"
    assert "1" in result.message
    assert "$0.00" in result.message


def test_token_extraction_pass_when_all_have_cost(tmp_path: Path):
    """Token extraction passes when all successful requests have cost."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE requests (id INTEGER PRIMARY KEY, cost_usd REAL, status_code INTEGER, timestamp TEXT)"
    )
    conn.execute("INSERT INTO requests (cost_usd, status_code, timestamp) VALUES (0.01, 200, '2026-01-01')")
    conn.commit()
    conn.close()

    result = check_token_extraction(db_path)
    assert result.status == "pass"


# ---------------------------------------------------------------------------
# run_all_checks never crashes
# ---------------------------------------------------------------------------


def test_run_all_checks_never_crashes_on_exception():
    """run_all_checks must return results even if individual checks raise."""
    with patch("burnlens.doctor.check_proxy", side_effect=RuntimeError("boom")):
        with patch("burnlens.doctor.check_database", side_effect=RuntimeError("boom")):
            results = run_all_checks()
    # Should still return 7 results, not crash
    assert len(results) == 7
    # The crashed checks should be "fail", not missing
    assert results[0].status == "fail"
    assert results[1].status == "fail"
    # Checks 6 and 7 should be "skip" since proxy/db failed
    assert results[5].status == "skip"
    assert results[6].status == "skip"
