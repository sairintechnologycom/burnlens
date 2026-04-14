import pytest
from unittest.mock import patch, AsyncMock
from uuid import uuid4
from datetime import datetime


@pytest.mark.asyncio
async def test_signup(client, mock_db):
    """Test workspace signup."""
    workspace_id = str(uuid4())

    with patch("burnlens_cloud.auth.execute_insert") as mock_insert:
        mock_insert.return_value = None

        response = await client.post(
            "/auth/signup",
            json={
                "email": "test@example.com",
                "workspace_name": "Test Workspace",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert "api_key" in data
    assert data["api_key"].startswith("bl_live_")
    assert "workspace_id" in data
    assert data["message"] == "Workspace created successfully. Use the API key to login and start syncing data."


@pytest.mark.asyncio
async def test_login_success(client, mock_db):
    """Test successful login."""
    workspace_id = str(uuid4())
    api_key = "bl_live_testkey123"

    with patch("burnlens_cloud.auth.execute_query") as mock_query:
        mock_query.return_value = [
            {
                "id": workspace_id,
                "name": "Test Workspace",
                "owner_email": "test@example.com",
                "plan": "free",
                "api_key": api_key,
                "created_at": datetime.utcnow(),
                "active": True,
            }
        ]

        response = await client.post(
            "/auth/login",
            json={"api_key": api_key},
        )

    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    assert data["expires_in"] == 86400
    assert data["workspace"]["name"] == "Test Workspace"
    assert data["workspace"]["plan"] == "free"


@pytest.mark.asyncio
async def test_login_invalid_api_key(client):
    """Test login with invalid API key."""
    with patch("burnlens_cloud.auth.execute_query") as mock_query:
        mock_query.return_value = []

        response = await client.post(
            "/auth/login",
            json={"api_key": "invalid_key"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"


@pytest.mark.asyncio
async def test_api_key_validation_format():
    """Test API key format validation."""
    from burnlens_cloud.auth import generate_api_key

    key = generate_api_key()
    assert key.startswith("bl_live_")
    assert len(key) == len("bl_live_") + 32


@pytest.mark.asyncio
async def test_jwt_encode_decode():
    """Test JWT token generation and validation."""
    from burnlens_cloud.auth import encode_jwt, decode_jwt
    from uuid import uuid4

    workspace_id = str(uuid4())
    plan = "cloud"

    token = encode_jwt(workspace_id, plan)
    payload = decode_jwt(token)

    assert payload.workspace_id == workspace_id
    assert payload.plan == plan
    assert payload.exp > payload.iat


@pytest.mark.asyncio
async def test_jwt_invalid_token():
    """Test JWT validation with invalid token."""
    from burnlens_cloud.auth import decode_jwt

    payload = decode_jwt("invalid.token.here")
    assert payload is None
