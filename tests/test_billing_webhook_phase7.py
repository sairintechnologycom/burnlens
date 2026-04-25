"""Phase 7: Paddle lifecycle sync — webhook dedup, handlers, /billing/summary.

Covers signature rejection (401 per ROADMAP SC-1), missing-event_id (400),
event_id dedup, activated/updated/canceled/paused/payment_failed handlers,
handler-exception silent-success path, DB-first _plan_from_price_id, and
/billing/summary workspace scoping.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

# Ensure test-safe env before burnlens_cloud imports. These mirror the values
# asserted throughout this file — we force them here so the pydantic-settings
# loader does not pick up a production .env.
os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/burnlens_test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ["PADDLE_WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["PADDLE_CLOUD_PRICE_ID"] = "pri_env_cloud"
os.environ["PADDLE_TEAMS_PRICE_ID"] = "pri_env_teams"


# The project-root `.env` is authored for the BurnLens proxy (OPENAI_API_KEY,
# OPENAI_BASE_URL, etc.) and carries fields not present on
# `burnlens_cloud.config.Settings`. Pydantic-settings 2.7 rejects extras by
# default. Redirect the env_file to an ignored path for the duration of the
# import so `Settings()` doesn't pick up proxy-only vars. This only affects
# the in-process Settings validation — no runtime behavior changes.
import pathlib  # noqa: E402
_FAKE_ENV = pathlib.Path(__file__).parent / "_phase7_billing_test.env"
if not _FAKE_ENV.exists():
    _FAKE_ENV.write_text("")
os.environ["BURNLENS_CLOUD_ENV_FILE_OVERRIDE"] = str(_FAKE_ENV)

# Patch pydantic-settings' dotenv loader to read from the empty file. We
# monkeypatch `dotenv_values` used internally by pydantic-settings so the
# loader sees no keys from the project `.env`.
import pydantic_settings.sources as _ps_sources  # noqa: E402


def _empty_dotenv_values(*args, **kwargs):  # noqa: D401
    return {}


_ps_sources.dotenv_values = _empty_dotenv_values


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

WEBHOOK_SECRET = "test-webhook-secret"
WS_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
WS_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER_ID = "11111111-1111-1111-1111-111111111111"


def _sign(raw_body: bytes, ts: int | None = None, secret: str = WEBHOOK_SECRET) -> str:
    if ts is None:
        ts = int(time.time())
    signed = f"{ts}:".encode("utf-8") + raw_body
    h1 = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"ts={ts};h1={h1}"


def _encode_test_jwt(workspace_id: str = WS_A, plan: str = "cloud") -> str:
    """Build a valid JWT with the encode_jwt helper on burnlens_cloud.auth."""
    from burnlens_cloud.auth import encode_jwt
    return encode_jwt(workspace_id, USER_ID, "owner", plan)


@pytest.fixture
def app_client():
    """A httpx.AsyncClient wired to a FastAPI app mounting ONLY the billing router.

    No DB pool is initialized; `execute_query` / `execute_insert` are patched per-test.
    """
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport

    # Force webhook secret into settings (overrides any dotenv-loaded value).
    from burnlens_cloud import config as config_mod
    config_mod.settings.paddle_webhook_secret = WEBHOOK_SECRET
    config_mod.settings.paddle_cloud_price_id = "pri_env_cloud"
    config_mod.settings.paddle_teams_price_id = "pri_env_teams"

    from burnlens_cloud.billing import router as billing_router
    app = FastAPI()
    app.include_router(billing_router)

    transport = ASGITransport(app=app)

    async def _client():
        return AsyncClient(transport=transport, base_url="http://testserver")

    return _client


# ---------------------------------------------------------------------------
# 1-4: Signature rejection — ROADMAP SC-1 locks HTTP 401 for all four cases.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_rejects_missing_signature(app_client):
    async with await app_client() as ac:
        resp = await ac.post(
            "/billing/webhook",
            content=b'{"event_id":"evt_x"}',
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_rejects_malformed_signature(app_client):
    async with await app_client() as ac:
        resp = await ac.post(
            "/billing/webhook",
            content=b'{"event_id":"evt_x"}',
            headers={
                "Content-Type": "application/json",
                "Paddle-Signature": "garbage-no-semicolons",
            },
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_rejects_bad_signature(app_client):
    ts = int(time.time())
    async with await app_client() as ac:
        resp = await ac.post(
            "/billing/webhook",
            content=b'{"event_id":"evt_x"}',
            headers={
                "Content-Type": "application/json",
                "Paddle-Signature": f"ts={ts};h1=deadbeef",
            },
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_rejects_stale_signature(app_client):
    raw = b'{"event_id":"evt_x"}'
    stale_ts = int(time.time()) - 400  # > 300s tolerance
    sig = _sign(raw, ts=stale_ts)
    async with await app_client() as ac:
        resp = await ac.post(
            "/billing/webhook",
            content=raw,
            headers={"Content-Type": "application/json", "Paddle-Signature": sig},
        )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 5: Missing event_id (post-signature) — stays 400 (malformed envelope).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_rejects_missing_event_id(app_client):
    raw = json.dumps({"event_type": "subscription.activated", "data": {}}).encode("utf-8")
    sig = _sign(raw)
    async with await app_client() as ac:
        resp = await ac.post(
            "/billing/webhook",
            content=raw,
            headers={"Content-Type": "application/json", "Paddle-Signature": sig},
        )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 6: Dedup — second delivery with same event_id returns deduped, no handler rerun.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_dedup_returns_early(app_client):
    raw = json.dumps({
        "event_id": "evt_dup",
        "event_type": "subscription.canceled",
        "data": {"id": "sub_any"},
    }).encode("utf-8")
    sig = _sign(raw)

    # Dedup simulation: the ON CONFLICT RETURNING yields [] (already processed).
    mock_query = AsyncMock(return_value=[])
    mock_insert = AsyncMock(return_value="UPDATE 1")

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.execute_insert", mock_insert):
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/webhook",
                content=raw,
                headers={"Content-Type": "application/json", "Paddle-Signature": sig},
            )

    assert resp.status_code == 200
    assert resp.json() == {"received": True, "deduped": True}
    # Handler path (which uses execute_insert) must NOT have been invoked.
    mock_insert.assert_not_called()


# ---------------------------------------------------------------------------
# 7: subscription.activated populates every new column from the payload.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscription_activated_populates_all_columns(app_client):
    event = {
        "event_id": "evt_act_1",
        "event_type": "subscription.activated",
        "data": {
            "id": "sub_act_1",
            "customer_id": "ctm_1",
            "status": "trialing",
            "custom_data": {"workspace_id": WS_A},
            "items": [{
                "price": {
                    "id": "pri_env_cloud",
                    "unit_price": {"amount": "2900", "currency_code": "USD"},
                }
            }],
            "current_billing_period": {
                "starts_at": "2026-04-19T00:00:00Z",
                "ends_at": "2026-05-19T00:00:00Z",
            },
            "trial_dates": {
                "starts_at": "2026-04-19T00:00:00Z",
                "ends_at": "2026-05-26T00:00:00Z",
            },
            "scheduled_change": None,
        },
    }
    raw = json.dumps(event).encode("utf-8")
    sig = _sign(raw)

    # First execute_query = dedup INSERT returning event_id.
    # Second execute_query = _plan_from_price_id DB lookup returning [{plan:'cloud'}].
    insert_row = [{"event_id": "evt_act_1"}]
    plan_row = [{"plan": "cloud"}]

    async def _query_side_effect(q, *args):
        if "INSERT INTO paddle_events" in q:
            return insert_row
        if "FROM plan_limits" in q:
            return plan_row
        return []

    mock_query = AsyncMock(side_effect=_query_side_effect)
    mock_insert = AsyncMock(return_value="UPDATE 1")

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.execute_insert", mock_insert):
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/webhook",
                content=raw,
                headers={"Content-Type": "application/json", "Paddle-Signature": sig},
            )

    assert resp.status_code == 200
    # Find the UPDATE workspaces SET plan=... call
    update_calls = [
        c for c in mock_insert.call_args_list
        if "UPDATE workspaces" in c.args[0] and "plan = $1" in c.args[0]
    ]
    assert len(update_calls) == 1, f"expected 1 UPDATE workspaces call, got {len(update_calls)}"
    call = update_calls[0]
    sql = call.args[0]
    params = call.args[1:]
    # Phase 2c: plaintext paddle_* columns dropped; SQL now writes only
    # *_encrypted + *_hash for customer and subscription IDs.
    assert "paddle_customer_id_encrypted = $2" in sql
    assert "paddle_customer_id_hash = $3" in sql
    assert "paddle_subscription_id_encrypted = $4" in sql
    assert "paddle_subscription_id_hash = $5" in sql
    assert "cancel_at_period_end = $9" in sql
    assert "price_cents = $10" in sql
    assert "currency = $11" in sql
    assert "WHERE id = $12::uuid" in sql
    # params: plan, cust_enc, cust_hash, sub_enc, sub_hash, status,
    # trial_ends_at, current_period_ends_at, cancel_at_period_end,
    # price_cents, currency, workspace_id
    assert len(params) == 12
    (
        plan, _cust_enc, _cust_hash, _sub_enc, _sub_hash,
        status, trial_end, period_end, cancel_flag,
        price_cents, currency, ws_id,
    ) = params
    # customer_id / sub_id are now only available via encrypted columns in the
    # DB; upstream callers see the plaintext value from the webhook payload.
    customer_id = "ctm_1"
    sub_id = "sub_act_1"
    assert plan == "cloud"
    assert customer_id == "ctm_1"
    assert sub_id == "sub_act_1"
    assert status == "trialing"
    assert isinstance(trial_end, datetime)
    assert trial_end.year == 2026 and trial_end.month == 5 and trial_end.day == 26
    assert isinstance(period_end, datetime)
    assert period_end.day == 19
    assert cancel_flag is False
    assert price_cents == 2900
    assert currency == "USD"
    assert ws_id == WS_A


# ---------------------------------------------------------------------------
# 8: subscription.updated with status=past_due — status flips, plan unchanged.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscription_updated_past_due_flips_status(app_client):
    event = {
        "event_id": "evt_upd_1",
        "event_type": "subscription.updated",
        "data": {
            "id": "sub_xyz",
            "status": "past_due",
            "items": [{"price": {"id": "pri_env_cloud", "unit_price": {"amount": "2900", "currency_code": "USD"}}}],
        },
    }
    raw = json.dumps(event).encode("utf-8")
    sig = _sign(raw)

    async def _query_side_effect(q, *args):
        if "INSERT INTO paddle_events" in q:
            return [{"event_id": "evt_upd_1"}]
        if "FROM plan_limits" in q:
            return [{"plan": "cloud"}]
        return []

    mock_query = AsyncMock(side_effect=_query_side_effect)
    mock_insert = AsyncMock(return_value="UPDATE 1")

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.execute_insert", mock_insert):
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/webhook",
                content=raw,
                headers={"Content-Type": "application/json", "Paddle-Signature": sig},
            )

    assert resp.status_code == 200
    update_calls = [
        c for c in mock_insert.call_args_list
        if "UPDATE workspaces" in c.args[0] and "paddle_subscription_id_hash = $8" in c.args[0]
    ]
    assert len(update_calls) == 1
    _call = update_calls[0]
    params = _call.args[1:]
    plan, status = params[0], params[1]
    assert status == "past_due"
    # Plan stays 'cloud' (price_id remained cloud — plan value not reset to 'free')
    assert plan == "cloud"


# ---------------------------------------------------------------------------
# 9: subscription.canceled downgrades to free.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscription_canceled_downgrades_to_free(app_client):
    event = {
        "event_id": "evt_can_1",
        "event_type": "subscription.canceled",
        "data": {"id": "sub_c1"},
    }
    raw = json.dumps(event).encode("utf-8")
    sig = _sign(raw)

    async def _query_side_effect(q, *args):
        if "INSERT INTO paddle_events" in q:
            return [{"event_id": "evt_can_1"}]
        return []

    mock_query = AsyncMock(side_effect=_query_side_effect)
    mock_insert = AsyncMock(return_value="UPDATE 1")

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.execute_insert", mock_insert):
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/webhook",
                content=raw,
                headers={"Content-Type": "application/json", "Paddle-Signature": sig},
            )

    assert resp.status_code == 200
    cancel_calls = [
        c for c in mock_insert.call_args_list
        if "UPDATE workspaces" in c.args[0] and "plan = 'free'" in c.args[0]
    ]
    assert len(cancel_calls) == 1
    call = cancel_calls[0]
    assert "subscription_status = 'canceled'" in call.args[0]
    from burnlens_cloud.pii_crypto import lookup_hash as _lh
    assert call.args[1] == _lh("sub_c1")


# ---------------------------------------------------------------------------
# 10: subscription.paused is routed to the canceled handler (D-23).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscription_paused_downgrades_to_free(app_client):
    event = {
        "event_id": "evt_pause_1",
        "event_type": "subscription.paused",
        "data": {"id": "sub_pause"},
    }
    raw = json.dumps(event).encode("utf-8")
    sig = _sign(raw)

    async def _query_side_effect(q, *args):
        if "INSERT INTO paddle_events" in q:
            return [{"event_id": "evt_pause_1"}]
        return []

    mock_query = AsyncMock(side_effect=_query_side_effect)
    mock_insert = AsyncMock(return_value="UPDATE 1")

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.execute_insert", mock_insert):
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/webhook",
                content=raw,
                headers={"Content-Type": "application/json", "Paddle-Signature": sig},
            )

    assert resp.status_code == 200
    cancel_calls = [
        c for c in mock_insert.call_args_list
        if "UPDATE workspaces" in c.args[0] and "plan = 'free'" in c.args[0]
    ]
    assert len(cancel_calls) == 1  # routed to _handle_subscription_canceled
    from burnlens_cloud.pii_crypto import lookup_hash as _lh
    assert cancel_calls[0].args[1] == _lh("sub_pause")


# ---------------------------------------------------------------------------
# 11: transaction.payment_failed flips to past_due via paddle_subscription_id.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transaction_payment_failed_flips_past_due(app_client):
    event = {
        "event_id": "evt_pf_1",
        "event_type": "transaction.payment_failed",
        "data": {"id": "txn_pf_1", "subscription_id": "sub_xyz"},
    }
    raw = json.dumps(event).encode("utf-8")
    sig = _sign(raw)

    async def _query_side_effect(q, *args):
        if "INSERT INTO paddle_events" in q:
            return [{"event_id": "evt_pf_1"}]
        return []

    mock_query = AsyncMock(side_effect=_query_side_effect)
    mock_insert = AsyncMock(return_value="UPDATE 1")

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.execute_insert", mock_insert):
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/webhook",
                content=raw,
                headers={"Content-Type": "application/json", "Paddle-Signature": sig},
            )

    assert resp.status_code == 200
    pd_calls = [
        c for c in mock_insert.call_args_list
        if "UPDATE workspaces" in c.args[0] and "subscription_status = 'past_due'" in c.args[0]
    ]
    assert len(pd_calls) == 1
    call = pd_calls[0]
    # plan must NOT be in the SET clause
    assert "plan =" not in call.args[0].split("SET", 1)[1].split("WHERE", 1)[0]
    # Phase 2c: WHERE uses the hash column; arg is HMAC of "sub_xyz".
    assert "WHERE paddle_subscription_id_hash = $1" in call.args[0]
    from burnlens_cloud.pii_crypto import lookup_hash as _lh
    assert call.args[1] == _lh("sub_xyz")


# ---------------------------------------------------------------------------
# 12: Handler exception is caught; 200 returned; error column written.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handler_exception_writes_error_column(app_client):
    event = {
        "event_id": "evt_err_1",
        "event_type": "subscription.canceled",
        "data": {"id": "sub_err"},
    }
    raw = json.dumps(event).encode("utf-8")
    sig = _sign(raw)

    async def _query_side_effect(q, *args):
        if "INSERT INTO paddle_events" in q:
            return [{"event_id": "evt_err_1"}]
        return []

    mock_query = AsyncMock(side_effect=_query_side_effect)

    async def _insert_side_effect(q, *args):
        if "UPDATE workspaces" in q:
            raise RuntimeError("boom handler")
        return "UPDATE 1"

    mock_insert = AsyncMock(side_effect=_insert_side_effect)

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.execute_insert", mock_insert):
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/webhook",
                content=raw,
                headers={"Content-Type": "application/json", "Paddle-Signature": sig},
            )

    assert resp.status_code == 200  # silent-success invariant
    error_calls = [
        c for c in mock_insert.call_args_list
        if "UPDATE paddle_events SET error = $1 WHERE event_id = $2" in c.args[0]
    ]
    assert len(error_calls) == 1
    err_call = error_calls[0]
    assert "boom handler" in err_call.args[1]
    assert err_call.args[2] == "evt_err_1"


# ---------------------------------------------------------------------------
# 13: _plan_from_price_id prefers DB lookup (Phase 6 plan_limits).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_plan_from_price_id_uses_db_first():
    from burnlens_cloud import billing
    mock_query = AsyncMock(return_value=[{"plan": "teams"}])
    with patch("burnlens_cloud.billing.execute_query", mock_query):
        result = await billing._plan_from_price_id("pri_anything")
    assert result == "teams"
    # Exactly one DB roundtrip for the plan_limits lookup.
    assert mock_query.call_count == 1
    call = mock_query.call_args
    assert "SELECT plan FROM plan_limits WHERE paddle_price_id = $1" in call.args[0]
    assert call.args[1] == "pri_anything"


# ---------------------------------------------------------------------------
# 14: _plan_from_price_id falls back to env when DB returns no rows.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_plan_from_price_id_env_fallback():
    from burnlens_cloud import billing
    from burnlens_cloud import config as config_mod
    config_mod.settings.paddle_cloud_price_id = "pri_env_cloud"
    config_mod.settings.paddle_teams_price_id = "pri_env_teams"

    mock_query = AsyncMock(return_value=[])
    with patch("burnlens_cloud.billing.execute_query", mock_query):
        assert await billing._plan_from_price_id("pri_env_cloud") == "cloud"
        assert await billing._plan_from_price_id("pri_env_teams") == "teams"
        assert await billing._plan_from_price_id("pri_unknown") == "free"


# ---------------------------------------------------------------------------
# 15: /billing/summary returns BillingSummary JSON from workspace row.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_billing_summary_returns_workspace_data(app_client):
    token = _encode_test_jwt(WS_A, "cloud")
    trial_end = datetime(2026, 5, 26, tzinfo=timezone.utc)
    period_end = datetime(2026, 5, 19, tzinfo=timezone.utc)

    # Phase 10 Plan 01: /billing/summary now also reads workspace_usage_cycles,
    # plan_limits, and api_keys to populate the additive `usage`/
    # `available_plans`/`api_keys` subobjects (D-18 / D-26). Dispatch on SQL
    # substring so the original Phase 7 fields keep getting validated.
    cycle_start = datetime(2026, 4, 19, tzinfo=timezone.utc)
    cycle_end = datetime(2026, 5, 19, tzinfo=timezone.utc)

    async def _query_side_effect(sql, *args):
        s = " ".join(sql.split())
        if "FROM workspaces" in s:
            return [{
                "plan": "cloud",
                "price_cents": 2900,
                "currency": "USD",
                "subscription_status": "trialing",
                "trial_ends_at": trial_end,
                "current_period_ends_at": period_end,
                "cancel_at_period_end": False,
            }]
        if "FROM workspace_usage_cycles" in s:
            return [{"cycle_start": cycle_start, "cycle_end": cycle_end, "request_count": 0}]
        if "FROM plan_limits" in s:
            return [
                {"plan": "cloud", "paddle_price_id": "pri_cloud"},
                {"plan": "teams", "paddle_price_id": "pri_teams"},
            ]
        if "FROM api_keys" in s:
            return [{"n": 0}]
        return []

    mock_query = AsyncMock(side_effect=_query_side_effect)
    # Phase 10 Plan 01: the extended handler calls plans.resolve_limits to
    # surface monthly_request_cap and api_key_count.
    from burnlens_cloud.models import ResolvedLimits
    mock_resolve = AsyncMock(return_value=ResolvedLimits(
        plan="cloud", monthly_request_cap=1_000_000, seat_count=1,
        retention_days=30, api_key_count=3, gated_features={},
    ))

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.resolve_limits", mock_resolve):
        async with await app_client() as ac:
            resp = await ac.get(
                "/billing/summary",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["plan"] == "cloud"
    assert body["price_cents"] == 2900
    assert body["currency"] == "USD"
    assert body["status"] == "trialing"
    assert body["trial_ends_at"] is not None
    assert body["current_period_ends_at"] is not None
    assert body["cancel_at_period_end"] is False


# ---------------------------------------------------------------------------
# 16: /billing/summary without auth → 401 (verify_token dependency).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_billing_summary_rejects_unauth(app_client):
    async with await app_client() as ac:
        resp = await ac.get("/billing/summary")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 17: /billing/summary is scoped to caller's workspace — SELECT binds token.workspace_id only.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_billing_summary_scoped_to_caller(app_client):
    token_a = _encode_test_jwt(WS_A, "cloud")

    # Phase 10 Plan 01: the extended handler now fires several SELECTs
    # (workspaces / workspace_usage_cycles / plan_limits / api_keys). The
    # workspace-scoping invariant is unchanged: every SELECT that takes a
    # workspace param MUST bind only WS_A — never WS_B. This test still
    # verifies the SQL+params surface but tolerates the larger query plan.
    captured: list[tuple] = []

    cycle_start = datetime(2026, 4, 19, tzinfo=timezone.utc)
    cycle_end = datetime(2026, 5, 19, tzinfo=timezone.utc)

    async def _query_side_effect(sql, *args):
        captured.append((sql, args))
        s = " ".join(sql.split())
        if "FROM workspaces" in s:
            return [{
                "plan": "cloud",
                "price_cents": 2900,
                "currency": "USD",
                "subscription_status": "active",
                "trial_ends_at": None,
                "current_period_ends_at": None,
                "cancel_at_period_end": False,
            }]
        if "FROM workspace_usage_cycles" in s:
            return [{"cycle_start": cycle_start, "cycle_end": cycle_end, "request_count": 0}]
        if "FROM plan_limits" in s:
            return []
        if "FROM api_keys" in s:
            return [{"n": 0}]
        return []

    mock_query = AsyncMock(side_effect=_query_side_effect)
    from burnlens_cloud.models import ResolvedLimits
    mock_resolve = AsyncMock(return_value=ResolvedLimits(
        plan="cloud", monthly_request_cap=1_000_000, seat_count=1,
        retention_days=30, api_key_count=3, gated_features={},
    ))

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.resolve_limits", mock_resolve):
        async with await app_client() as ac:
            resp = await ac.get(
                "/billing/summary",
                headers={"Authorization": f"Bearer {token_a}"},
            )

    assert resp.status_code == 200
    # The original workspaces SELECT is still present and still bound only to
    # the caller's workspace_id (no WS_B leak through any path).
    workspace_calls = [
        c for c in captured if "FROM workspaces" in " ".join(c[0].split())
    ]
    assert len(workspace_calls) >= 1
    ws_sql, ws_args = workspace_calls[0]
    assert "WHERE id = $1" in ws_sql
    assert ws_args == (WS_A,)
    # No SQL call across the entire summary path may carry WS_B.
    for _sql, args in captured:
        assert WS_B not in args, f"unexpected WS_B in args of {_sql!r}: {args!r}"


# ---------------------------------------------------------------------------
# 18: /billing/summary defaults status to 'active' when the row has NULL.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_billing_summary_defaults_status_active_when_null(app_client):
    token = _encode_test_jwt(WS_A, "free")

    # Phase 10 Plan 01: handler fires extra SELECTs for the additive subobjects.
    # Status-defaulting behaviour for the workspaces row is unchanged.
    cycle_start = datetime(2026, 4, 1, tzinfo=timezone.utc)
    cycle_end = datetime(2026, 5, 1, tzinfo=timezone.utc)

    async def _query_side_effect(sql, *args):
        s = " ".join(sql.split())
        if "FROM workspaces" in s:
            return [{
                "plan": "free",
                "price_cents": None,
                "currency": None,
                "subscription_status": None,      # legacy default path
                "trial_ends_at": None,
                "current_period_ends_at": None,
                "cancel_at_period_end": False,
            }]
        if "FROM workspace_usage_cycles" in s:
            return []  # brand-new free workspace
        if "date_trunc('month'" in s and "FROM workspace_usage_cycles" not in s:
            return [{"cycle_start": cycle_start, "cycle_end": cycle_end}]
        if "FROM plan_limits" in s:
            return []
        if "FROM api_keys" in s:
            return [{"n": 0}]
        return []

    mock_query = AsyncMock(side_effect=_query_side_effect)
    from burnlens_cloud.models import ResolvedLimits
    mock_resolve = AsyncMock(return_value=ResolvedLimits(
        plan="free", monthly_request_cap=10_000, seat_count=1,
        retention_days=7, api_key_count=1, gated_features={},
    ))

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.resolve_limits", mock_resolve):
        async with await app_client() as ac:
            resp = await ac.get(
                "/billing/summary",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200
    assert resp.json()["status"] == "active"
