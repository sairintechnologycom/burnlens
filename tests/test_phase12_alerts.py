import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Test-safe env — mirror the fake dotenv shim from test_phase11_auth.py exactly
# ---------------------------------------------------------------------------
import os
import pathlib

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/burnlens_test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("PADDLE_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("PADDLE_CLOUD_PRICE_ID", "pri_env_cloud")
os.environ.setdefault("PADDLE_TEAMS_PRICE_ID", "pri_env_teams")

_FAKE_ENV = pathlib.Path(__file__).parent / "_phase7_billing_test.env"
if not _FAKE_ENV.exists():
    _FAKE_ENV.write_text("")
os.environ["BURNLENS_CLOUD_ENV_FILE_OVERRIDE"] = str(_FAKE_ENV)

import pydantic_settings.sources as _ps_sources  # noqa: E402


def _empty_dotenv_values(*args, **kwargs):
    return {}


_ps_sources.dotenv_values = _empty_dotenv_values

# ---------------------------------------------------------------------------
# Now import the modules under test
# ---------------------------------------------------------------------------

from burnlens_cloud.alert_engine import (
    _should_fire, _dispatch_slack, _dispatch_email,
    evaluate_workspace, evaluate_all_workspaces,
)
from burnlens_cloud import config as config_mod


# --- _should_fire ---

@pytest.mark.asyncio
async def test_should_fire_true():
    conn = AsyncMock()
    conn.fetchrow.return_value = None
    now = datetime.now(tz=timezone.utc)
    result = await _should_fire(conn, "rule-uuid", now)
    assert result is True
    conn.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_should_fire_false():
    conn = AsyncMock()
    conn.fetchrow.return_value = {"1": 1}
    now = datetime.now(tz=timezone.utc)
    result = await _should_fire(conn, "rule-uuid", now)
    assert result is False


# --- _dispatch_slack ---

@pytest.mark.asyncio
async def test_dispatch_slack_ssrf_guard_invalid_host():
    with patch("burnlens_cloud.alert_engine.httpx.AsyncClient") as mock_client:
        result = await _dispatch_slack(
            webhook_url="https://evil.com/hook",
            workspace_id="ws-1",
            threshold_pct=80,
            current=800,
            limit=1000,
        )
    assert result is False
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_slack_ssrf_guard_empty():
    with patch("burnlens_cloud.alert_engine.httpx.AsyncClient") as mock_client:
        result = await _dispatch_slack(
            webhook_url="",
            workspace_id="ws-1",
            threshold_pct=80,
            current=800,
            limit=1000,
        )
    assert result is False
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_slack_success():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(return_value=None)

    mock_post = AsyncMock(return_value=mock_response)
    mock_http = AsyncMock()
    mock_http.post = mock_post

    with patch("burnlens_cloud.alert_engine.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _dispatch_slack(
            webhook_url="https://hooks.slack.com/services/T000/B000/xxx",
            workspace_id="ws-1",
            threshold_pct=80,
            current=800,
            limit=1000,
        )

    assert result is True
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    payload = call_kwargs[1].get("json") or call_kwargs[0][1]
    assert "80%" in payload["text"]


@pytest.mark.asyncio
async def test_dispatch_slack_http_error():
    import httpx as _httpx

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(side_effect=_httpx.HTTPStatusError(
        "500", request=MagicMock(), response=MagicMock()
    ))

    with patch("burnlens_cloud.alert_engine.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _dispatch_slack(
            webhook_url="https://hooks.slack.com/services/T000/B000/xxx",
            workspace_id="ws-1",
            threshold_pct=80,
            current=800,
            limit=1000,
        )

    assert result is False


# --- evaluate_workspace ---

@pytest.mark.asyncio
async def test_evaluate_workspace_fires_on_threshold():
    conn = AsyncMock()
    conn.fetch.return_value = [
        {
            "id": "rule-uuid-1",
            "threshold_pct": 80,
            "channel": "email",
            "slack_webhook_url": None,
            "extra_emails": [],
        }
    ]
    conn.fetchrow.return_value = None  # _should_fire → True
    conn.execute = AsyncMock()

    with patch("burnlens_cloud.alert_engine._dispatch_email", new=AsyncMock(return_value=True)):
        fired = await evaluate_workspace(
            conn=conn,
            workspace_id="ws-1",
            plan="cloud",
            current_count=850,
            monthly_cap=1000,
            cycle_end_date="2026-05-31",
        )

    assert len(fired) == 1
    assert fired[0]["threshold_pct"] == 80
    assert fired[0]["status"] == "sent"
    conn.execute.assert_called_once()


@pytest.mark.asyncio
async def test_evaluate_workspace_dedup_skips():
    conn = AsyncMock()
    conn.fetch.return_value = [
        {
            "id": "rule-uuid-1",
            "threshold_pct": 80,
            "channel": "email",
            "slack_webhook_url": None,
            "extra_emails": [],
        }
    ]
    conn.fetchrow.return_value = {"1": 1}  # _should_fire → False
    conn.execute = AsyncMock()

    with patch("burnlens_cloud.alert_engine._dispatch_email", new=AsyncMock(return_value=True)):
        fired = await evaluate_workspace(
            conn=conn,
            workspace_id="ws-1",
            plan="cloud",
            current_count=850,
            monthly_cap=1000,
            cycle_end_date="2026-05-31",
        )

    assert len(fired) == 0
    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_workspace_fail_open():
    conn = AsyncMock()
    conn.fetch.return_value = [
        {
            "id": "rule-uuid-err",
            "threshold_pct": 80,
            "channel": "email",
            "slack_webhook_url": None,
            "extra_emails": [],
        }
    ]
    conn.fetchrow.side_effect = Exception("DB connection lost")

    fired = await evaluate_workspace(
        conn=conn,
        workspace_id="ws-1",
        plan="cloud",
        current_count=850,
        monthly_cap=1000,
        cycle_end_date="2026-05-31",
    )

    assert fired == []


@pytest.mark.asyncio
async def test_evaluate_all_workspaces_skip_free():
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []  # SQL excludes free — no rows returned

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("burnlens_cloud.alert_engine.evaluate_workspace", new=AsyncMock(return_value=[])) as mock_eval:
        result = await evaluate_all_workspaces(mock_pool)

    assert result["evaluated"] == 0
    assert result["fired"] == 0
    mock_eval.assert_not_called()


# --- cron endpoint ---
# Build a minimal FastAPI app with just the cron router — no lifespan/init_db —
# mirroring the pattern in test_phase11_auth.py (_make_app(*routers)).

def _make_cron_app():
    """Return a minimal FastAPI app with only the cron router mounted."""
    from fastapi import FastAPI
    from burnlens_cloud.cron_api import router as cron_router
    app = FastAPI()
    mock_pool = MagicMock()
    app.state.db_pool = mock_pool
    app.include_router(cron_router)
    return app


def test_cron_endpoint_401_no_header():
    from fastapi.testclient import TestClient
    with patch.object(config_mod.settings, "cron_secret", "test-cron-secret"):
        app = _make_cron_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/cron/evaluate-alerts")
    assert resp.status_code == 401


def test_cron_endpoint_401_wrong_secret():
    from fastapi.testclient import TestClient
    with patch.object(config_mod.settings, "cron_secret", "test-cron-secret"):
        app = _make_cron_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/cron/evaluate-alerts",
                headers={"Authorization": "Bearer wrong-secret"},
            )
    assert resp.status_code == 401


def test_cron_endpoint_200_with_correct_secret():
    from fastapi.testclient import TestClient
    with patch.object(config_mod.settings, "cron_secret", "test-cron-secret"), \
         patch("burnlens_cloud.cron_api.get_pool", return_value=MagicMock()), \
         patch(
             "burnlens_cloud.cron_api.evaluate_all_workspaces",
             new=AsyncMock(return_value={"evaluated": 3, "fired": 1}),
         ):
        app = _make_cron_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/cron/evaluate-alerts",
                headers={"Authorization": "Bearer test-cron-secret"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert "evaluated" in data
    assert "fired" in data
    assert data["evaluated"] == 3
    assert data["fired"] == 1


# --- ALERT-01: seeding migration regression guard ---

def test_alert_rules_seeding_sql_present():
    """ALERT-01: Verify default-seeding migration is present in database.py (regression guard).

    The actual INSERT runs against a live Postgres DB at deploy time and cannot be
    unit-tested without a real DB. This static check ensures the migration is never
    accidentally removed during refactors.
    """
    import pathlib
    src = pathlib.Path("burnlens_cloud/database.py").read_text()
    assert "INSERT INTO alert_rules (workspace_id, threshold_pct, channel)" in src
    assert "CROSS JOIN (VALUES (80), (100)) AS t(threshold_pct)" in src
    assert "WHERE w.plan IN ('cloud', 'teams')" in src
    assert "AND NOT EXISTS" in src, "Idempotent NOT EXISTS guard must be present"
