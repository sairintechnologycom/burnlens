import pytest
import pytest_asyncio
from unittest.mock import patch
from uuid import uuid4
from datetime import datetime
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport


@pytest_asyncio.fixture
async def dash_client():
    """AsyncClient wired to the cloud dashboard router."""
    from burnlens_cloud.dashboard_api import router as dashboard_router
    app = FastAPI()
    app.include_router(dashboard_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
def valid_jwt_token():
    """Generate a valid JWT token for testing."""
    from burnlens_cloud.auth import encode_jwt
    ws_id = str(uuid4())
    user_id = str(uuid4())
    return encode_jwt(ws_id, user_id, "owner", "cloud")


@pytest.mark.asyncio
async def test_summary_requires_auth(dash_client):
    """Test that summary endpoint requires authentication."""
    response = await dash_client.get("/api/v1/usage/summary")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_summary_with_auth(dash_client, valid_jwt_token):
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

        response = await dash_client.get(
            "/api/v1/usage/summary",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["total_cost_usd"] == 123.45
    assert data["total_requests"] == 1000
    assert data["models_used"] == 3


@pytest.mark.asyncio
async def test_team_budgets_no_budgets_returns_empty(dash_client, valid_jwt_token):
    with patch("burnlens_cloud.dashboard_api.execute_query") as mock_query:
        mock_query.return_value = [{"tb": None}]
        response = await dash_client.get(
            "/api/v1/team-budgets",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_team_budgets_spend_vs_limit(dash_client, valid_jwt_token):
    """Budgets from limit_overrides joined with month-to-date team spend."""
    with patch("burnlens_cloud.dashboard_api.execute_query") as mock_query:
        mock_query.side_effect = [
            [{"tb": {"search": 500, "chat": 100}}],                # overrides
            [
                {"team": "search", "spent": 450.0},                # 90% -> WARNING
                {"team": "chat", "spent": 120.0},                  # 120% -> EXCEEDED
                {"team": "untracked", "spent": 999.0},             # no budget -> omitted
            ],
        ]
        response = await dash_client.get(
            "/api/v1/team-budgets",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

    assert response.status_code == 200
    rows = response.json()
    assert [r["team"] for r in rows] == ["chat", "search"]  # sorted by pct desc
    chat, search = rows
    assert chat["status"] == "EXCEEDED" and chat["pct_used"] == 120.0
    assert search["status"] == "WARNING" and search["spent"] == 450.0
    assert search["limit"] == 500.0


@pytest.mark.asyncio
async def test_recommendations_requires_auth(dash_client):
    response = await dash_client.get("/api/v1/recommendations")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_recommendations_model_overkill(dash_client, valid_jwt_token):
    """Short-output traffic on an overkill model yields a downgrade rec."""
    with patch("burnlens_cloud.dashboard_api.execute_query") as mock_query:
        mock_query.return_value = [
            {   # triggers: overkill model, avg_out < 200, count > 20
                "model": "gpt-4o",
                "feature_tag": "chat",
                "request_count": 100,
                "avg_input_tokens": 500.0,
                "avg_output_tokens": 40.0,
                "total_cost": 50.0,
            },
            {   # below volume threshold — no rec
                "model": "gpt-4o",
                "feature_tag": "rare",
                "request_count": 5,
                "avg_input_tokens": 500.0,
                "avg_output_tokens": 40.0,
                "total_cost": 1.0,
            },
            {   # long outputs — no rec
                "model": "claude-sonnet-5",
                "feature_tag": "writer",
                "request_count": 100,
                "avg_input_tokens": 500.0,
                "avg_output_tokens": 900.0,
                "total_cost": 80.0,
            },
        ]
        response = await dash_client.get(
            "/api/v1/recommendations",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

    assert response.status_code == 200
    recs = response.json()
    assert len(recs) == 1
    rec = recs[0]
    assert rec["current_model"] == "gpt-4o"
    assert rec["suggested_model"] == "gpt-4o-mini"
    assert rec["feature_tag"] == "chat"
    assert rec["confidence"] == "high"  # avg_out < 50
    assert rec["projected_saving"] > 0
    assert 0 < rec["saving_pct"] <= 100


@pytest.mark.asyncio
async def test_recommendations_empty_workspace(dash_client, valid_jwt_token):
    with patch("burnlens_cloud.dashboard_api.execute_query") as mock_query:
        mock_query.return_value = []
        response = await dash_client.get(
            "/api/v1/recommendations",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_costs_by_model(dash_client, valid_jwt_token):
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

        response = await dash_client.get(
            "/api/v1/usage/by-model?days=7",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["model"] == "gpt-4o"
    assert data[0]["total_cost_usd"] == 50.00


@pytest.mark.asyncio
async def test_costs_by_tag(dash_client, valid_jwt_token):
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

        response = await dash_client.get(
            "/api/v1/usage/by-tag?tag_type=feature&days=7",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["tag"] == "backend"
    assert data[0]["total_cost_usd"] == 30.00


@pytest.mark.asyncio
async def test_costs_timeline(dash_client, valid_jwt_token):
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

        response = await dash_client.get(
            "/api/v1/usage/timeseries?days=7&granularity=day",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["total_cost_usd"] == 10.00


@pytest.mark.asyncio
async def test_requests_endpoint(dash_client, valid_jwt_token):
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

        response = await dash_client.get(
            "/api/v1/requests?limit=50&days=7",
            headers={"Authorization": f"Bearer {valid_jwt_token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_period_clamping_free_tier(dash_client):
    """Test that period is clamped based on plan."""
    from burnlens_cloud.dashboard_api import clamp_days_by_plan

    # Free tier: 7 days max
    assert clamp_days_by_plan(30, "free") == 7
    assert clamp_days_by_plan(7, "free") == 7

    # Cloud: 90 days max
    assert clamp_days_by_plan(180, "cloud") == 90

    # Teams: 365 days max
    assert clamp_days_by_plan(1000, "teams") == 365
