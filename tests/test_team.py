"""Tests for team management endpoints."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


WS_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
USER_ID = "11111111-2222-3333-4444-555555555555"


def _teams_authed(mock_conn, token_plan="teams", token_role="owner"):
    """Helper: set up mock_conn for get_current_workspace with a teams plan."""
    from api.auth import _encode_jwt
    token = _encode_jwt(WS_ID, token_plan, user_id=USER_ID, role=token_role)
    mock_conn.fetchrow.return_value = {
        "id": WS_ID,
        "name": "Test WS",
        "plan": token_plan,
        "active": True,
    }
    return token


# ---- invite -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_invite_creates_invitation_record(client):
    ac, mock_conn = client
    token = _teams_authed(mock_conn)

    # fetchval for member count, fetchrow for existing member check, fetchrow for INSERT
    mock_conn.fetchval.return_value = 2  # 2 members
    invite_id = str(uuid4())
    expires = datetime.now(timezone.utc) + timedelta(hours=48)

    call_count = [0]
    original_fetchrow = mock_conn.fetchrow

    async def _fetchrow_side(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            # get_current_workspace
            return {"id": WS_ID, "name": "Test WS", "plan": "teams", "active": True}
        elif call_count[0] == 2:
            # existing member check
            return None
        elif call_count[0] == 3:
            # INSERT invitation RETURNING
            return {"id": invite_id, "expires_at": expires}
        return None

    mock_conn.fetchrow.side_effect = _fetchrow_side

    with patch("api.team._send_invite_email"):
        with patch("api.team._log_activity", new_callable=AsyncMock):
            resp = await ac.post(
                "/team/invite",
                json={"email": "new@example.com", "role": "viewer"},
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["invitation_id"] == invite_id


@pytest.mark.asyncio
async def test_invite_sends_email(client):
    ac, mock_conn = client
    token = _teams_authed(mock_conn)
    mock_conn.fetchval.return_value = 1
    invite_id = str(uuid4())
    expires = datetime.now(timezone.utc) + timedelta(hours=48)

    call_count = [0]

    async def _fetchrow_side(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"id": WS_ID, "name": "Test WS", "plan": "teams", "active": True}
        elif call_count[0] == 2:
            return None
        elif call_count[0] == 3:
            return {"id": invite_id, "expires_at": expires}
        return None

    mock_conn.fetchrow.side_effect = _fetchrow_side

    with patch("api.team._send_invite_email") as mock_email:
        with patch("api.team._log_activity", new_callable=AsyncMock):
            resp = await ac.post(
                "/team/invite",
                json={"email": "test@co.com", "role": "admin"},
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200
    mock_email.assert_called_once()
    call_args = mock_email.call_args[0]
    assert call_args[0] == "test@co.com"
    assert call_args[1] == "Test WS"


@pytest.mark.asyncio
async def test_invite_rejected_on_seat_limit(client):
    ac, mock_conn = client
    token = _teams_authed(mock_conn)
    mock_conn.fetchval.return_value = 10  # at limit for teams plan

    resp = await ac.post(
        "/team/invite",
        json={"email": "extra@co.com", "role": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 422
    assert "seat_limit_reached" in resp.text


@pytest.mark.asyncio
async def test_invite_requires_teams_plan(client):
    ac, mock_conn = client
    # Use cloud plan (not teams)
    token = _teams_authed(mock_conn, token_plan="cloud")

    resp = await ac.post(
        "/team/invite",
        json={"email": "extra@co.com", "role": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 403
    assert "teams_plan_required" in resp.text


# ---- accept invite ----------------------------------------------------------

@pytest.mark.asyncio
async def test_accept_invite_creates_member(client):
    ac, mock_conn = client
    now = datetime.now(timezone.utc)
    new_user_id = str(uuid4())
    inv_id = str(uuid4())

    call_count = [0]

    async def _fetchrow_side(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            # invitation lookup
            return {
                "id": inv_id,
                "workspace_id": WS_ID,
                "email": "new@co.com",
                "role": "viewer",
                "token": "tok123",
                "invited_by": USER_ID,
                "created_at": now,
                "expires_at": now + timedelta(hours=48),
                "accepted_at": None,
                "plan": "teams",
            }
        elif call_count[0] == 2:
            # user upsert
            return {"id": new_user_id}
        return None

    mock_conn.fetchrow.side_effect = _fetchrow_side

    with patch("api.team._log_activity", new_callable=AsyncMock):
        resp = await ac.post(
            "/invite/tok123/accept",
            json={"email": "new@co.com", "name": "New User"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["role"] == "viewer"
    assert data["plan"] == "teams"


@pytest.mark.asyncio
async def test_accept_expired_invite_410(client):
    ac, mock_conn = client
    now = datetime.now(timezone.utc)
    inv_id = str(uuid4())

    mock_conn.fetchrow.return_value = {
        "id": inv_id,
        "workspace_id": WS_ID,
        "email": "old@co.com",
        "role": "viewer",
        "token": "expired_tok",
        "invited_by": USER_ID,
        "created_at": now - timedelta(hours=72),
        "expires_at": now - timedelta(hours=24),  # expired
        "accepted_at": None,
        "plan": "teams",
    }

    resp = await ac.post(
        "/invite/expired_tok/accept",
        json={"email": "old@co.com", "name": "Old User"},
    )

    assert resp.status_code == 410
    assert "invitation_expired" in resp.text


# ---- RBAC -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_viewer_cannot_invite(client):
    ac, mock_conn = client
    token = _teams_authed(mock_conn, token_role="viewer")

    resp = await ac.post(
        "/team/invite",
        json={"email": "x@co.com", "role": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 403
    assert "insufficient_role" in resp.text


@pytest.mark.asyncio
async def test_admin_can_invite(client):
    ac, mock_conn = client
    token = _teams_authed(mock_conn, token_role="admin")
    mock_conn.fetchval.return_value = 2
    invite_id = str(uuid4())
    expires = datetime.now(timezone.utc) + timedelta(hours=48)

    call_count = [0]

    async def _fetchrow_side(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"id": WS_ID, "name": "Test WS", "plan": "teams", "active": True}
        elif call_count[0] == 2:
            return None
        elif call_count[0] == 3:
            return {"id": invite_id, "expires_at": expires}
        return None

    mock_conn.fetchrow.side_effect = _fetchrow_side

    with patch("api.team._send_invite_email"):
        with patch("api.team._log_activity", new_callable=AsyncMock):
            resp = await ac.post(
                "/team/invite",
                json={"email": "team@co.com", "role": "viewer"},
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_owner_can_change_roles(client):
    ac, mock_conn = client
    token = _teams_authed(mock_conn, token_role="owner")
    target_user = str(uuid4())

    call_count = [0]

    async def _fetchrow_side(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"id": WS_ID, "name": "Test WS", "plan": "teams", "active": True}
        elif call_count[0] == 2:
            return {"role": "viewer"}  # current role of target user
        return None

    mock_conn.fetchrow.side_effect = _fetchrow_side

    with patch("api.team._log_activity", new_callable=AsyncMock):
        resp = await ac.patch(
            f"/team/members/{target_user}",
            json={"role": "admin"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_admin_cannot_change_roles(client):
    ac, mock_conn = client
    token = _teams_authed(mock_conn, token_role="admin")
    target_user = str(uuid4())

    resp = await ac.patch(
        f"/team/members/{target_user}",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 403
    assert "insufficient_role" in resp.text


@pytest.mark.asyncio
async def test_cannot_remove_owner(client):
    ac, mock_conn = client
    token = _teams_authed(mock_conn, token_role="owner")
    owner_user = str(uuid4())

    call_count = [0]

    async def _fetchrow_side(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"id": WS_ID, "name": "Test WS", "plan": "teams", "active": True}
        elif call_count[0] == 2:
            return {"role": "owner"}
        return None

    mock_conn.fetchrow.side_effect = _fetchrow_side

    resp = await ac.delete(
        f"/team/members/{owner_user}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 400
    assert "cannot_remove_owner" in resp.text


# ---- activity ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_activity_log_viewer_forbidden(client):
    ac, mock_conn = client
    token = _teams_authed(mock_conn, token_role="viewer")

    resp = await ac.get(
        "/api/activity",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 403
    assert "insufficient_role" in resp.text
