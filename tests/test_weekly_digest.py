"""Weekly spend digest: query shape, WoW math, and send-loop behaviour.

CI has no Postgres, so the connection is a stand-in that dispatches on SQL
fragments — same approach as tests/test_cloud_findings.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from burnlens_cloud.digest import (
    build_weekly_digest,
    render_digest_html,
    send_weekly_digests,
)

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


class FakeConn:
    """Dispatches on SQL fragments the digest module writes."""

    def __init__(self, totals=None, models=None, features=None, waste=None,
                 owner_email="owner@example.com", workspaces=None):
        self.totals = totals
        self.models = models or []
        self.features = features or []
        self.waste = waste or {"open_count": 0, "waste_usd": 0}
        self.owner_email = owner_email
        self.workspaces = workspaces if workspaces is not None else [
            {"id": "ws-1", "name": "Acme"}
        ]
        self.sql_log: list[str] = []

    async def fetchrow(self, sql, *args):
        self.sql_log.append(sql)
        if "cost_this" in sql:
            return self.totals
        if "waste_findings" in sql:
            return self.waste
        if "email_encrypted" in sql:
            return {"email_encrypted": b"enc"} if self.owner_email else None
        return None

    async def fetch(self, sql, *args):
        self.sql_log.append(sql)
        if "FROM workspaces" in sql:
            return self.workspaces
        if "GROUP BY model" in sql:
            return self.models
        if "tags->>'feature'" in sql:
            return self.features
        return []


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


def _totals(cost_this=100.0, cost_prev=80.0, requests=500,
            prompt_tokens=200_000, cache_read=150_000):
    return {
        "cost_this": cost_this,
        "requests_this": requests,
        "prompt_tokens": prompt_tokens,
        "cache_read_tokens": cache_read,
        "cost_prev": cost_prev,
    }


# ---------------------------------------------------------------------------
# build_weekly_digest


async def test_digest_computes_week_over_week_delta():
    conn = FakeConn(
        totals=_totals(cost_this=100.0, cost_prev=80.0),
        models=[{"model": "claude-opus-5", "cost": 60.0, "requests": 120}],
        features=[{"tag": "chat", "cost": 70.0}],
        waste={"open_count": 2, "waste_usd": 12.5},
    )

    digest = await build_weekly_digest(conn, "ws-1", now=NOW)

    assert digest["cost_usd"] == 100.0
    assert digest["change_pct"] == 25.0          # 100 vs 80
    assert digest["cache_read_rate"] == 0.75
    assert digest["top_models"][0]["model"] == "claude-opus-5"
    assert digest["open_finding_count"] == 2
    assert digest["waste_usd"] == 12.5


async def test_digest_is_none_when_nothing_was_spent():
    """A "you spent $0" email is unsubscribe bait — do not send one."""
    conn = FakeConn(totals=_totals(cost_this=0.0, cost_prev=80.0))
    assert await build_weekly_digest(conn, "ws-1", now=NOW) is None


async def test_first_week_has_no_percentage_change():
    """No prior spend must not render as +100%."""
    conn = FakeConn(totals=_totals(cost_this=50.0, cost_prev=0.0))
    digest = await build_weekly_digest(conn, "ws-1", now=NOW)
    assert digest["change_pct"] is None


async def test_digest_queries_are_workspace_scoped():
    """A missing workspace predicate leaks another tenant's spend by email."""
    conn = FakeConn(totals=_totals())
    await build_weekly_digest(conn, "ws-1", now=NOW)
    spend_sql = [s for s in conn.sql_log if "request_records" in s]
    assert spend_sql
    for sql in spend_sql:
        assert "workspace_id = $1" in sql


async def test_prompt_tokens_are_provider_aware():
    """OpenAI folds cache reads into input_tokens; Anthropic does not. The
    query must branch, never sum blindly."""
    conn = FakeConn(totals=_totals())
    await build_weekly_digest(conn, "ws-1", now=NOW)
    totals_sql = next(s for s in conn.sql_log if "cost_this" in s)
    assert "CASE WHEN provider IN" in totals_sql
    assert "'openai'" in totals_sql and "'anthropic'" not in totals_sql


# ---------------------------------------------------------------------------
# render_digest_html


def _sample_digest(**over):
    d = {
        "period_start": "2026-08-09", "period_end": "2026-08-16",
        "cost_usd": 100.0, "prev_cost_usd": 80.0, "change_pct": 25.0,
        "request_count": 500, "prompt_tokens": 200_000,
        "cache_read_tokens": 150_000, "cache_read_rate": 0.75,
        "top_models": [{"model": "claude-opus-5", "cost_usd": 60.0, "request_count": 120}],
        "top_features": [{"tag": "chat", "cost_usd": 70.0}],
        "open_finding_count": 2, "waste_usd": 12.5,
    }
    d.update(over)
    return d


def test_html_renders_the_numbers_and_an_opt_out():
    html_body = render_digest_html(_sample_digest(), "Acme", "https://burnlens.app")
    assert "$100.00" in html_body
    assert "up 25.0%" in html_body
    assert "claude-opus-5" in html_body
    assert "75.0% served from cache" in html_body
    assert "$12.50" in html_body
    assert "https://burnlens.app/settings" in html_body


def test_html_escapes_a_hostile_workspace_name():
    """Workspace names and tags are user input landing in an email body."""
    html_body = render_digest_html(
        _sample_digest(top_features=[{"tag": "<script>x</script>", "cost_usd": 1.0}]),
        "<img src=x onerror=alert(1)>",
        "https://burnlens.app",
    )
    assert "<script>x</script>" not in html_body
    assert "<img src=x" not in html_body
    assert "&lt;script&gt;" in html_body


def test_html_says_so_when_there_is_no_prior_week():
    html_body = render_digest_html(
        _sample_digest(change_pct=None, prev_cost_usd=0.0), "Acme", "https://burnlens.app"
    )
    assert "No spend in the prior week" in html_body


# ---------------------------------------------------------------------------
# send_weekly_digests


async def test_send_loop_queues_one_email_per_workspace_with_spend():
    conn = FakeConn(
        totals=_totals(),
        models=[{"model": "claude-opus-5", "cost": 60.0, "requests": 120}],
    )
    with patch("burnlens_cloud.digest.mail_configured", return_value=True), \
         patch("burnlens_cloud.digest.decrypt_pii", return_value="owner@example.com"), \
         patch("burnlens_cloud.digest.deliver", return_value=True) as deliver:
        result = await send_weekly_digests(FakePool(conn), now=NOW)

    assert result == {"considered": 1, "sent": 1, "skipped_empty": 0}
    recipient, subject, body, what = deliver.call_args.args
    assert recipient == "owner@example.com"
    assert "$100.00" in subject
    assert what == "weekly digest"


async def test_send_loop_skips_quiet_workspaces_without_emailing():
    conn = FakeConn(totals=_totals(cost_this=0.0))
    with patch("burnlens_cloud.digest.mail_configured", return_value=True), \
         patch("burnlens_cloud.digest.deliver") as deliver:
        result = await send_weekly_digests(FakePool(conn), now=NOW)

    assert result == {"considered": 1, "sent": 0, "skipped_empty": 1}
    deliver.assert_not_called()


async def test_send_loop_noops_when_mail_is_unconfigured():
    """Same fail-open posture as every other sender — no crash, no send."""
    conn = FakeConn(totals=_totals())
    with patch("burnlens_cloud.digest.mail_configured", return_value=False), \
         patch("burnlens_cloud.digest.deliver") as deliver:
        result = await send_weekly_digests(FakePool(conn), now=NOW)

    assert result == {"considered": 0, "sent": 0, "skipped_empty": 0}
    deliver.assert_not_called()


async def test_send_loop_survives_one_bad_workspace():
    """One workspace failing must not stop the rest of the run."""
    conn = FakeConn(
        totals=_totals(),
        workspaces=[{"id": "ws-bad", "name": "Bad"}, {"id": "ws-ok", "name": "Ok"}],
    )
    calls = {"n": 0}

    async def flaky(c, workspace_id, now=None):
        calls["n"] += 1
        if workspace_id == "ws-bad":
            raise RuntimeError("boom")
        return _sample_digest()

    with patch("burnlens_cloud.digest.mail_configured", return_value=True), \
         patch("burnlens_cloud.digest.build_weekly_digest", side_effect=flaky), \
         patch("burnlens_cloud.digest.decrypt_pii", return_value="owner@example.com"), \
         patch("burnlens_cloud.digest.deliver", return_value=True):
        result = await send_weekly_digests(FakePool(conn), now=NOW)

    assert calls["n"] == 2
    assert result["considered"] == 2 and result["sent"] == 1


async def test_send_loop_only_selects_paid_opted_in_workspaces():
    conn = FakeConn(totals=_totals())
    with patch("burnlens_cloud.digest.mail_configured", return_value=True), \
         patch("burnlens_cloud.digest.decrypt_pii", return_value="o@e.com"), \
         patch("burnlens_cloud.digest.deliver", return_value=True):
        await send_weekly_digests(FakePool(conn), now=NOW)

    ws_sql = next(s for s in conn.sql_log if "FROM workspaces" in s)
    assert "plan != 'free'" in ws_sql
    assert "weekly_digest_enabled = true" in ws_sql


# ---------------------------------------------------------------------------
# POST /cron/weekly-digest


def _make_cron_app():
    from fastapi import FastAPI
    from unittest.mock import MagicMock

    from burnlens_cloud.cron_api import router as cron_router

    app = FastAPI()
    app.state.db_pool = MagicMock()
    app.include_router(cron_router)
    return app


def test_cron_weekly_digest_401_without_secret():
    from fastapi.testclient import TestClient

    from burnlens_cloud import config as config_mod

    with patch.object(config_mod.settings, "cron_secret", "test-cron-secret"):
        with TestClient(_make_cron_app(), raise_server_exceptions=False) as client:
            assert client.post("/cron/weekly-digest").status_code == 401
            assert client.post(
                "/cron/weekly-digest",
                headers={"Authorization": "Bearer wrong"},
            ).status_code == 401


def test_cron_weekly_digest_200_with_secret():
    from unittest.mock import AsyncMock, MagicMock

    from fastapi.testclient import TestClient

    from burnlens_cloud import config as config_mod

    with patch.object(config_mod.settings, "cron_secret", "test-cron-secret"), \
         patch("burnlens_cloud.cron_api.get_pool", return_value=MagicMock()), \
         patch(
             "burnlens_cloud.cron_api.send_weekly_digests",
             new=AsyncMock(return_value={"considered": 2, "sent": 1, "skipped_empty": 1}),
         ):
        with TestClient(_make_cron_app(), raise_server_exceptions=False) as client:
            resp = client.post(
                "/cron/weekly-digest",
                headers={"Authorization": "Bearer test-cron-secret"},
            )
    assert resp.status_code == 200
    assert resp.json()["sent"] == 1


def test_cron_weekly_digest_fails_open_on_error():
    """A mail-provider outage must not make the endpoint look broken to the
    scheduler, which fails the workflow on any non-200."""
    from unittest.mock import AsyncMock, MagicMock

    from fastapi.testclient import TestClient

    from burnlens_cloud import config as config_mod

    with patch.object(config_mod.settings, "cron_secret", "test-cron-secret"), \
         patch("burnlens_cloud.cron_api.get_pool", return_value=MagicMock()), \
         patch(
             "burnlens_cloud.cron_api.send_weekly_digests",
             new=AsyncMock(side_effect=RuntimeError("smtp down")),
         ):
        with TestClient(_make_cron_app(), raise_server_exceptions=False) as client:
            resp = client.post(
                "/cron/weekly-digest",
                headers={"Authorization": "Bearer test-cron-secret"},
            )
    assert resp.status_code == 200
    assert resp.json() == {"considered": 0, "sent": 0, "skipped_empty": 0}
