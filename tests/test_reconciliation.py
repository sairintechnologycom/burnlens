"""Economics-graph Phase E: reconciliation against provider billing APIs.

Three things are worth guarding here:

* The **unit trap.** Anthropic's cost report returns minor units ("123.45" USD
  is $1.23); OpenAI returns dollars. Reading either wrong makes every workspace
  look 100x under- or over-counted, silently.
* The **drift math**, including the divide-by-zero case, which is a real state
  (a provider that billed nothing) and not an error.
* The **alert gate**, which is the whole point of the phase — a number nobody
  is told about is not a trust feature.
"""
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from burnlens_cloud.reconciliation import (
    DRIFT_ALERT_THRESHOLD_PCT,
    ProviderCostError,
    _anthropic_day_cost,
    _openai_day_cost,
    classify,
    compute_drift_pct,
    reconcile_all_workspaces,
)

DAY = date(2026, 8, 9)


@pytest_asyncio.fixture
async def recon_client():
    from burnlens_cloud.reconciliation import router

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        yield ac


@pytest.fixture
def owner_token():
    from burnlens_cloud.auth import encode_jwt

    return encode_jwt(str(uuid4()), str(uuid4()), "owner", "cloud")


# ------------------------------------------------------------------ drift math


def test_drift_is_signed_relative_to_the_provider():
    # BurnLens counted less than the bill — the normal direction.
    assert compute_drift_pct(100.0, 98.0) == pytest.approx(-2.0)
    assert compute_drift_pct(100.0, 103.0) == pytest.approx(3.0)


def test_drift_is_none_when_the_provider_billed_nothing():
    assert compute_drift_pct(0.0, 5.0) is None
    assert compute_drift_pct(0.0, 0.0) is None


def test_classify_treats_unmeasurable_drift_with_spend_as_drifted():
    # Provider billed nothing but we recorded spend: real disagreement, no
    # percentage to express it with.
    assert classify(None, 5.0) == "drifted"
    assert classify(None, 0.0) == "reconciled"


def test_classify_uses_the_threshold_symmetrically():
    assert classify(DRIFT_ALERT_THRESHOLD_PCT, 10.0) == "reconciled"
    assert classify(-DRIFT_ALERT_THRESHOLD_PCT, 10.0) == "reconciled"
    assert classify(DRIFT_ALERT_THRESHOLD_PCT + 0.1, 10.0) == "drifted"
    assert classify(-(DRIFT_ALERT_THRESHOLD_PCT + 0.1), 10.0) == "drifted"


# ------------------------------------------------------------ provider parsers


@respx.mock
@pytest.mark.asyncio
async def test_anthropic_amounts_are_minor_units():
    respx.get("https://api.anthropic.com/v1/organizations/cost_report").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "starting_at": "2026-08-09T00:00:00Z",
                        "ending_at": "2026-08-10T00:00:00Z",
                        "results": [
                            {"amount": "12345", "currency": "USD"},
                            {"amount": "55", "currency": "USD"},
                        ],
                    }
                ],
                "has_more": False,
                "next_page": None,
            },
        )
    )
    # 12345 + 55 cents = $124.00, not $12400.
    assert await _anthropic_day_cost("sk-ant-admin-x", DAY) == pytest.approx(124.00)


@respx.mock
@pytest.mark.asyncio
async def test_anthropic_admin_key_uses_x_api_key_header():
    route = respx.get("https://api.anthropic.com/v1/organizations/cost_report").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False})
    )
    await _anthropic_day_cost("sk-ant-admin-x", DAY)
    req = route.calls[0].request
    assert req.headers["x-api-key"] == "sk-ant-admin-x"
    assert "authorization" not in req.headers
    assert req.url.params["starting_at"] == "2026-08-09T00:00:00Z"
    assert req.url.params["ending_at"] == "2026-08-10T00:00:00Z"


@respx.mock
@pytest.mark.asyncio
async def test_anthropic_oauth_token_uses_bearer_header():
    route = respx.get("https://api.anthropic.com/v1/organizations/cost_report").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False})
    )
    await _anthropic_day_cost("oat-token", DAY)
    assert route.calls[0].request.headers["authorization"] == "Bearer oat-token"


@respx.mock
@pytest.mark.asyncio
async def test_anthropic_error_response_raises():
    respx.get("https://api.anthropic.com/v1/organizations/cost_report").mock(
        return_value=httpx.Response(401, text="invalid x-api-key")
    )
    with pytest.raises(ProviderCostError):
        await _anthropic_day_cost("sk-ant-bad", DAY)


@respx.mock
@pytest.mark.asyncio
async def test_openai_amounts_are_dollars():
    respx.get("https://api.openai.com/v1/organization/costs").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "object": "bucket",
                        "results": [
                            {"amount": {"value": 0.13, "currency": "usd"}},
                            {"amount": {"value": 1.87, "currency": "usd"}},
                        ],
                    }
                ],
                "has_more": False,
            },
        )
    )
    assert await _openai_day_cost("sk-admin", DAY) == pytest.approx(2.00)


@respx.mock
@pytest.mark.asyncio
async def test_openai_window_is_one_utc_day():
    route = respx.get("https://api.openai.com/v1/organization/costs").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False})
    )
    await _openai_day_cost("sk-admin", DAY)
    params = route.calls[0].request.url.params
    start = int(params["start_time"])
    assert datetime.fromtimestamp(start, tz=timezone.utc) == datetime(
        2026, 8, 9, tzinfo=timezone.utc
    )
    assert int(params["end_time"]) - start == 86_400


@respx.mock
@pytest.mark.asyncio
async def test_pagination_is_followed():
    route = respx.get("https://api.openai.com/v1/organization/costs")
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "data": [{"results": [{"amount": {"value": 1.0}}]}],
                "has_more": True,
                "next_page": "p2",
            },
        ),
        httpx.Response(
            200,
            json={"data": [{"results": [{"amount": {"value": 2.0}}]}], "has_more": False},
        ),
    ]
    assert await _openai_day_cost("sk-admin", DAY) == pytest.approx(3.0)
    assert route.calls[1].request.url.params["page"] == "p2"


# --------------------------------------------------------------- the daily job


class _FakeManager:
    def decrypt(self, ciphertext):
        return "plaintext-key"

    def encrypt(self, plaintext):
        return "encrypted"


def _run_with(provider_cost, burnlens_cost):
    """Run the daily job for one credential, returning (result, calls, alert mock)."""
    workspace_id = uuid4()
    creds = [
        {
            "workspace_id": workspace_id,
            "provider": "openai",
            "api_key_encrypted": "enc",
        }
    ]
    stored: list[tuple] = []

    async def fake_execute_query(query, *args):
        if "FROM reconciliation_credentials" in query:
            return creds
        if "SUM(cost_usd)" in query:
            return [{"cost": burnlens_cost}]
        stored.append(args)
        return []

    async def fake_fetch(api_key, day):
        assert api_key == "plaintext-key"
        return provider_cost

    alert = AsyncMock()
    return workspace_id, stored, alert, fake_execute_query, fake_fetch


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_cost,burnlens_cost,should_alert",
    [
        (100.0, 99.0, False),   # 1% under — inside the threshold
        (100.0, 90.0, True),    # 10% under — non-proxied traffic, worth a look
        (100.0, 110.0, True),   # 10% over — we are charging for phantom spend
        (0.0, 5.0, True),       # provider billed nothing, we recorded spend
        (0.0, 0.0, False),      # nothing anywhere: agreement
    ],
)
async def test_alert_fires_only_past_the_threshold(
    provider_cost, burnlens_cost, should_alert
):
    _ws, stored, alert, fake_query, fake_fetch = _run_with(provider_cost, burnlens_cost)

    with patch("burnlens_cloud.reconciliation.execute_query", fake_query), \
         patch("burnlens_cloud.reconciliation.get_encryption_manager", return_value=_FakeManager()), \
         patch("burnlens_cloud.reconciliation.PROVIDERS", {"openai": fake_fetch}), \
         patch("burnlens_cloud.reconciliation.send_ops_alert", alert):
        result = await reconcile_all_workspaces(DAY)

    assert result == {"checked": 1, "failed": 0, "alerted": 1 if should_alert else 0}
    assert alert.await_count == (1 if should_alert else 0)
    # The run is always recorded, alert or not — the badge needs the number.
    assert len(stored) == 1


@pytest.mark.asyncio
async def test_one_broken_credential_does_not_stop_the_run():
    creds = [
        {"workspace_id": uuid4(), "provider": "openai", "api_key_encrypted": "bad"},
        {"workspace_id": uuid4(), "provider": "anthropic", "api_key_encrypted": "good"},
    ]
    stored: list[tuple] = []

    async def fake_execute_query(query, *args):
        if "FROM reconciliation_credentials" in query:
            return creds
        if "SUM(cost_usd)" in query:
            return [{"cost": 10.0}]
        stored.append(args)
        return []

    async def boom(api_key, day):
        raise ProviderCostError("401")

    async def ok(api_key, day):
        return 10.0

    with patch("burnlens_cloud.reconciliation.execute_query", fake_execute_query), \
         patch("burnlens_cloud.reconciliation.get_encryption_manager", return_value=_FakeManager()), \
         patch("burnlens_cloud.reconciliation.PROVIDERS", {"openai": boom, "anthropic": ok}), \
         patch("burnlens_cloud.reconciliation.send_ops_alert", AsyncMock()):
        result = await reconcile_all_workspaces(DAY)

    assert result == {"checked": 1, "failed": 1, "alerted": 0}
    assert len(stored) == 1


@pytest.mark.asyncio
async def test_no_credentials_is_a_noop():
    async def empty(query, *args):
        return []

    with patch("burnlens_cloud.reconciliation.execute_query", empty):
        assert await reconcile_all_workspaces(DAY) == {
            "checked": 0,
            "failed": 0,
            "alerted": 0,
        }


# ------------------------------------------------------------------- endpoints


@pytest.mark.asyncio
async def test_status_requires_auth(recon_client):
    assert (await recon_client.get("/api/v1/reconciliation")).status_code in (401, 403)


@pytest.mark.asyncio
async def test_unknown_provider_is_rejected_before_any_storage(recon_client, owner_token):
    with patch("burnlens_cloud.reconciliation.require_role", AsyncMock()), \
         patch("burnlens_cloud.reconciliation.execute_query", AsyncMock()) as query:
        resp = await recon_client.put(
            "/settings/reconciliation/mistral",
            json={"api_key": "whatever-key"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
    assert resp.status_code == 400
    assert "mistral" in resp.json()["detail"]
    query.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_key_the_provider_rejects_is_never_stored(recon_client, owner_token):
    async def rejects(api_key, day):
        raise ProviderCostError("openai cost API returned 401")

    with patch("burnlens_cloud.reconciliation.require_role", AsyncMock()), \
         patch("burnlens_cloud.reconciliation.get_encryption_manager", return_value=_FakeManager()), \
         patch("burnlens_cloud.reconciliation.PROVIDERS", {"openai": rejects}), \
         patch("burnlens_cloud.reconciliation.execute_query", AsyncMock()) as query:
        resp = await recon_client.put(
            "/settings/reconciliation/openai",
            json={"api_key": "sk-admin-bad"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
    assert resp.status_code == 400
    query.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_reports_unreconciled_before_the_first_run(recon_client, owner_token):
    rows = [
        {
            "provider": "openai",
            "day": None,
            "provider_cost_usd": None,
            "burnlens_cost_usd": None,
            "drift_pct": None,
            "computed_at": None,
        }
    ]
    with patch("burnlens_cloud.reconciliation.require_role", AsyncMock()), \
         patch("burnlens_cloud.reconciliation.execute_query", AsyncMock(return_value=rows)):
        resp = await recon_client.get(
            "/api/v1/reconciliation",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
    assert resp.status_code == 200
    assert resp.json() == [
        {
            "provider": "openai",
            "status": "unreconciled",
            "day": None,
            "provider_cost_usd": None,
            "burnlens_cost_usd": None,
            "drift_pct": None,
            "computed_at": None,
        }
    ]


@pytest.mark.asyncio
async def test_status_classifies_the_latest_run(recon_client, owner_token):
    rows = [
        {
            "provider": "anthropic",
            "day": DAY,
            "provider_cost_usd": 100.0,
            "burnlens_cost_usd": 85.0,
            "drift_pct": -15.0,
            "computed_at": datetime(2026, 8, 10, tzinfo=timezone.utc),
        }
    ]
    with patch("burnlens_cloud.reconciliation.require_role", AsyncMock()), \
         patch("burnlens_cloud.reconciliation.execute_query", AsyncMock(return_value=rows)):
        resp = await recon_client.get(
            "/api/v1/reconciliation",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
    body = resp.json()
    assert body[0]["status"] == "drifted"
    assert body[0]["drift_pct"] == -15.0
