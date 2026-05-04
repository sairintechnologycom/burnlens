"""Tests for custom pricing configuration."""

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
def enterprise_admin_token():
    return TokenPayload(
        workspace_id=uuid4(),
        user_id=uuid4(),
        role="admin",
        plan="enterprise",
        iat=int(__import__("time").time()),
        exp=int(__import__("time").time()) + 86400,
    )


@pytest.fixture
def cloud_admin_token():
    return TokenPayload(
        workspace_id=uuid4(),
        user_id=uuid4(),
        role="admin",
        plan="cloud",
        iat=int(__import__("time").time()),
        exp=int(__import__("time").time()) + 86400,
    )


class TestCustomPricingGet:
    """Test GET /settings/pricing endpoint."""

    @pytest.mark.asyncio
    async def test_get_pricing_no_custom(self, cloud_client, enterprise_admin_token):
        """GET pricing with no custom override should return empty dict."""
        ac, app = cloud_client
        _auth(app, enterprise_admin_token)

        with patch("burnlens_cloud.settings_api.execute_query", AsyncMock(return_value=[])):
            response = await ac.get("/settings/pricing")

            assert response.status_code == 200
            assert response.json()["pricing"] == {}

    @pytest.mark.asyncio
    async def test_get_pricing_with_custom(self, cloud_client, enterprise_admin_token):
        """GET pricing should return custom rates if set."""
        ac, app = cloud_client
        _auth(app, enterprise_admin_token)

        with patch("burnlens_cloud.settings_api.execute_query", AsyncMock(return_value=[
            {
                "custom_pricing": {
                    "gpt-4o": {"input_per_1m": 4.50, "output_per_1m": 13.50},
                    "claude-3.5-sonnet": {"input_per_1m": 3.00, "output_per_1m": 15.00},
                }
            }
        ])):
            response = await ac.get("/settings/pricing")

            assert response.status_code == 200
            data = response.json()
            assert "gpt-4o" in data["pricing"]
            assert data["pricing"]["gpt-4o"]["input_per_1m"] == 4.50
            assert data["pricing"]["gpt-4o"]["output_per_1m"] == 13.50

    @pytest.mark.asyncio
    async def test_get_pricing_admin_only(self, cloud_client):
        """GET pricing should require admin+ role."""
        ac, app = cloud_client
        viewer_token = TokenPayload(
            workspace_id=uuid4(),
            user_id=uuid4(),
            role="viewer",
            plan="enterprise",
            iat=int(__import__("time").time()),
            exp=int(__import__("time").time()) + 86400,
        )
        _auth(app, viewer_token)

        response = await ac.get("/settings/pricing")
        assert response.status_code == 403


class TestCustomPricingPut:
    """Test PUT /settings/pricing endpoint."""

    @pytest.mark.asyncio
    async def test_put_pricing_enterprise_only(self, cloud_client, cloud_admin_token):
        """PUT pricing should reject non-enterprise plans."""
        ac, app = cloud_client
        _auth(app, cloud_admin_token)

        response = await ac.put(
            "/settings/pricing",
            json={"gpt-4o": {"input_per_1m": 5.0, "output_per_1m": 15.0}},
        )

        assert response.status_code == 403
        assert "enterprise" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_put_pricing_success(self, cloud_client, enterprise_admin_token):
        """PUT pricing should save custom rates for enterprise."""
        ac, app = cloud_client
        _auth(app, enterprise_admin_token)

        mock_conn = _make_db_mock()

        with patch("burnlens_cloud.settings_api.get_db", AsyncMock(return_value=mock_conn)):
            with patch("burnlens_cloud.settings_api.execute_insert", AsyncMock()):
                response = await ac.put(
                    "/settings/pricing",
                    json={"gpt-4o": {"input_per_1m": 4.50, "output_per_1m": 13.50}},
                )

                assert response.status_code == 200
                data = response.json()
                assert "updated" in data["status"]
                assert "gpt-4o" in data["models"]

    @pytest.mark.asyncio
    async def test_put_pricing_multiple_models(self, cloud_client, enterprise_admin_token):
        """PUT pricing should accept multiple models."""
        ac, app = cloud_client
        _auth(app, enterprise_admin_token)

        mock_conn = _make_db_mock()

        with patch("burnlens_cloud.settings_api.get_db", AsyncMock(return_value=mock_conn)):
            with patch("burnlens_cloud.settings_api.execute_insert", AsyncMock()):
                response = await ac.put(
                    "/settings/pricing",
                    json={
                        "gpt-4o": {"input_per_1m": 4.50, "output_per_1m": 13.50},
                        "gpt-4-turbo": {"input_per_1m": 10.0, "output_per_1m": 30.0},
                        "claude-3.5-sonnet": {"input_per_1m": 3.0, "output_per_1m": 15.0},
                    },
                )

                assert response.status_code == 200
                assert len(response.json()["models"]) == 3

    @pytest.mark.asyncio
    async def test_put_pricing_missing_output_rate(self, cloud_client, enterprise_admin_token):
        """PUT pricing should reject missing output_per_1m."""
        ac, app = cloud_client
        _auth(app, enterprise_admin_token)

        response = await ac.put(
            "/settings/pricing",
            json={"gpt-4o": {"input_per_1m": 4.50}},
        )

        assert response.status_code == 400
        assert "output_per_1m" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_put_pricing_missing_input_rate(self, cloud_client, enterprise_admin_token):
        """PUT pricing should reject missing input_per_1m."""
        ac, app = cloud_client
        _auth(app, enterprise_admin_token)

        response = await ac.put(
            "/settings/pricing",
            json={"gpt-4o": {"output_per_1m": 13.50}},
        )

        assert response.status_code == 400
        assert "input_per_1m" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_put_pricing_invalid_rate_type(self, cloud_client, enterprise_admin_token):
        """PUT pricing should reject non-numeric rates."""
        ac, app = cloud_client
        _auth(app, enterprise_admin_token)

        response = await ac.put(
            "/settings/pricing",
            json={"gpt-4o": {"input_per_1m": "invalid", "output_per_1m": 13.50}},
        )

        assert response.status_code == 400
        assert "Invalid pricing format" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_put_pricing_logs_audit(self, cloud_client, enterprise_admin_token):
        """PUT pricing should create audit log entry."""
        ac, app = cloud_client
        _auth(app, enterprise_admin_token)

        mock_conn = _make_db_mock()

        with patch("burnlens_cloud.settings_api.get_db", AsyncMock(return_value=mock_conn)):
            with patch("burnlens_cloud.settings_api.execute_insert", AsyncMock()) as mock_insert:
                response = await ac.put(
                    "/settings/pricing",
                    json={"gpt-4o": {"input_per_1m": 4.50, "output_per_1m": 13.50}},
                )

                assert response.status_code == 200
                mock_insert.assert_called_once()
                call_args = mock_insert.call_args[0]
                assert "update_custom_pricing" in call_args

    @pytest.mark.asyncio
    async def test_put_pricing_negative_rates_allowed(self, cloud_client, enterprise_admin_token):
        """PUT pricing should accept any numeric values (no validation)."""
        ac, app = cloud_client
        _auth(app, enterprise_admin_token)

        mock_conn = _make_db_mock()

        with patch("burnlens_cloud.settings_api.get_db", AsyncMock(return_value=mock_conn)):
            with patch("burnlens_cloud.settings_api.execute_insert", AsyncMock()):
                response = await ac.put(
                    "/settings/pricing",
                    json={"discount-model": {"input_per_1m": -0.50, "output_per_1m": 0.0}},
                )

                assert response.status_code == 200


class TestPricingIntegration:
    """Test custom pricing integration with ingest."""

    def test_custom_pricing_applied_to_cost_calculation(self):
        """Cost calculation should use custom rates if configured."""
        pass
