"""Tests for enterprise OTEL endpoints and forwarder."""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["DATABASE_URL"] = "postgresql://localhost:5432/burnlens_test"
os.environ["JWT_SECRET"] = "test-secret-key-for-unit-tests"
os.environ["ENVIRONMENT"] = "test"

# Generate a real Fernet key for encryption tests
from cryptography.fernet import Fernet

_TEST_KEY = Fernet.generate_key().decode()
os.environ["OTEL_ENCRYPTION_KEY"] = _TEST_KEY

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from api.auth import _encode_jwt


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _mock_pool():
    """Return (mock_pool, mock_conn) pair."""
    mock_conn = AsyncMock()
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_pool, mock_conn


@pytest_asyncio.fixture
async def enterprise_client():
    """Test client with enterprise-plan owner JWT."""
    mock_pool, mock_conn = _mock_pool()

    with patch("api.database.init_db", new_callable=AsyncMock):
        with patch("api.database.close_db", new_callable=AsyncMock):
            from api.main import app
            import api.database as db_mod
            db_mod.pool = mock_pool

            # Also patch pool reference in ingest module
            import api.ingest as ingest_mod
            ingest_mod._key_cache.clear()

            ws_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            user_id = "11111111-2222-3333-4444-555555555555"
            token = _encode_jwt(ws_id, "enterprise", user_id=user_id, role="owner")

            # Mock workspace lookup for get_current_workspace
            mock_conn.fetchrow.return_value = {
                "id": ws_id,
                "name": "Enterprise WS",
                "plan": "enterprise",
                "active": True,
            }

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac, mock_conn, token, ws_id


@pytest_asyncio.fixture
async def cloud_client():
    """Test client with cloud-plan owner JWT (non-enterprise)."""
    mock_pool, mock_conn = _mock_pool()

    with patch("api.database.init_db", new_callable=AsyncMock):
        with patch("api.database.close_db", new_callable=AsyncMock):
            from api.main import app
            import api.database as db_mod
            db_mod.pool = mock_pool

            ws_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            user_id = "11111111-2222-3333-4444-555555555555"
            token = _encode_jwt(ws_id, "cloud", user_id=user_id, role="owner")

            mock_conn.fetchrow.return_value = {
                "id": ws_id,
                "name": "Cloud WS",
                "plan": "cloud",
                "active": True,
            }

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac, mock_conn, token, ws_id


# ---------------------------------------------------------------------------
# test_otel_config_requires_enterprise_plan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_otel_config_requires_enterprise_plan(cloud_client):
    """PUT /settings/otel returns 403 for non-enterprise plans."""
    ac, mock_conn, token, ws_id = cloud_client
    resp = await ac.put(
        "/settings/otel",
        json={"endpoint": "https://otel.example.com", "api_key": "secret", "enabled": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    data = resp.json()
    assert data["detail"]["error"] == "enterprise_plan_required"
    assert "mailto:" in data["detail"]["upgrade_url"]


# ---------------------------------------------------------------------------
# test_otel_config_encrypts_api_key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_otel_config_encrypts_api_key(enterprise_client):
    """PUT /settings/otel encrypts the api_key before storing in DB."""
    ac, mock_conn, token, ws_id = enterprise_client

    # Mock the forwarder test to succeed
    with patch("api.enterprise.get_forwarder") as mock_fwd:
        mock_fwd.return_value.send_test_span = AsyncMock(return_value=(True, 100, ""))
        mock_conn.execute = AsyncMock()

        resp = await ac.put(
            "/settings/otel",
            json={
                "endpoint": "https://otel.example.com",
                "api_key": "my-secret-key-12345",
                "enabled": True,
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "connected"
    assert resp.json()["test_span_sent"] is True

    # Find the UPDATE call that stores the encrypted key
    update_calls = [
        c for c in mock_conn.execute.call_args_list
        if "otel_api_key_encrypted" in str(c)
    ]
    assert len(update_calls) >= 1

    # The stored value must NOT be plaintext
    stored_key = update_calls[0].args[2]  # $2 = encrypted key
    assert stored_key != "my-secret-key-12345"
    assert len(stored_key) > 20  # Fernet ciphertext is long

    # Verify we can decrypt it back
    from api.crypto import decrypt
    assert decrypt(stored_key) == "my-secret-key-12345"


# ---------------------------------------------------------------------------
# test_otel_config_masked_in_get_response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_otel_config_masked_in_get_response(enterprise_client):
    """GET /settings/otel returns masked api_key (****...xxxx)."""
    ac, mock_conn, token, ws_id = enterprise_client

    from api.crypto import encrypt

    encrypted = encrypt("my-secret-api-key-ABCD")
    mock_conn.fetchrow.side_effect = [
        # First call: get_current_workspace
        {"id": ws_id, "name": "Enterprise WS", "plan": "enterprise", "active": True},
        # Second call: get OTEL config
        {
            "otel_endpoint": "https://otel.example.com",
            "otel_api_key_encrypted": encrypted,
            "otel_enabled": True,
            "otel_last_push": None,
        },
    ]

    resp = await ac.get(
        "/settings/otel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["endpoint"] == "https://otel.example.com"
    assert data["enabled"] is True
    # Key must be masked: ****...ABCD
    assert "****" in data["api_key_masked"]
    assert data["api_key_masked"].endswith("ABCD")
    # Full key must NOT appear
    assert "my-secret-api-key" not in data["api_key_masked"]


# ---------------------------------------------------------------------------
# test_otel_test_span_calls_endpoint (mock httpx)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_otel_test_span_calls_endpoint(enterprise_client):
    """POST /settings/otel/test sends a test span to the configured endpoint."""
    ac, mock_conn, token, ws_id = enterprise_client

    from api.crypto import encrypt

    encrypted = encrypt("test-key")

    mock_conn.fetchrow.side_effect = [
        # get_current_workspace
        {"id": ws_id, "name": "Enterprise WS", "plan": "enterprise", "active": True},
        # fetch OTEL config
        {"otel_endpoint": "https://otel.example.com", "otel_api_key_encrypted": encrypted},
    ]

    with patch("api.telemetry.forwarder.httpx.AsyncClient") as mock_httpx:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.return_value = mock_client_instance

        resp = await ac.post(
            "/settings/otel/test",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "latency_ms" in data

    # Verify httpx was called with the right URL
    call_args = mock_client_instance.post.call_args
    assert "/v1/traces" in call_args.args[0]


# ---------------------------------------------------------------------------
# test_forwarder_builds_correct_otlp_payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forwarder_builds_correct_otlp_payload():
    """OtelForwarder builds proper OTLP JSON with typed attributes."""
    from api.telemetry.forwarder import OtelForwarder

    records = [
        {
            "ts": "2025-01-15T10:30:00Z",
            "provider": "openai",
            "model": "gpt-4o-mini",
            "input_tokens": 100,
            "output_tokens": 50,
            "reasoning_tokens": 0,
            "cost_usd": 0.000045,
            "latency_ms": 320,
            "status_code": 200,
            "tag_feature": "chat",
            "tag_team": "backend",
            "tag_customer": "acme",
        }
    ]

    captured_payload = {}

    async def _mock_post(url, json=None, headers=None):
        captured_payload.update(json)
        resp = MagicMock()
        resp.status_code = 200
        return resp

    with patch("api.telemetry.forwarder.httpx.AsyncClient") as mock_httpx:
        mock_client = AsyncMock()
        mock_client.post = _mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.return_value = mock_client

        forwarder = OtelForwarder()
        ok, err = await forwarder.forward_batch(
            records, "https://otel.example.com", "key123", workspace_id="ws-abc"
        )

    assert ok is True
    assert err == ""

    # Validate structure
    rs = captured_payload["resourceSpans"]
    assert len(rs) == 1

    # Resource attributes
    res_attrs = {a["key"]: a["value"] for a in rs[0]["resource"]["attributes"]}
    assert res_attrs["service.name"] == {"stringValue": "burnlens"}
    assert res_attrs["workspace.id"] == {"stringValue": "ws-abc"}

    # Scope
    scope_spans = rs[0]["scopeSpans"]
    assert scope_spans[0]["scope"]["name"] == "burnlens.cost"

    # Span
    span = scope_spans[0]["spans"][0]
    assert span["name"] == "llm.request"
    assert span["status"]["code"] == 1

    # Typed attributes
    attrs = {a["key"]: a["value"] for a in span["attributes"]}
    assert attrs["llm.provider"] == {"stringValue": "openai"}
    assert attrs["llm.model"] == {"stringValue": "gpt-4o-mini"}
    assert attrs["llm.tokens.input"] == {"intValue": "100"}
    assert attrs["llm.tokens.output"] == {"intValue": "50"}
    assert attrs["llm.cost.usd"] == {"doubleValue": 0.000045}
    assert attrs["llm.latency_ms"] == {"intValue": "320"}
    assert attrs["http.status_code"] == {"intValue": "200"}
    assert attrs["burnlens.feature"] == {"stringValue": "chat"}
    assert attrs["burnlens.team"] == {"stringValue": "backend"}
    assert attrs["burnlens.customer"] == {"stringValue": "acme"}


# ---------------------------------------------------------------------------
# test_forwarder_failure_does_not_crash_ingest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forwarder_failure_does_not_crash_ingest():
    """forward_batch returns (False, msg) on error — never raises."""
    from api.telemetry.forwarder import OtelForwarder

    with patch("api.telemetry.forwarder.httpx.AsyncClient") as mock_httpx:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=ConnectionError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.return_value = mock_client

        forwarder = OtelForwarder()
        ok, err = await forwarder.forward_batch(
            [{"ts": "2025-01-01T00:00:00Z", "provider": "openai", "model": "gpt-4o"}],
            "https://otel.example.com",
            "key",
        )

    assert ok is False
    assert "ConnectionError" in err


# ---------------------------------------------------------------------------
# test_forward_triggered_after_ingest (mock forwarder)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forward_triggered_after_ingest(enterprise_client):
    """Ingest queues an OTEL forward when workspace has otel_enabled=True."""
    ac, mock_conn, token, ws_id = enterprise_client

    from api.crypto import encrypt

    encrypted_key = encrypt("otel-api-key")

    # Mock _lookup_workspace to return enterprise workspace
    with patch("api.ingest._lookup_workspace", new_callable=AsyncMock) as mock_lookup:
        mock_lookup.return_value = (ws_id, "enterprise")

        # Mock OTEL config query
        mock_conn.fetchrow.return_value = {
            "otel_endpoint": "https://otel.example.com",
            "otel_api_key_encrypted": encrypted_key,
            "otel_enabled": True,
        }
        mock_conn.executemany = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=0)
        mock_conn.execute = AsyncMock()

        with patch("api.ingest.get_forwarder") as mock_fwd_fn:
            mock_forwarder = AsyncMock()
            mock_forwarder.forward_batch = AsyncMock(return_value=(True, ""))
            mock_fwd_fn.return_value = mock_forwarder

            resp = await ac.post(
                "/api/v1/ingest",
                json={
                    "api_key": "bl_live_" + "a" * 64,
                    "records": [
                        {
                            "ts": "2025-01-15T10:30:00Z",
                            "provider": "openai",
                            "model": "gpt-4o",
                            "input_tokens": 100,
                            "output_tokens": 50,
                            "cost_usd": 0.001,
                            "latency_ms": 200,
                        }
                    ],
                },
            )

            assert resp.status_code == 200
            assert resp.json()["accepted"] == 1

            # Give the background task time to fire
            import asyncio
            await asyncio.sleep(0.1)

            mock_forwarder.forward_batch.assert_called_once()
            call_args = mock_forwarder.forward_batch.call_args
            assert call_args.args[1] == "https://otel.example.com"


# ---------------------------------------------------------------------------
# test_encryption_roundtrip
# ---------------------------------------------------------------------------


def test_encryption_roundtrip():
    """encrypt → decrypt returns original plaintext."""
    from api.crypto import encrypt, decrypt, mask_api_key

    original = "sk-abc123-very-secret-key"
    ciphertext = encrypt(original)
    assert ciphertext != original
    assert len(ciphertext) > len(original)

    plaintext = decrypt(ciphertext)
    assert plaintext == original

    # Test masking
    masked = mask_api_key(original)
    assert masked == "****...-key"
    assert original not in masked
