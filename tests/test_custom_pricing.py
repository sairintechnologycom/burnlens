"""Tests for custom pricing configuration."""

import pytest
from unittest.mock import patch, AsyncMock
from uuid import uuid4

from burnlens_cloud.models import TokenPayload


@pytest.fixture
def enterprise_admin_token():
    """Create admin token for enterprise plan."""
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
    """Create admin token for cloud plan (non-enterprise)."""
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
    async def test_get_pricing_no_custom(self, client, enterprise_admin_token):
        """GET pricing with no custom override should return empty dict."""
        with patch("burnlens_cloud.settings_api.verify_token", return_value=enterprise_admin_token):
            with patch("burnlens_cloud.settings_api.execute_query") as mock_query:
                mock_query.return_value = []  # No custom pricing

                response = await client.get("/settings/pricing")

                assert response.status_code == 200
                data = response.json()
                assert data["pricing"] == {}

    @pytest.mark.asyncio
    async def test_get_pricing_with_custom(self, client, enterprise_admin_token):
        """GET pricing should return custom rates if set."""
        with patch("burnlens_cloud.settings_api.verify_token", return_value=enterprise_admin_token):
            with patch("burnlens_cloud.settings_api.execute_query") as mock_query:
                mock_query.return_value = [
                    {
                        "custom_pricing": {
                            "gpt-4o": {
                                "input_per_1m": 4.50,
                                "output_per_1m": 13.50,
                            },
                            "claude-3.5-sonnet": {
                                "input_per_1m": 3.00,
                                "output_per_1m": 15.00,
                            },
                        }
                    }
                ]

                response = await client.get("/settings/pricing")

                assert response.status_code == 200
                data = response.json()
                assert "gpt-4o" in data["pricing"]
                assert data["pricing"]["gpt-4o"]["input_per_1m"] == 4.50
                assert data["pricing"]["gpt-4o"]["output_per_1m"] == 13.50

    @pytest.mark.asyncio
    async def test_get_pricing_admin_only(self, client):
        """GET pricing should require admin+ role."""
        viewer_token = TokenPayload(
            workspace_id=uuid4(),
            user_id=uuid4(),
            role="viewer",
            plan="enterprise",
            iat=int(__import__("time").time()),
            exp=int(__import__("time").time()) + 86400,
        )

        with patch("burnlens_cloud.settings_api.verify_token", return_value=viewer_token):
            with patch("burnlens_cloud.settings_api.require_role") as mock_require:
                mock_require.side_effect = __import__("fastapi").HTTPException(status_code=403)

                response = await client.get("/settings/pricing")
                assert response.status_code == 403


class TestCustomPricingPut:
    """Test PUT /settings/pricing endpoint."""

    @pytest.mark.asyncio
    async def test_put_pricing_enterprise_only(self, client, cloud_admin_token):
        """PUT pricing should reject non-enterprise plans."""
        with patch("burnlens_cloud.settings_api.verify_token", return_value=cloud_admin_token):
            response = await client.put(
                "/settings/pricing",
                json={"gpt-4o": {"input_per_1m": 5.0, "output_per_1m": 15.0}},
            )

            assert response.status_code == 403
            assert "enterprise" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_put_pricing_success(self, client, enterprise_admin_token):
        """PUT pricing should save custom rates for enterprise."""
        with patch("burnlens_cloud.settings_api.verify_token", return_value=enterprise_admin_token):
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
                        },
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert "updated" in data["status"]
                    assert "gpt-4o" in data["models"]

    @pytest.mark.asyncio
    async def test_put_pricing_multiple_models(self, client, enterprise_admin_token):
        """PUT pricing should accept multiple models."""
        with patch("burnlens_cloud.settings_api.verify_token", return_value=enterprise_admin_token):
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
                            "gpt-4-turbo": {"input_per_1m": 10.0, "output_per_1m": 30.0},
                            "claude-3.5-sonnet": {"input_per_1m": 3.0, "output_per_1m": 15.0},
                        },
                    )

                    assert response.status_code == 200
                    assert len(response.json()["models"]) == 3

    @pytest.mark.asyncio
    async def test_put_pricing_missing_output_rate(self, client, enterprise_admin_token):
        """PUT pricing should reject missing output_per_1m."""
        with patch("burnlens_cloud.settings_api.verify_token", return_value=enterprise_admin_token):
            response = await client.put(
                "/settings/pricing",
                json={
                    "gpt-4o": {"input_per_1m": 4.50}  # Missing output_per_1m
                },
            )

            assert response.status_code == 400
            assert "output_per_1m" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_put_pricing_missing_input_rate(self, client, enterprise_admin_token):
        """PUT pricing should reject missing input_per_1m."""
        with patch("burnlens_cloud.settings_api.verify_token", return_value=enterprise_admin_token):
            response = await client.put(
                "/settings/pricing",
                json={
                    "gpt-4o": {"output_per_1m": 13.50}  # Missing input_per_1m
                },
            )

            assert response.status_code == 400
            assert "input_per_1m" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_put_pricing_invalid_rate_type(self, client, enterprise_admin_token):
        """PUT pricing should reject non-numeric rates."""
        with patch("burnlens_cloud.settings_api.verify_token", return_value=enterprise_admin_token):
            response = await client.put(
                "/settings/pricing",
                json={
                    "gpt-4o": {"input_per_1m": "invalid", "output_per_1m": 13.50}
                },
            )

            assert response.status_code == 400
            assert "Invalid pricing format" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_put_pricing_logs_audit(self, client, enterprise_admin_token):
        """PUT pricing should create audit log entry."""
        with patch("burnlens_cloud.settings_api.verify_token", return_value=enterprise_admin_token):
            with patch("burnlens_cloud.settings_api.get_db") as mock_db_class:
                mock_db = AsyncMock()
                mock_db.execute.return_value = None
                mock_db.transaction.return_value.__aenter__.return_value = mock_db
                mock_db.transaction.return_value.__aexit__.return_value = None
                mock_db_class.return_value = mock_db

                with patch("burnlens_cloud.settings_api.execute_insert") as mock_insert:
                    response = await client.put(
                        "/settings/pricing",
                        json={
                            "gpt-4o": {"input_per_1m": 4.50, "output_per_1m": 13.50},
                        },
                    )

                    assert response.status_code == 200

                    # Verify audit log was inserted
                    mock_insert.assert_called_once()
                    call_args = mock_insert.call_args[0]
                    assert "update_custom_pricing" in call_args[0]

    @pytest.mark.asyncio
    async def test_put_pricing_negative_rates_allowed(self, client, enterprise_admin_token):
        """PUT pricing should accept any numeric values (no validation)."""
        with patch("burnlens_cloud.settings_api.verify_token", return_value=enterprise_admin_token):
            with patch("burnlens_cloud.settings_api.get_db") as mock_db_class:
                mock_db = AsyncMock()
                mock_db.execute.return_value = None
                mock_db.transaction.return_value.__aenter__.return_value = mock_db
                mock_db.transaction.return_value.__aexit__.return_value = None
                mock_db_class.return_value = mock_db

                with patch("burnlens_cloud.settings_api.execute_insert"):
                    # Edge case: allow negative or zero rates (might be used for credits)
                    response = await client.put(
                        "/settings/pricing",
                        json={
                            "discount-model": {"input_per_1m": -0.50, "output_per_1m": 0.0},
                        },
                    )

                    assert response.status_code == 200


class TestPricingIntegration:
    """Test custom pricing integration with ingest."""

    def test_custom_pricing_applied_to_cost_calculation():
        """Cost calculation should use custom rates if configured."""
        # This would be tested in test_ingest.py
        # Integration test: verify custom_pricing is passed to cost calculator
        pass
