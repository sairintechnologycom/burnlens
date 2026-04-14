"""Tests for billing endpoints."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


WS_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.mark.asyncio
async def test_checkout_creates_stripe_session(authed_client):
    ac, mock_conn, token, ws_id = authed_client
    # authed_client has plan='cloud', so use a free workspace for checkout
    mock_conn.fetchrow.return_value = {
        "id": ws_id,
        "name": "Test WS",
        "plan": "free",
        "active": True,
    }
    mock_conn.fetchval.return_value = "user@example.com"

    mock_session = MagicMock()
    mock_session.url = "https://checkout.stripe.com/test_session"

    with patch("stripe.checkout.Session.create", return_value=mock_session) as mock_create:
        resp = await ac.post(
            "/billing/checkout",
            json={"plan": "cloud"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["checkout_url"] == "https://checkout.stripe.com/test_session"
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args[1]
    assert call_kwargs["mode"] == "subscription"
    assert call_kwargs["metadata"]["workspace_id"] == ws_id


@pytest.mark.asyncio
async def test_checkout_rejects_same_plan(authed_client):
    ac, mock_conn, token, ws_id = authed_client
    # authed_client defaults to plan='cloud'
    mock_conn.fetchrow.return_value = {
        "id": ws_id,
        "name": "Test WS",
        "plan": "cloud",
        "active": True,
    }

    resp = await ac.post(
        "/billing/checkout",
        json={"plan": "cloud"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 400
    assert "already_on_plan" in resp.text


@pytest.mark.asyncio
async def test_webhook_checkout_completed_upgrades_plan(client):
    ac, mock_conn = client

    event_payload = {
        "id": "evt_test",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "customer": "cus_test_abc",
                "metadata": {"workspace_id": WS_ID},
            }
        },
    }

    mock_line_items = {"data": [{"price": {"id": "price_cloud_test"}}]}

    with patch("stripe.Webhook.construct_event", return_value=event_payload):
        with patch("stripe.checkout.Session.list_line_items", return_value=mock_line_items):
            with patch("api.billing.config.STRIPE_CLOUD_PRICE_ID", "price_cloud_test"):
                # Clear cached mapping so it rebuilds
                import api.billing
                api.billing._PRICE_TO_PLAN.clear()

                resp = await ac.post(
                    "/billing/webhook",
                    content=b'{"test": true}',
                    headers={"stripe-signature": "test_sig"},
                )

    assert resp.status_code == 200
    # Verify UPDATE was called with correct args
    mock_conn.execute.assert_called_once()
    call_args = mock_conn.execute.call_args[0]
    assert "UPDATE workspaces SET plan" in call_args[0]
    assert call_args[1] == "cloud"
    assert call_args[2] == "cus_test_abc"
    assert call_args[3] == WS_ID


@pytest.mark.asyncio
async def test_webhook_subscription_deleted_downgrades_to_free(client):
    ac, mock_conn = client

    event_payload = {
        "id": "evt_test",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_test",
                "customer": "cus_test_abc",
            }
        },
    }

    with patch("stripe.Webhook.construct_event", return_value=event_payload):
        resp = await ac.post(
            "/billing/webhook",
            content=b'{"test": true}',
            headers={"stripe-signature": "test_sig"},
        )

    assert resp.status_code == 200
    mock_conn.execute.assert_called_once()
    call_args = mock_conn.execute.call_args[0]
    assert "plan = 'free'" in call_args[0]
    assert call_args[1] == "cus_test_abc"


@pytest.mark.asyncio
async def test_webhook_invalid_signature_400(client):
    ac, mock_conn = client

    import stripe as stripe_mod

    with patch(
        "stripe.Webhook.construct_event",
        side_effect=stripe_mod.SignatureVerificationError("bad", "sig"),
    ):
        resp = await ac.post(
            "/billing/webhook",
            content=b'{"bad": true}',
            headers={"stripe-signature": "bad_sig"},
        )

    assert resp.status_code == 400
    assert "Invalid signature" in resp.text


@pytest.mark.asyncio
async def test_portal_requires_stripe_customer_id(authed_client):
    ac, mock_conn, token, ws_id = authed_client
    # fetchrow for get_current_workspace, then fetchval returns None (no customer)
    mock_conn.fetchval.return_value = None

    resp = await ac.get(
        "/billing/portal",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 400
    assert "no_billing_history" in resp.text


@pytest.mark.asyncio
async def test_free_tier_limit_enforced_at_10k(client):
    ac, mock_conn = client

    # Setup: _lookup_workspace returns free plan
    mock_conn.fetchrow.return_value = {
        "id": WS_ID,
        "plan": "free",
        "active": True,
    }
    # fetchval for COUNT(*) returns 10000
    mock_conn.fetchval.return_value = 10000

    # Clear the ingest key cache
    import api.ingest
    api.ingest._key_cache.clear()

    resp = await ac.post(
        "/api/v1/ingest",
        json={
            "api_key": "bl_live_testkey123",
            "records": [
                {
                    "ts": "2026-04-14T12:00:00Z",
                    "provider": "openai",
                    "model": "gpt-4o",
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cost_usd": 0.01,
                }
            ],
        },
    )

    assert resp.status_code == 429
    data = resp.json()
    assert data["detail"]["error"] == "free_tier_limit"
    assert data["detail"]["count"] == 10000
    assert data["detail"]["limit"] == 10000
