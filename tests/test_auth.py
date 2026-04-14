"""Tests for auth endpoints."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_signup_creates_workspace_and_api_key(client):
    ac, mock_conn = client
    mock_conn.fetchrow.side_effect = [
        None,  # no existing workspace with this email
        {"id": str(uuid4())},  # INSERT RETURNING id
    ]

    resp = await ac.post("/auth/signup", json={
        "email": "new@example.com",
        "workspace_name": "My Team",
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["api_key"].startswith("bl_live_")
    assert "workspace_id" in data
    assert data["workspace_name"] == "My Team"


@pytest.mark.asyncio
async def test_signup_duplicate_email_409(client):
    ac, mock_conn = client
    mock_conn.fetchrow.return_value = {"id": str(uuid4())}  # email exists

    resp = await ac.post("/auth/signup", json={
        "email": "dup@example.com",
        "workspace_name": "Dup",
    })

    assert resp.status_code == 409
    assert "email_already_registered" in resp.text


@pytest.mark.asyncio
async def test_login_valid_key_returns_jwt(client):
    ac, mock_conn = client
    ws_id = str(uuid4())
    mock_conn.fetchrow.return_value = {
        "id": ws_id,
        "name": "My Team",
        "plan": "free",
        "active": True,
    }

    resp = await ac.post("/auth/login", json={"api_key": "bl_live_abc123"})

    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["plan"] == "free"
    assert data["workspace_name"] == "My Team"
    assert data["expires_in"] == 86400


@pytest.mark.asyncio
async def test_login_invalid_key_401(client):
    ac, mock_conn = client
    mock_conn.fetchrow.return_value = None  # not found

    resp = await ac.post("/auth/login", json={"api_key": "bl_live_bad"})

    assert resp.status_code == 401
    assert "invalid_api_key" in resp.text


@pytest.mark.asyncio
async def test_jwt_expired_returns_401(client):
    from api.auth import _encode_jwt
    from jose import jwt as jose_jwt
    import api.config as cfg

    # Create an already-expired token
    payload = {
        "workspace_id": str(uuid4()),
        "plan": "free",
        "iat": int(time.time()) - 100000,
        "exp": int(time.time()) - 1,
    }
    expired_token = jose_jwt.encode(payload, cfg.JWT_SECRET, algorithm="HS256")

    ac, _ = client
    resp = await ac.get("/api/stats", headers={"Authorization": f"Bearer {expired_token}"})

    assert resp.status_code == 401
