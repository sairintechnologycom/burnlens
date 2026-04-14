import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime


@pytest.fixture
def valid_jwt_token():
    """Generate a valid JWT token for testing."""
    from burnlens_cloud.auth import encode_jwt
    return encode_jwt(str(uuid4()), "cloud")


@pytest.mark.asyncio
async def test_summary_requires_auth(client):
    """Test that summary endpoint requires authentication."""
    response = await client.get("/api/summary")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_summary_with_auth(client, valid_jwt_token):
    """Test summary endpoint with valid JWT."""
    with patch("burnlens_cloud.dashboard_api.execute_query") as mock_query:
        mock_query.return_value = [
            {
                "total_cost": 123.45,
                "request_count": 1000,
                "model_count": 3,
                "avg_cost": 0.12345,
            }
        ]

        response = await client.get(
            "/api/summary",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["total_cost_usd"] == 123.45
    assert data["total_requests"] == 1000
    assert data["models_used"] == 3


@pytest.mark.asyncio
async def test_costs_by_model(client, valid_jwt_token):
    """Test costs by model endpoint."""
    with patch("burnlens_cloud.dashboard_api.execute_query") as mock_query:
        mock_query.return_value = [
            {
                "model": "gpt-4o",
                "provider": "openai",
                "request_count": 500,
                "total_input_tokens": 25000,
                "total_output_tokens": 5000,
                "total_cost": 50.00,
            }
        ]

        response = await client.get(
            "/api/costs/by-model?period=7d",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["model"] == "gpt-4o"
    assert data[0]["total_cost_usd"] == 50.00


@pytest.mark.asyncio
async def test_costs_by_tag(client, valid_jwt_token):
    """Test costs by tag endpoint."""
    with patch("burnlens_cloud.dashboard_api.execute_query") as mock_query:
        mock_query.return_value = [
            {
                "tag_value": "backend",
                "request_count": 300,
                "total_cost": 30.00,
                "total_input_tokens": 15000,
                "total_output_tokens": 3000,
            }
        ]

        response = await client.get(
            "/api/costs/by-tag?tag_type=team&period=7d",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["tag"] == "backend"
    assert data[0]["total_cost_usd"] == 30.00


@pytest.mark.asyncio
async def test_costs_timeline(client, valid_jwt_token):
    """Test cost timeline endpoint."""
    from datetime import date

    with patch("burnlens_cloud.dashboard_api.execute_query") as mock_query:
        mock_query.return_value = [
            {
                "date": date(2024, 1, 15),
                "request_count": 100,
                "total_cost": 10.00,
            }
        ]

        response = await client.get(
            "/api/costs/timeline?period=7d&granularity=daily",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["total_cost_usd"] == 10.00


@pytest.mark.asyncio
async def test_requests_endpoint(client, valid_jwt_token):
    """Test requests endpoint."""
    with patch("burnlens_cloud.dashboard_api.execute_query") as mock_query:
        mock_query.return_value = [
            {
                "id": 1,
                "workspace_id": str(uuid4()),
                "ts": datetime.utcnow(),
                "provider": "openai",
                "model": "gpt-4o",
                "input_tokens": 100,
                "output_tokens": 50,
                "reasoning_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "cost_usd": 0.015,
                "duration_ms": 1250,
                "status_code": 200,
                "tags": {"team": "backend"},
                "system_prompt_hash": "hash123",
                "received_at": datetime.utcnow(),
            }
        ]

        response = await client.get(
            "/api/requests?limit=50&period=7d",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_period_clamping_free_tier(client):
    """Test that period is clamped based on plan."""
    from burnlens_cloud.dashboard_api import clamp_days_by_plan

    # Free tier: 7 days max
    assert clamp_days_by_plan(30, "free") == 7
    assert clamp_days_by_plan(7, "free") == 7

    # Cloud: 90 days max
    assert clamp_days_by_plan(180, "cloud") == 90

    # Teams: 365 days max
    assert clamp_days_by_plan(1000, "teams") == 365
