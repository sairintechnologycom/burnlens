"""Tests for settings API endpoints (OTEL, pricing)."""

import pytest
from unittest.mock import patch, AsyncMock
from uuid import uuid4

from burnlens_cloud.models import TokenPayload


@pytest.fixture
def owner_token():
    """Create owner token for testing."""
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
    """Create admin token for testing."""
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
    """Create token for non-enterprise plan."""
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
    async def test_put_otel_config_success(self, client, owner_token):
        """PUT /settings/otel should update config and test endpoint."""
        with patch("burnlens_cloud.settings_api.verify_token", return_value=owner_token):
            with patch("burnlens_cloud.settings_api.get_forwarder") as mock_forwarder_class:
                mock_forwarder = AsyncMock()
                mock_forwarder.test_endpoint.return_value = (True, 150)
                mock_forwarder_class.return_value = mock_forwarder

                with patch("burnlens_cloud.settings_api.execute_query"):
                    with patch("burnlens_cloud.settings_api.get_db") as mock_db_class:
                        mock_db = AsyncMock()
                        mock_db.execute.return_value = None
                        mock_db.transaction.return_value.__aenter__.return_value = mock_db
                        mock_db.transaction.return_value.__aexit__.return_value = None
                        mock_db_class.return_value = mock_db

                        response = await client.put(
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
    async def test_put_otel_config_http_endpoint_rejected(self, client, owner_token):
        """PUT /settings/otel should reject non-HTTPS endpoints."""
        with patch("burnlens_cloud.settings_api.verify_token", return_value=owner_token):
            response = await client.put(
                "/settings/otel",
                json={
                    "endpoint": "http://otel.example.com/v1/traces",  # HTTP not HTTPS
                    "api_key": "Bearer test",
                    "enabled": True,
                },
            )

            assert response.status_code == 400
            assert "HTTPS" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_otel_config_masked_key(self, client, admin_token):
        """GET /settings/otel should return masked API key."""
        with patch("burnlens_cloud.settings_api.verify_token", return_value=admin_token):
            with patch(
                "burnlens_cloud.settings_api.execute_query"
            ) as mock_query:
                mock_query.return_value = [
                    {
                        "otel_endpoint": "https://otel.datadoghq.com/v1/traces",
                        "otel_api_key_encrypted": "gAAAAABl...",  # Fernet encrypted
                        "otel_enabled": True,
                    }
                ]

                with patch("burnlens_cloud.settings_api.get_encryption_manager") as mock_enc_class:
                    mock_enc = AsyncMock()
                    mock_enc.decrypt.return_value = "Bearer sk_test_1234567890"
                    mock_enc_class.return_value = mock_enc

                    response = await client.get("/settings/otel")

                    assert response.status_code == 200
                    assert "api_key_masked" in response.json()
                    assert "****" in response.json()["api_key_masked"]
                    assert "1234567890" not in response.json()["api_key_masked"]

    @pytest.mark.asyncio
    async def test_post_otel_test_connectivity(self, client, admin_token):
        """POST /settings/otel/test should test endpoint connectivity."""
        with patch("burnlens_cloud.settings_api.verify_token", return_value=admin_token):
            with patch("burnlens_cloud.settings_api.execute_query") as mock_query:
                mock_query.return_value = [
                    {
                        "otel_endpoint": "https://otel.example.com/v1/traces",
                        "otel_api_key_encrypted": "gAAAAABl...",
                    }
                ]

                with patch("burnlens_cloud.settings_api.get_encryption_manager") as mock_enc_class:
                    mock_enc = AsyncMock()
                    mock_enc.decrypt.return_value = "Bearer test_key"
                    mock_enc_class.return_value = mock_enc

                    with patch("burnlens_cloud.settings_api.get_forwarder") as mock_forwarder_class:
                        mock_forwarder = AsyncMock()
                        mock_forwarder.test_endpoint.return_value = (True, 145)
                        mock_forwarder_class.return_value = mock_forwarder

                        response = await client.post("/settings/otel/test")

                        assert response.status_code == 200
                        data = response.json()
                        assert data["ok"] is True
                        assert data["latency_ms"] == 145


class TestCustomPricingEndpoints:
    """Test custom pricing API endpoints."""

    @pytest.mark.asyncio
    async def test_put_pricing_enterprise_only(self, client, non_enterprise_token):
        """PUT /settings/pricing should reject non-enterprise plans."""
        with patch("burnlens_cloud.settings_api.verify_token", return_value=non_enterprise_token):
            response = await client.put(
                "/settings/pricing",
                json={"gpt-4o": {"input_per_1m": 4.50, "output_per_1m": 13.50}},
            )

            assert response.status_code == 403
            assert "enterprise" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_put_pricing_success(self, client, admin_token):
        """PUT /settings/pricing should save custom rates for enterprise."""
        with patch("burnlens_cloud.settings_api.verify_token", return_value=admin_token):
            with patch("burnlens_cloud.settings_api.get_db") as mock_db_class:
                mock_db = AsyncMock()
                mock_db.execute.return_value = None
                mock_db.transaction.return_value.__aenter__.return_value = mock_db
                mock_db.transaction.return_value.__aexit__.return_value = None
                mock_db_class.return_value = mock_db

                with patch("burnlens_cloud.settings_api.execute_insert"):
                    response = await client.put(
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
    async def test_put_pricing_invalid_format(self, client, admin_token):
        """PUT /settings/pricing should reject invalid format."""
        with patch("burnlens_cloud.settings_api.verify_token", return_value=admin_token):
            response = await client.put(
                "/settings/pricing",
                json={
                    "gpt-4o": {"input_per_1m": "invalid"}  # String instead of float
                },
            )

            assert response.status_code == 400
            assert "Invalid pricing format" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_put_pricing_missing_fields(self, client, admin_token):
        """PUT /settings/pricing should reject missing required fields."""
        with patch("burnlens_cloud.settings_api.verify_token", return_value=admin_token):
            response = await client.put(
                "/settings/pricing",
                json={
                    "gpt-4o": {"input_per_1m": 4.50}  # Missing output_per_1m
                },
            )

            assert response.status_code == 400
            assert "output_per_1m" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_pricing_default(self, client, admin_token):
        """GET /settings/pricing should return empty dict if no custom pricing."""
        with patch("burnlens_cloud.settings_api.verify_token", return_value=admin_token):
            with patch("burnlens_cloud.settings_api.execute_query") as mock_query:
                mock_query.return_value = []  # No custom pricing set

                response = await client.get("/settings/pricing")

                assert response.status_code == 200
                assert response.json()["pricing"] == {}

    @pytest.mark.asyncio
    async def test_get_pricing_custom(self, client, admin_token):
        """GET /settings/pricing should return custom pricing if set."""
        with patch("burnlens_cloud.settings_api.verify_token", return_value=admin_token):
            with patch("burnlens_cloud.settings_api.execute_query") as mock_query:
                mock_query.return_value = [
                    {
                        "custom_pricing": {
                            "gpt-4o": {"input_per_1m": 4.50, "output_per_1m": 13.50}
                        }
                    }
                ]

                response = await client.get("/settings/pricing")

                assert response.status_code == 200
                assert "gpt-4o" in response.json()["pricing"]
                assert response.json()["pricing"]["gpt-4o"]["input_per_1m"] == 4.50
