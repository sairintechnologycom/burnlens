import pytest
import jwt
import time
from uuid import uuid4
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from burnlens_cloud.main import app
from burnlens_cloud.action_tokens import create_action_token, ACTION_TOKEN_ALGORITHM
from burnlens_cloud.config import settings

client = TestClient(app)

WS_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
KEY_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

@pytest.mark.asyncio
async def test_action_token_lifecycle():
    token = await create_action_token("pause_api_key", WS_ID, KEY_ID)
    assert token is not None
    
    # Verify decoding
    decoded = jwt.decode(token, settings.jwt_secret, algorithms=[ACTION_TOKEN_ALGORITHM])
    assert decoded["action"] == "pause_api_key"
    assert decoded["workspace_id"] == WS_ID
    assert decoded["target_id"] == KEY_ID
    assert "jti" in decoded
    assert decoded["exp"] > time.time()

@pytest.mark.asyncio
async def test_confirm_endpoint():
    token = await create_action_token("pause_api_key", WS_ID, KEY_ID)
    response = client.get(f"/api/v1/actions/confirm?token={token}")
    assert response.status_code == 200
    assert "Confirm Pause Api Key" in response.text
    # We don't render raw IDs in HTML for security/UX; check for action label
    assert "Pause Api Key" in response.text

@pytest.mark.asyncio
@patch("burnlens_cloud.actions_api.execute_query")
@patch("burnlens_cloud.actions_api.execute_insert")
@patch("burnlens_cloud.actions_api.consume_action_token")
async def test_execute_pause_api_key(mock_token_consume, mock_action_insert, mock_action_query):
    token = await create_action_token("pause_api_key", WS_ID, KEY_ID)
    
    # Mock token consumption
    mock_token_consume.return_value = True
    
    # Mock action execution
    mock_action_query.return_value = [{"key_hash": "hash123"}]
    
    # Execute action
    response = client.post("/api/v1/actions/execute", data={"token": token})
    assert response.status_code == 200
    assert response.json()["ok"] is True
    
    # Verify pause was called
    mock_action_query.assert_called()
    args = mock_action_query.call_args[0]
    assert "UPDATE api_keys" in args[0]
    assert "paused_at = NOW()" in args[0]
    assert KEY_ID in args

@pytest.mark.asyncio
@patch("burnlens_cloud.actions_api.execute_query")
@patch("burnlens_cloud.actions_api.execute_insert")
@patch("burnlens_cloud.actions_api.consume_action_token")
async def test_token_single_use(mock_token_consume, mock_action_insert, mock_action_query):
    token = await create_action_token("pause_api_key", WS_ID, KEY_ID)
    
    # Second use fails (mocked consumption failure)
    mock_token_consume.return_value = False
    response = client.post("/api/v1/actions/execute", data={"token": token})
    assert response.status_code == 400
    assert response.json()["detail"] == "token_already_consumed"

@pytest.mark.asyncio
@patch("burnlens_cloud.actions_api.execute_query")
@patch("burnlens_cloud.actions_api.execute_insert")
@patch("burnlens_cloud.actions_api.consume_action_token")
async def test_execute_increase_budget(mock_token_consume, mock_action_insert, mock_action_query):
    # Initial state
    mock_action_query.return_value = [{"monthly_request_cap": 1000}]
    mock_token_consume.return_value = True
    
    token = await create_action_token("increase_budget", WS_ID)
    response = client.post("/api/v1/actions/execute", data={"token": token})
    assert response.status_code == 200
    
    # Verify budget increase (1000 * 1.5 = 1500)
    mock_action_insert.assert_called()
    # Find the call that updates workspaces
    found = False
    for call in mock_action_insert.call_args_list:
        query = call[0][0]
        if "UPDATE workspaces" in query and "limit_overrides" in query:
            assert call[0][1] == 1500
            found = True
            break
    assert found, "Budget update query not found in calls"
