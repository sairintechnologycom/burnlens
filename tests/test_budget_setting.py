"""Tests for PUT /settings/budget — set/clear the workspace monthly spend cap."""

import time
from unittest.mock import patch, AsyncMock
from uuid import uuid4

import pytest

from burnlens_cloud.models import TokenPayload
from burnlens_cloud.auth import verify_token as _verify_token


def _auth(app, token):
    app.dependency_overrides[_verify_token] = lambda: token


def _token(role="admin"):
    return TokenPayload(
        workspace_id=uuid4(),
        user_id=uuid4(),
        role=role,
        plan="cloud",
        iat=int(time.time()),
        exp=int(time.time()) + 86400,
    )


def _update_calls(mock_insert):
    return [c for c in mock_insert.call_args_list if "UPDATE workspaces" in c.args[0]]


@pytest.mark.asyncio
async def test_set_budget_writes_override(cloud_client):
    ac, app = cloud_client
    _auth(app, _token("admin"))
    mock_insert = AsyncMock(return_value="UPDATE 1")
    with patch("burnlens_cloud.settings_api.execute_insert", mock_insert):
        resp = await ac.put("/settings/budget", json={"monthly_budget_usd": 500})
    assert resp.status_code == 200
    assert resp.json() == {"monthly_budget_usd": 500}
    upd = _update_calls(mock_insert)
    assert len(upd) == 1
    assert "jsonb_build_object" in upd[0].args[0]   # SET branch
    assert upd[0].args[1] == 500


@pytest.mark.asyncio
async def test_clear_budget_removes_override(cloud_client):
    ac, app = cloud_client
    _auth(app, _token("admin"))
    mock_insert = AsyncMock(return_value="UPDATE 1")
    with patch("burnlens_cloud.settings_api.execute_insert", mock_insert):
        resp = await ac.put("/settings/budget", json={"monthly_budget_usd": None})
    assert resp.status_code == 200
    assert resp.json() == {"monthly_budget_usd": None}
    upd = _update_calls(mock_insert)
    assert len(upd) == 1
    assert "- 'monthly_spend_cap_usd'" in upd[0].args[0]   # clear branch


@pytest.mark.asyncio
async def test_non_positive_budget_rejected(cloud_client):
    ac, app = cloud_client
    _auth(app, _token("admin"))
    mock_insert = AsyncMock()
    with patch("burnlens_cloud.settings_api.execute_insert", mock_insert):
        resp = await ac.put("/settings/budget", json={"monthly_budget_usd": 0})
    assert resp.status_code == 422
    mock_insert.assert_not_called()   # no DB write on invalid input


@pytest.mark.asyncio
async def test_viewer_forbidden(cloud_client):
    ac, app = cloud_client
    _auth(app, _token("viewer"))
    mock_insert = AsyncMock()
    with patch("burnlens_cloud.settings_api.execute_insert", mock_insert):
        resp = await ac.put("/settings/budget", json={"monthly_budget_usd": 500})
    assert resp.status_code == 403
    mock_insert.assert_not_called()


# ============ PUT /settings/team-budget ============


@pytest.mark.asyncio
async def test_set_team_budget_writes_override(cloud_client):
    ac, app = cloud_client
    _auth(app, _token("admin"))
    mock_insert = AsyncMock(return_value="UPDATE 1")
    with patch("burnlens_cloud.settings_api.execute_insert", mock_insert):
        resp = await ac.put(
            "/settings/team-budget", json={"team": "search", "monthly_budget_usd": 500}
        )
    assert resp.status_code == 200
    assert resp.json() == {"team": "search", "monthly_budget_usd": 500}
    upd = _update_calls(mock_insert)
    assert len(upd) == 1
    assert "jsonb_set" in upd[0].args[0]                 # SET branch
    assert upd[0].args[1] == "search"
    assert upd[0].args[2] == 500


@pytest.mark.asyncio
async def test_clear_team_budget_removes_key(cloud_client):
    ac, app = cloud_client
    _auth(app, _token("admin"))
    mock_insert = AsyncMock(return_value="UPDATE 1")
    with patch("burnlens_cloud.settings_api.execute_insert", mock_insert):
        resp = await ac.put(
            "/settings/team-budget", json={"team": "search", "monthly_budget_usd": None}
        )
    assert resp.status_code == 200
    assert resp.json() == {"team": "search", "monthly_budget_usd": None}
    upd = _update_calls(mock_insert)
    assert len(upd) == 1
    assert "#- ARRAY['team_budgets', $1]" in upd[0].args[0]   # clear branch
    assert upd[0].args[1] == "search"


@pytest.mark.asyncio
async def test_team_budget_blank_team_rejected(cloud_client):
    ac, app = cloud_client
    _auth(app, _token("admin"))
    mock_insert = AsyncMock()
    with patch("burnlens_cloud.settings_api.execute_insert", mock_insert):
        resp = await ac.put(
            "/settings/team-budget", json={"team": "   ", "monthly_budget_usd": 500}
        )
    assert resp.status_code == 422
    mock_insert.assert_not_called()


@pytest.mark.asyncio
async def test_team_budget_viewer_forbidden(cloud_client):
    ac, app = cloud_client
    _auth(app, _token("viewer"))
    mock_insert = AsyncMock()
    with patch("burnlens_cloud.settings_api.execute_insert", mock_insert):
        resp = await ac.put(
            "/settings/team-budget", json={"team": "search", "monthly_budget_usd": 500}
        )
    assert resp.status_code == 403
    mock_insert.assert_not_called()
