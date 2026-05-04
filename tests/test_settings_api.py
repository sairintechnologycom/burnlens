"""Tests for settings API endpoints (OTEL, pricing)."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from uuid import uuid4

from burnlens_cloud.models import TokenPayload
from burnlens_cloud.auth import verify_token as _verify_token


def _auth(app, token):
    """Override the verify_token FastAPI dependency for a single test."""
    app.dependency_overrides[_verify_token] = lambda: token


def _make_db_mock():
    """Properly wired asyncpg connection mock (transaction is a sync context manager)."""
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(return_value=None)
    mock_txn = MagicMock()
    mock_txn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_txn.__aexit__ = AsyncMock(return_value=False)
    mock_conn.transaction = MagicMock(return_value=mock_txn)
    return mock_conn


@pytest.fixture
def owner_token():
    return TokenPayload(
        workspace_id=uuid4(),
        user_id=uuid4(),
        role="owner",
        plan="enterprise",
        iat=int(__import__("time").time()),
        exp=int(__import__("time").time()) + 86400,
    )


@pytest.fixture
def admin_token():
    return TokenPayload(
        workspace_id=uuid4(),
        user_id=uuid4(),
        role="admin",
        plan="enterprise",
        iat=int(__import__("time").time()),
        exp=int(__import__("time").time()) + 86400,
    )


@pytest.fixture
def non_enterprise_token():
    return TokenPayload(
        workspace_id=uuid4(),
        user_id=uuid4(),
        role="owner",
        plan="cloud",
        iat=int(__import__("time").time()),
        exp=int(__import__("time").time()) + 86400,
    )


class TestOtelConfigEndpoints:
    """Test OTEL configuration API endpoints."""

    @pytest.mark.asyncio
    async def test_put_otel_config_success(self, cloud_client, owner_token):
        """PUT /settings/otel should update config and test endpoint."""
        ac, app = cloud_client
        _auth(app, owner_token)

        mock_conn = _make_db_mock()
        mock_enc = MagicMock()
        mock_enc.encrypt.return_value = "gAAAAABencrypted..."

        with patch("burnlens_cloud.settings_api.get_forwarder") as mock_fwd_cls:
            mock_fwd = AsyncMock()
            mock_fwd.test_endpoint.return_value = (True, 150)
            mock_fwd_cls.return_value = mock_fwd

            with patch("burnlens_cloud.settings_api.get_encryption_manager", return_value=mock_enc):
                with patch("burnlens_cloud.settings_api.execute_query", AsyncMock(return_value=[])):
                    with patch("burnlens_cloud.settings_api.get_db", AsyncMock(return_value=mock_conn)):
                        response = await ac.put(
                            "/settings/otel",
                            json={
                                "endpoint": "https://otel.datadoghq.com/v1/traces",
                                "api_key": "Bearer dd_test_123",
                                "enabled": True,
                            },
                        )

                        assert response.status_code == 200
                        assert "connected" in response.json()["status"]

    @pytest.mark.asyncio
    async def test_put_otel_config_http_endpoint_rejected(self, cloud_client, owner_token):
        """PUT /settings/otel should reject non-HTTPS endpoints."""
        ac, app = cloud_client
        _auth(app, owner_token)

        response = await ac.put(
            "/settings/otel",
            json={
                "endpoint": "http://otel.example.com/v1/traces",
                "api_key": "Bearer test",
                "enabled": True,
            },
        )

        assert response.status_code == 400
        assert "HTTPS" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_otel_config_masked_key(self, cloud_client, admin_token):
        """GET /settings/otel should return masked API key."""
        ac, app = cloud_client
        _auth(app, admin_token)

        mock_enc = MagicMock()
        mock_enc.decrypt.return_value = "Bearer sk_test_1234567890"

        with patch("burnlens_cloud.settings_api.execute_query", AsyncMock(return_value=[
            {
                "otel_endpoint": "https://otel.datadoghq.com/v1/traces",
                "otel_api_key_encrypted": "gAAAAABl...",
                "otel_enabled": True,
            }
        ])):
            with patch("burnlens_cloud.settings_api.get_encryption_manager", return_value=mock_enc):
                response = await ac.get("/settings/otel")

                assert response.status_code == 200
                assert "api_key_masked" in response.json()
                assert "****" in response.json()["api_key_masked"]
                assert "1234567890" not in response.json()["api_key_masked"]

    @pytest.mark.asyncio
    async def test_post_otel_test_connectivity(self, cloud_client, admin_token):
        """POST /settings/otel/test should test endpoint connectivity."""
        ac, app = cloud_client
        _auth(app, admin_token)

        mock_enc = MagicMock()
        mock_enc.decrypt.return_value = "Bearer test_key"

        with patch("burnlens_cloud.settings_api.execute_query", AsyncMock(return_value=[
            {
                "otel_endpoint": "https://otel.example.com/v1/traces",
                "otel_api_key_encrypted": "gAAAAABl...",
            }
        ])):
            with patch("burnlens_cloud.settings_api.get_encryption_manager", return_value=mock_enc):
                with patch("burnlens_cloud.settings_api.get_forwarder") as mock_fwd_cls:
                    mock_fwd = AsyncMock()
                    mock_fwd.test_endpoint.return_value = (True, 145)
                    mock_fwd_cls.return_value = mock_fwd

                    response = await ac.post("/settings/otel/test")

                    assert response.status_code == 200
                    data = response.json()
                    assert data["ok"] is True
                    assert data["latency_ms"] == 145


class TestCustomPricingEndpoints:
    """Test custom pricing API endpoints."""

    @pytest.mark.asyncio
    async def test_put_pricing_enterprise_only(self, cloud_client, non_enterprise_token):
        """PUT /settings/pricing should reject non-enterprise plans."""
        ac, app = cloud_client
        _auth(app, non_enterprise_token)

        response = await ac.put(
            "/settings/pricing",
            json={"gpt-4o": {"input_per_1m": 4.50, "output_per_1m": 13.50}},
        )

        assert response.status_code == 403
        assert "enterprise" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_put_pricing_success(self, cloud_client, admin_token):
        """PUT /settings/pricing should save custom rates for enterprise."""
        ac, app = cloud_client
        _auth(app, admin_token)

        mock_conn = _make_db_mock()

        with patch("burnlens_cloud.settings_api.get_db", AsyncMock(return_value=mock_conn)):
            with patch("burnlens_cloud.settings_api.execute_insert", AsyncMock()):
                response = await ac.put(
                    "/settings/pricing",
                    json={
                        "gpt-4o": {"input_per_1m": 4.50, "output_per_1m": 13.50},
                        "claude-3.5-sonnet": {"input_per_1m": 3.00, "output_per_1m": 15.00},
                    },
                )

                assert response.status_code == 200
                assert "updated" in response.json()["status"]
                assert len(response.json()["models"]) == 2

    @pytest.mark.asyncio
    async def test_put_pricing_invalid_format(self, cloud_client, admin_token):
        """PUT /settings/pricing should reject invalid format."""
        ac, app = cloud_client
        _auth(app, admin_token)

        response = await ac.put(
            "/settings/pricing",
            json={"gpt-4o": {"input_per_1m": "invalid"}},
        )

        assert response.status_code == 400
        assert "Invalid pricing format" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_put_pricing_missing_fields(self, cloud_client, admin_token):
        """PUT /settings/pricing should reject missing required fields."""
        ac, app = cloud_client
        _auth(app, admin_token)

        response = await ac.put(
            "/settings/pricing",
            json={"gpt-4o": {"input_per_1m": 4.50}},
        )

        assert response.status_code == 400
        assert "output_per_1m" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_pricing_default(self, cloud_client, admin_token):
        """GET /settings/pricing should return empty dict if no custom pricing."""
        ac, app = cloud_client
        _auth(app, admin_token)

        with patch("burnlens_cloud.settings_api.execute_query", AsyncMock(return_value=[])):
            response = await ac.get("/settings/pricing")

            assert response.status_code == 200
            assert response.json()["pricing"] == {}

    @pytest.mark.asyncio
    async def test_get_pricing_custom(self, cloud_client, admin_token):
        """GET /settings/pricing should return custom pricing if set."""
        ac, app = cloud_client
        _auth(app, admin_token)

        with patch("burnlens_cloud.settings_api.execute_query", AsyncMock(return_value=[
            {
                "custom_pricing": {
                    "gpt-4o": {"input_per_1m": 4.50, "output_per_1m": 13.50}
                }
            }
        ])):
            response = await ac.get("/settings/pricing")

            assert response.status_code == 200
            assert "gpt-4o" in response.json()["pricing"]
            assert response.json()["pricing"]["gpt-4o"]["input_per_1m"] == 4.50
