"""Phase 8: billing self-service — change-plan, cancel, reactivate, invoices, plans.

Covers:
  - ChangePlanBody / CancelBody model validation
  - POST /billing/change-plan  (401, idempotent, 400-free, 400-no-sub, upgrade, downgrade, 5xx, timeout)
  - POST /billing/cancel       (401, idempotent, 400-free, happy+survey, happy-no-survey, 5xx)
  - POST /billing/reactivate   (401, idempotent, 400-period-ended, 400-status-canceled, happy, 5xx)
  - GET  /billing/invoices     (401, free-empty, PDF-fail-soft, 5xx)
  - GET  /billing/plans        (401, cloud+teams rows, empty returns {"plans": []})
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Safe env — mirrors Phase 7 pattern.
# ---------------------------------------------------------------------------
os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/burnlens_test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ["PADDLE_WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["PADDLE_CLOUD_PRICE_ID"] = "pri_env_cloud"
os.environ["PADDLE_TEAMS_PRICE_ID"] = "pri_env_teams"

import pathlib  # noqa: E402
_FAKE_ENV = pathlib.Path(__file__).parent / "_phase8_billing_test.env"
if not _FAKE_ENV.exists():
    _FAKE_ENV.write_text("")
os.environ["BURNLENS_CLOUD_ENV_FILE_OVERRIDE"] = str(_FAKE_ENV)

import pydantic_settings.sources as _ps_sources  # noqa: E402


def _empty_dotenv_values(*args, **kwargs):  # noqa: D401
    return {}


_ps_sources.dotenv_values = _empty_dotenv_values

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

WS_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
WS_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER_ID = "11111111-1111-1111-1111-111111111111"

SUB_ENC = "enc_sub_aaa"          # fake encrypted subscription id value
CUST_ENC = "enc_cust_aaa"        # fake encrypted customer id value


def _encode_test_jwt(workspace_id: str = WS_A, plan: str = "cloud") -> str:
    from burnlens_cloud.auth import encode_jwt
    return encode_jwt(workspace_id, USER_ID, "owner", plan)


@pytest.fixture
def app_client():
    """httpx.AsyncClient wired to a FastAPI app mounting ONLY the billing router.

    No DB pool is initialised; execute_query / execute_insert are patched per-test.
    PADDLE_API_KEY is injected so endpoints don't 500 before the test logic.
    """
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport

    from burnlens_cloud import config as config_mod
    config_mod.settings.paddle_webhook_secret = "test-webhook-secret"
    config_mod.settings.paddle_cloud_price_id = "pri_env_cloud"
    config_mod.settings.paddle_teams_price_id = "pri_env_teams"
    config_mod.settings.paddle_api_key = "test-paddle-api-key"

    from burnlens_cloud.billing import router as billing_router
    app = FastAPI()
    app.include_router(billing_router)

    transport = ASGITransport(app=app)

    async def _client():
        return AsyncClient(transport=transport, base_url="http://testserver")

    return _client


# ---------------------------------------------------------------------------
# Helper: build a minimal _load_billing_summary workspace row
# ---------------------------------------------------------------------------

def _ws_row(
    plan: str = "cloud",
    cancel_at_period_end: bool = False,
    subscription_status: str = "active",
    current_period_ends_at=None,
    scheduled_plan=None,
    scheduled_change_at=None,
):
    return {
        "plan": plan,
        "price_cents": 2900,
        "currency": "USD",
        "subscription_status": subscription_status,
        "trial_ends_at": None,
        "current_period_ends_at": current_period_ends_at,
        "cancel_at_period_end": cancel_at_period_end,
        "scheduled_plan": scheduled_plan,
        "scheduled_change_at": scheduled_change_at,
    }


# ===========================================================================
# 1. Model validation
# ===========================================================================

class TestChangePlanBodyValidation:
    def test_valid_cloud(self):
        from burnlens_cloud.models import ChangePlanBody
        b = ChangePlanBody(target_plan="cloud")
        assert b.target_plan == "cloud"

    def test_valid_teams(self):
        from burnlens_cloud.models import ChangePlanBody
        b = ChangePlanBody(target_plan="TEAMS")   # should be lowercased
        assert b.target_plan == "teams"

    def test_rejects_free(self):
        from burnlens_cloud.models import ChangePlanBody
        import pydantic
        with pytest.raises((pydantic.ValidationError, ValueError)):
            ChangePlanBody(target_plan="free")

    def test_rejects_garbage(self):
        from burnlens_cloud.models import ChangePlanBody
        import pydantic
        with pytest.raises((pydantic.ValidationError, ValueError)):
            ChangePlanBody(target_plan="enterprise")


class TestCancelBodyValidation:
    def test_empty_body_ok(self):
        from burnlens_cloud.models import CancelBody
        b = CancelBody()
        assert b.reason_code is None
        assert b.reason_text is None

    def test_with_reason_code(self):
        from burnlens_cloud.models import CancelBody
        b = CancelBody(reason_code="too_expensive")
        assert b.reason_code == "too_expensive"

    def test_reason_code_max_length(self):
        from burnlens_cloud.models import CancelBody
        import pydantic
        with pytest.raises((pydantic.ValidationError, ValueError)):
            CancelBody(reason_code="x" * 65)

    def test_reason_text_max_length(self):
        from burnlens_cloud.models import CancelBody
        import pydantic
        with pytest.raises((pydantic.ValidationError, ValueError)):
            CancelBody(reason_text="x" * 1001)


# ===========================================================================
# 2. POST /billing/change-plan
# ===========================================================================

@pytest.mark.asyncio
async def test_change_plan_401_unauth(app_client):
    async with await app_client() as ac:
        resp = await ac.post("/billing/change-plan", json={"target_plan": "teams"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_change_plan_idempotent_noop(app_client):
    """target_plan == current plan → return summary, no Paddle call."""
    token = _encode_test_jwt(WS_A, "cloud")

    # The endpoint SELECTs different columns on each query:
    #   1st: plan + paddle_subscription_id_encrypted + paddle_customer_id_encrypted + current_period_ends_at
    #   2nd (_load_billing_summary): plan + price_cents + currency + subscription_status + ...
    call_count = {"n": 0}

    async def _query_side(q, *args):
        if "FROM workspaces" in q:
            call_count["n"] += 1
            if call_count["n"] == 1:
                # change-plan initial SELECT
                return [{
                    "plan": "cloud",
                    "paddle_subscription_id_encrypted": None,
                    "paddle_customer_id_encrypted": None,
                    "current_period_ends_at": None,
                }]
            else:
                # _load_billing_summary SELECT
                return [_ws_row(plan="cloud")]
        return []

    mock_query = AsyncMock(side_effect=_query_side)
    mock_insert = AsyncMock(return_value="UPDATE 1")

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.execute_insert", mock_insert), \
         patch("burnlens_cloud.billing.httpx.AsyncClient") as mock_http:
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/change-plan",
                json={"target_plan": "cloud"},
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["plan"] == "cloud"
    # No Paddle HTTP call should have been made
    mock_http.assert_not_called()


@pytest.mark.asyncio
async def test_change_plan_400_target_free(app_client):
    """target_plan='free' must be rejected before any DB hit."""
    token = _encode_test_jwt(WS_A, "cloud")
    async with await app_client() as ac:
        resp = await ac.post(
            "/billing/change-plan",
            json={"target_plan": "free"},
            headers={"Authorization": f"Bearer {token}"},
        )
    # Pydantic validator rejects "free" at model level → 422 (Unprocessable Entity)
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_change_plan_400_no_subscription(app_client):
    """No subscription_id on workspace → 400."""
    token = _encode_test_jwt(WS_A, "cloud")

    # First query: workspace row (no subscription_id_encrypted → decrypts to None)
    # Second query (inside _load_billing_summary): won't be reached
    async def _query_side(q, *args):
        if "FROM workspaces" in q:
            return [{
                "plan": "cloud",
                "paddle_subscription_id_encrypted": None,
                "paddle_customer_id_encrypted": None,
                "current_period_ends_at": None,
            }]
        return []

    mock_query = AsyncMock(side_effect=_query_side)

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.execute_insert", AsyncMock()):
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/change-plan",
                json={"target_plan": "teams"},
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 400
    assert "subscription" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_change_plan_upgrade_cloud_to_teams(app_client):
    """Upgrade path: proration_billing_mode=prorated_immediately, plan flips immediately."""
    token = _encode_test_jwt(WS_A, "cloud")

    future = datetime.now(timezone.utc) + timedelta(days=14)

    call_count = {"n": 0}

    async def _query_side(q, *args):
        s = " ".join(q.split())
        if "FROM workspaces" in s:
            call_count["n"] += 1
            if call_count["n"] == 1:
                # Initial workspace fetch for change-plan logic
                # _ws_pii_value is patched so the encrypted value is never decrypted
                return [{
                    "plan": "cloud",
                    "paddle_subscription_id_encrypted": SUB_ENC,
                    "paddle_customer_id_encrypted": CUST_ENC,
                    "current_period_ends_at": future,
                }]
            else:
                # _load_billing_summary after update
                return [_ws_row(plan="teams", current_period_ends_at=future)]
        return []

    mock_query = AsyncMock(side_effect=_query_side)
    mock_insert = AsyncMock(return_value="UPDATE 1")

    # Mock Paddle PATCH response
    mock_paddle_resp = MagicMock()
    mock_paddle_resp.status_code = 200
    mock_paddle_resp.json.return_value = {"data": {"id": "sub_real_id", "status": "active"}}

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.patch = AsyncMock(return_value=mock_paddle_resp)

    # Patch _ws_pii_value at the billing module level so decrypt_pii is never called
    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.execute_insert", mock_insert), \
         patch("burnlens_cloud.billing.httpx.AsyncClient", return_value=mock_http_client), \
         patch("burnlens_cloud.billing._ws_pii_value", side_effect=lambda row, plain, enc: "sub_real_id"):
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/change-plan",
                json={"target_plan": "teams"},
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200
    # Paddle was called with patch + proration_billing_mode=prorated_immediately
    mock_http_client.patch.assert_called_once()
    patch_call = mock_http_client.patch.call_args
    payload = patch_call.kwargs.get("json") or {}
    assert payload.get("proration_billing_mode") == "prorated_immediately"

    # DB write: plan flips to teams immediately
    upgrade_updates = [
        c for c in mock_insert.call_args_list
        if "UPDATE workspaces" in c.args[0] and "plan = $1" in c.args[0]
    ]
    assert len(upgrade_updates) == 1
    assert upgrade_updates[0].args[1] == "teams"


@pytest.mark.asyncio
async def test_change_plan_downgrade_teams_to_cloud(app_client):
    """Downgrade path: effective_from=next_billing_period, scheduled_plan written."""
    token = _encode_test_jwt(WS_A, "teams")

    future = datetime.now(timezone.utc) + timedelta(days=14)
    call_count = {"n": 0}

    async def _query_side(q, *args):
        s = " ".join(q.split())
        if "FROM workspaces" in s:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [{
                    "plan": "teams",
                    "paddle_subscription_id_encrypted": SUB_ENC,
                    "paddle_customer_id_encrypted": CUST_ENC,
                    "current_period_ends_at": future,
                }]
            else:
                return [_ws_row(plan="teams", scheduled_plan="cloud",
                                scheduled_change_at=future, current_period_ends_at=future)]
        return []

    mock_query = AsyncMock(side_effect=_query_side)
    mock_insert = AsyncMock(return_value="UPDATE 1")

    mock_paddle_resp = MagicMock()
    mock_paddle_resp.status_code = 200
    mock_paddle_resp.json.return_value = {"data": {"id": "sub_real_id"}}

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.patch = AsyncMock(return_value=mock_paddle_resp)

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.execute_insert", mock_insert), \
         patch("burnlens_cloud.billing.httpx.AsyncClient", return_value=mock_http_client), \
         patch("burnlens_cloud.billing._ws_pii_value", return_value="sub_real_id"):
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/change-plan",
                json={"target_plan": "cloud"},
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200
    # Paddle called with effective_from=next_billing_period
    patch_call = mock_http_client.patch.call_args
    payload = patch_call.kwargs.get("json") or {}
    assert payload.get("effective_from") == "next_billing_period"

    # DB write: scheduled_plan=cloud, NOT plan flip
    scheduled_updates = [
        c for c in mock_insert.call_args_list
        if "scheduled_plan = $1" in c.args[0]
    ]
    assert len(scheduled_updates) == 1
    assert scheduled_updates[0].args[1] == "cloud"


@pytest.mark.asyncio
async def test_change_plan_paddle_5xx_returns_502(app_client):
    """Paddle 5xx → 502; workspaces row must NOT be mutated."""
    token = _encode_test_jwt(WS_A, "cloud")

    future = datetime.now(timezone.utc) + timedelta(days=14)

    mock_query = AsyncMock(return_value=[{
        "plan": "cloud",
        "paddle_subscription_id_encrypted": SUB_ENC,
        "paddle_customer_id_encrypted": CUST_ENC,
        "current_period_ends_at": future,
    }])
    mock_insert = AsyncMock(return_value="UPDATE 1")

    mock_paddle_resp = MagicMock()
    mock_paddle_resp.status_code = 503
    mock_paddle_resp.text = "Service Unavailable"

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.patch = AsyncMock(return_value=mock_paddle_resp)

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.execute_insert", mock_insert), \
         patch("burnlens_cloud.billing.httpx.AsyncClient", return_value=mock_http_client), \
         patch("burnlens_cloud.billing._ws_pii_value", return_value="sub_real_id"):
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/change-plan",
                json={"target_plan": "teams"},
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 502
    # No DB mutation must have occurred
    mock_insert.assert_not_called()


@pytest.mark.asyncio
async def test_change_plan_paddle_timeout_returns_502(app_client):
    """Paddle timeout → 502; no DB mutation."""
    import httpx as _httpx

    token = _encode_test_jwt(WS_A, "cloud")
    future = datetime.now(timezone.utc) + timedelta(days=14)

    mock_query = AsyncMock(return_value=[{
        "plan": "cloud",
        "paddle_subscription_id_encrypted": SUB_ENC,
        "paddle_customer_id_encrypted": CUST_ENC,
        "current_period_ends_at": future,
    }])
    mock_insert = AsyncMock(return_value="UPDATE 1")

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.patch = AsyncMock(side_effect=_httpx.TimeoutException("timed out"))

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.execute_insert", mock_insert), \
         patch("burnlens_cloud.billing.httpx.AsyncClient", return_value=mock_http_client), \
         patch("burnlens_cloud.billing._ws_pii_value", return_value="sub_real_id"):
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/change-plan",
                json={"target_plan": "teams"},
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 502
    mock_insert.assert_not_called()


# ===========================================================================
# 3. POST /billing/cancel
# ===========================================================================

@pytest.mark.asyncio
async def test_cancel_401_unauth(app_client):
    async with await app_client() as ac:
        resp = await ac.post("/billing/cancel")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cancel_idempotent_already_canceled(app_client):
    """cancel_at_period_end already True → return summary, no Paddle call."""
    token = _encode_test_jwt(WS_A, "cloud")

    # cancel reads: plan + paddle_subscription_id_encrypted + cancel_at_period_end
    # _load_billing_summary reads: plan + price_cents + currency + subscription_status + ...
    call_count = {"n": 0}

    async def _query_side(q, *args):
        if "FROM workspaces" in q:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [{
                    "plan": "cloud",
                    "paddle_subscription_id_encrypted": None,
                    "cancel_at_period_end": True,
                }]
            else:
                return [_ws_row(plan="cloud", cancel_at_period_end=True)]
        return []

    mock_query = AsyncMock(side_effect=_query_side)

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.execute_insert", AsyncMock()), \
         patch("burnlens_cloud.billing.httpx.AsyncClient") as mock_http:
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/cancel",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200
    mock_http.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_400_free_plan(app_client):
    """Free plan workspace → 400."""
    token = _encode_test_jwt(WS_A, "free")

    mock_query = AsyncMock(return_value=[{
        "plan": "free",
        "paddle_subscription_id_encrypted": None,
        "cancel_at_period_end": False,
    }])

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing._ws_pii_value", return_value=None):
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/cancel",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 400
    assert "subscription" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cancel_happy_path_with_survey(app_client):
    """Cancel succeeds, survey row written, cancel_at_period_end=true DB update fires."""
    token = _encode_test_jwt(WS_A, "cloud")
    call_count = {"n": 0}

    async def _query_side(q, *args):
        if "FROM workspaces" in q:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [{
                    "plan": "cloud",
                    "paddle_subscription_id_encrypted": SUB_ENC,
                    "cancel_at_period_end": False,
                }]
            else:
                return [_ws_row(plan="cloud", cancel_at_period_end=True)]
        return []

    mock_query = AsyncMock(side_effect=_query_side)
    mock_insert = AsyncMock(return_value="UPDATE 1")

    mock_paddle_resp = MagicMock()
    mock_paddle_resp.status_code = 200
    mock_paddle_resp.json.return_value = {"data": {}}

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.post = AsyncMock(return_value=mock_paddle_resp)

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.execute_insert", mock_insert), \
         patch("burnlens_cloud.billing.httpx.AsyncClient", return_value=mock_http_client), \
         patch("burnlens_cloud.billing._ws_pii_value", return_value="sub_real_id"):
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/cancel",
                json={"reason_code": "too_expensive", "reason_text": "Just too costly"},
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200
    # cancel_at_period_end = true update
    cancel_updates = [
        c for c in mock_insert.call_args_list
        if "cancel_at_period_end = true" in c.args[0]
    ]
    assert len(cancel_updates) == 1

    # survey INSERT
    survey_inserts = [
        c for c in mock_insert.call_args_list
        if "cancellation_surveys" in c.args[0]
    ]
    assert len(survey_inserts) == 1
    assert survey_inserts[0].args[2] == "too_expensive"
    assert "Just too costly" in survey_inserts[0].args[3]


@pytest.mark.asyncio
async def test_cancel_happy_path_no_survey(app_client):
    """Cancel with empty body — no survey INSERT should fire."""
    token = _encode_test_jwt(WS_A, "cloud")
    call_count = {"n": 0}

    async def _query_side(q, *args):
        if "FROM workspaces" in q:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [{
                    "plan": "cloud",
                    "paddle_subscription_id_encrypted": SUB_ENC,
                    "cancel_at_period_end": False,
                }]
            else:
                return [_ws_row(plan="cloud", cancel_at_period_end=True)]
        return []

    mock_query = AsyncMock(side_effect=_query_side)
    mock_insert = AsyncMock(return_value="UPDATE 1")

    mock_paddle_resp = MagicMock()
    mock_paddle_resp.status_code = 200
    mock_paddle_resp.json.return_value = {"data": {}}

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.post = AsyncMock(return_value=mock_paddle_resp)

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.execute_insert", mock_insert), \
         patch("burnlens_cloud.billing.httpx.AsyncClient", return_value=mock_http_client), \
         patch("burnlens_cloud.billing._ws_pii_value", return_value="sub_real_id"):
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/cancel",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200
    survey_inserts = [
        c for c in mock_insert.call_args_list
        if "cancellation_surveys" in c.args[0]
    ]
    assert len(survey_inserts) == 0


@pytest.mark.asyncio
async def test_cancel_paddle_5xx_returns_502(app_client):
    """Paddle 5xx on cancel → 502; no DB mutation."""
    token = _encode_test_jwt(WS_A, "cloud")

    mock_query = AsyncMock(return_value=[{
        "plan": "cloud",
        "paddle_subscription_id_encrypted": SUB_ENC,
        "cancel_at_period_end": False,
    }])
    mock_insert = AsyncMock(return_value="UPDATE 1")

    mock_paddle_resp = MagicMock()
    mock_paddle_resp.status_code = 500
    mock_paddle_resp.text = "Internal Server Error"

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.post = AsyncMock(return_value=mock_paddle_resp)

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.execute_insert", mock_insert), \
         patch("burnlens_cloud.billing.httpx.AsyncClient", return_value=mock_http_client), \
         patch("burnlens_cloud.billing._ws_pii_value", return_value="sub_real_id"):
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/cancel",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 502
    mock_insert.assert_not_called()


# ===========================================================================
# 4. POST /billing/reactivate
# ===========================================================================

@pytest.mark.asyncio
async def test_reactivate_401_unauth(app_client):
    async with await app_client() as ac:
        resp = await ac.post("/billing/reactivate")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_reactivate_idempotent_not_scheduled(app_client):
    """cancel_at_period_end is False → nothing scheduled; return summary, no Paddle call."""
    token = _encode_test_jwt(WS_A, "cloud")

    # reactivate reads: plan + paddle_subscription_id_encrypted + cancel_at_period_end
    #                   + current_period_ends_at + subscription_status
    # _load_billing_summary reads: plan + price_cents + currency + ...
    call_count = {"n": 0}

    async def _query_side(q, *args):
        if "FROM workspaces" in q:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [{
                    "plan": "cloud",
                    "paddle_subscription_id_encrypted": None,
                    "cancel_at_period_end": False,
                    "current_period_ends_at": None,
                    "subscription_status": "active",
                }]
            else:
                return [_ws_row(plan="cloud")]
        return []

    mock_query = AsyncMock(side_effect=_query_side)

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.execute_insert", AsyncMock()), \
         patch("burnlens_cloud.billing.httpx.AsyncClient") as mock_http:
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/reactivate",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200
    mock_http.assert_not_called()


@pytest.mark.asyncio
async def test_reactivate_400_period_ended(app_client):
    """Period already ended → 400; user must re-checkout."""
    token = _encode_test_jwt(WS_A, "cloud")
    past = datetime.now(timezone.utc) - timedelta(days=1)

    mock_query = AsyncMock(return_value=[{
        "plan": "cloud",
        "paddle_subscription_id_encrypted": SUB_ENC,
        "cancel_at_period_end": True,
        "current_period_ends_at": past,
        "subscription_status": "active",
    }])

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing._ws_pii_value", return_value="sub_real_id"):
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/reactivate",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 400
    assert "checkout" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reactivate_400_status_canceled(app_client):
    """subscription_status='canceled' → 400 even if period not yet ended."""
    token = _encode_test_jwt(WS_A, "cloud")
    future = datetime.now(timezone.utc) + timedelta(days=5)

    mock_query = AsyncMock(return_value=[{
        "plan": "cloud",
        "paddle_subscription_id_encrypted": SUB_ENC,
        "cancel_at_period_end": True,
        "current_period_ends_at": future,
        "subscription_status": "canceled",
    }])

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing._ws_pii_value", return_value="sub_real_id"):
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/reactivate",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_reactivate_happy_path(app_client):
    """Successful reactivate: Paddle PATCH called, cancel_at_period_end=false written."""
    token = _encode_test_jwt(WS_A, "cloud")
    future = datetime.now(timezone.utc) + timedelta(days=10)
    call_count = {"n": 0}

    async def _query_side(q, *args):
        if "FROM workspaces" in q:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [{
                    "plan": "cloud",
                    "paddle_subscription_id_encrypted": SUB_ENC,
                    "cancel_at_period_end": True,
                    "current_period_ends_at": future,
                    "subscription_status": "active",
                }]
            else:
                return [_ws_row(plan="cloud", cancel_at_period_end=False,
                                current_period_ends_at=future)]
        return []

    mock_query = AsyncMock(side_effect=_query_side)
    mock_insert = AsyncMock(return_value="UPDATE 1")

    mock_paddle_resp = MagicMock()
    mock_paddle_resp.status_code = 200
    mock_paddle_resp.json.return_value = {"data": {}}

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.patch = AsyncMock(return_value=mock_paddle_resp)

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.execute_insert", mock_insert), \
         patch("burnlens_cloud.billing.httpx.AsyncClient", return_value=mock_http_client), \
         patch("burnlens_cloud.billing._ws_pii_value", return_value="sub_real_id"):
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/reactivate",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200
    # Paddle PATCH called with scheduled_change=null
    mock_http_client.patch.assert_called_once()
    patch_payload = mock_http_client.patch.call_args.kwargs.get("json") or {}
    assert patch_payload.get("scheduled_change") is None

    # DB flip cancel_at_period_end=false
    reactivate_updates = [
        c for c in mock_insert.call_args_list
        if "cancel_at_period_end = false" in c.args[0]
    ]
    assert len(reactivate_updates) == 1


@pytest.mark.asyncio
async def test_reactivate_paddle_5xx_returns_502(app_client):
    """Paddle 5xx on reactivate → 502; no DB mutation."""
    token = _encode_test_jwt(WS_A, "cloud")
    future = datetime.now(timezone.utc) + timedelta(days=10)

    mock_query = AsyncMock(return_value=[{
        "plan": "cloud",
        "paddle_subscription_id_encrypted": SUB_ENC,
        "cancel_at_period_end": True,
        "current_period_ends_at": future,
        "subscription_status": "active",
    }])
    mock_insert = AsyncMock(return_value="UPDATE 1")

    mock_paddle_resp = MagicMock()
    mock_paddle_resp.status_code = 500
    mock_paddle_resp.text = "Server error"

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.patch = AsyncMock(return_value=mock_paddle_resp)

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.execute_insert", mock_insert), \
         patch("burnlens_cloud.billing.httpx.AsyncClient", return_value=mock_http_client), \
         patch("burnlens_cloud.billing._ws_pii_value", return_value="sub_real_id"):
        async with await app_client() as ac:
            resp = await ac.post(
                "/billing/reactivate",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 502
    mock_insert.assert_not_called()


# ===========================================================================
# 5. GET /billing/invoices
# ===========================================================================

@pytest.mark.asyncio
async def test_invoices_401_unauth(app_client):
    async with await app_client() as ac:
        resp = await ac.get("/billing/invoices")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_invoices_free_workspace_empty_list(app_client):
    """Free workspace (no customer_id) → empty invoices list, no Paddle call."""
    token = _encode_test_jwt(WS_A, "free")

    mock_query = AsyncMock(return_value=[{
        "paddle_customer_id_encrypted": None,
    }])

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing._ws_pii_value", return_value=None), \
         patch("burnlens_cloud.billing.httpx.AsyncClient") as mock_http:
        async with await app_client() as ac:
            resp = await ac.get(
                "/billing/invoices",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200
    assert resp.json() == {"invoices": []}
    mock_http.assert_not_called()


@pytest.mark.asyncio
async def test_invoices_pdf_fail_soft(app_client):
    """PDF fetch failure → invoice row still returned with invoice_pdf_url=None."""
    token = _encode_test_jwt(WS_A, "cloud")

    mock_query = AsyncMock(return_value=[{
        "paddle_customer_id_encrypted": CUST_ENC,
    }])

    # Paddle list transactions response — one invoice
    txn_data = [{
        "id": "txn_001",
        "status": "paid",
        "billed_at": "2026-04-01T12:00:00Z",
        "details": {"totals": {"grand_total": "2900", "currency_code": "USD"}},
    }]

    mock_list_resp = MagicMock()
    mock_list_resp.status_code = 200
    mock_list_resp.json.return_value = {"data": txn_data}

    import httpx as _httpx

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    # List call succeeds; PDF call raises timeout
    mock_http_client.get = AsyncMock(side_effect=[
        mock_list_resp,
        _httpx.TimeoutException("pdf timeout"),
    ])

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.httpx.AsyncClient", return_value=mock_http_client), \
         patch("burnlens_cloud.billing._ws_pii_value", return_value="ctm_real_id"):
        async with await app_client() as ac:
            resp = await ac.get(
                "/billing/invoices",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200
    invoices = resp.json()["invoices"]
    assert len(invoices) == 1
    assert invoices[0]["id"] == "txn_001"
    assert invoices[0]["invoice_pdf_url"] is None   # fail-soft
    assert invoices[0]["amount_cents"] == 2900


@pytest.mark.asyncio
async def test_invoices_paddle_5xx_returns_502(app_client):
    """Paddle 5xx on transactions list → 502."""
    token = _encode_test_jwt(WS_A, "cloud")

    mock_query = AsyncMock(return_value=[{
        "paddle_customer_id_encrypted": CUST_ENC,
    }])

    mock_list_resp = MagicMock()
    mock_list_resp.status_code = 503
    mock_list_resp.text = "Service Unavailable"

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.get = AsyncMock(return_value=mock_list_resp)

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.httpx.AsyncClient", return_value=mock_http_client), \
         patch("burnlens_cloud.billing._ws_pii_value", return_value="ctm_real_id"):
        async with await app_client() as ac:
            resp = await ac.get(
                "/billing/invoices",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 502


# ===========================================================================
# 6. GET /billing/plans
# ===========================================================================

@pytest.mark.asyncio
async def test_plans_401_unauth(app_client):
    async with await app_client() as ac:
        resp = await ac.get("/billing/plans")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_plans_returns_cloud_and_teams(app_client):
    """Returns cloud + teams rows in order."""
    token = _encode_test_jwt(WS_A, "cloud")

    plan_rows = [
        {
            "plan": "cloud",
            "monthly_request_cap": 1_000_000,
            "seat_count": 1,
            "retention_days": 30,
            "api_key_count": 3,
            "paddle_price_id": "pri_cloud",
            "paddle_product_id": "pro_cloud",
            "gated_features": {},
        },
        {
            "plan": "teams",
            "monthly_request_cap": 5_000_000,
            "seat_count": 10,
            "retention_days": 90,
            "api_key_count": 20,
            "paddle_price_id": "pri_teams",
            "paddle_product_id": "pro_teams",
            "gated_features": {"sso": True},
        },
    ]

    mock_query = AsyncMock(return_value=plan_rows)

    with patch("burnlens_cloud.billing.execute_query", mock_query):
        async with await app_client() as ac:
            resp = await ac.get(
                "/billing/plans",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert "plans" in body
    plans = body["plans"]
    assert len(plans) == 2
    assert plans[0]["plan"] == "cloud"
    assert plans[1]["plan"] == "teams"
    assert plans[0]["monthly_request_cap"] == 1_000_000
    assert plans[1]["seat_count"] == 10
    assert plans[1]["gated_features"] == {"sso": True}


@pytest.mark.asyncio
async def test_plans_empty_returns_empty_list(app_client):
    """Empty plan_limits → {"plans": []}."""
    token = _encode_test_jwt(WS_A, "cloud")

    mock_query = AsyncMock(return_value=[])

    with patch("burnlens_cloud.billing.execute_query", mock_query):
        async with await app_client() as ac:
            resp = await ac.get(
                "/billing/plans",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200
    assert resp.json() == {"plans": []}


@pytest.mark.asyncio
async def test_plans_gated_features_str_jsonb(app_client):
    """gated_features as a JSON string (asyncpg without JSONB codec) is parsed to dict."""
    token = _encode_test_jwt(WS_A, "cloud")

    plan_rows = [
        {
            "plan": "cloud",
            "monthly_request_cap": 1_000_000,
            "seat_count": 1,
            "retention_days": 30,
            "api_key_count": 3,
            "paddle_price_id": "pri_cloud",
            "paddle_product_id": "pro_cloud",
            "gated_features": '{"sso": false}',   # string, not dict
        },
    ]

    mock_query = AsyncMock(return_value=plan_rows)

    with patch("burnlens_cloud.billing.execute_query", mock_query):
        async with await app_client() as ac:
            resp = await ac.get(
                "/billing/plans",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200
    plan = resp.json()["plans"][0]
    # Implementation normalises the JSON string to a dict
    assert isinstance(plan["gated_features"], dict)
    assert plan["gated_features"]["sso"] is False
