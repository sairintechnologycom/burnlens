"""Tests for Google and GitHub SSO endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


WS_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
USER_ID = "11111111-2222-3333-4444-555555555555"
INV_ID = "22222222-3333-4444-5555-666666666666"


def _mock_httpx_google(profile: dict):
    """Return a mock httpx.AsyncClient that simulates Google OAuth responses."""
    mock_client = AsyncMock()

    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = {"access_token": "goog_access_token"}

    profile_resp = MagicMock()
    profile_resp.status_code = 200
    profile_resp.json.return_value = profile

    mock_client.post.return_value = token_resp
    mock_client.get.return_value = profile_resp
    return mock_client


def _mock_httpx_github(gh_user: dict, emails: list[dict]):
    """Return a mock httpx.AsyncClient that simulates GitHub OAuth responses."""
    mock_client = AsyncMock()

    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = {"access_token": "gh_access_token"}
    mock_client.post.return_value = token_resp

    user_resp = MagicMock()
    user_resp.status_code = 200
    user_resp.json.return_value = gh_user

    emails_resp = MagicMock()
    emails_resp.status_code = 200
    emails_resp.json.return_value = emails

    async def _get_side(url, **kwargs):
        if "emails" in url:
            return emails_resp
        return user_resp

    mock_client.get.side_effect = _get_side
    return mock_client


# ---- Google OAuth -----------------------------------------------------------

@pytest.mark.asyncio
async def test_google_redirect(client):
    """GET /auth/google redirects to accounts.google.com."""
    ac, _ = client
    resp = await ac.get("/auth/google", follow_redirects=False)
    assert resp.status_code == 302
    assert "accounts.google.com" in resp.headers["location"]


@pytest.mark.asyncio
async def test_google_callback_creates_new_user(client):
    """Google callback creates a new user when google_id not found."""
    ac, mock_conn = client
    new_user_id = str(uuid4())

    call_count = [0]

    async def _fetchrow_side(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return None  # no user by google_id
        elif call_count[0] == 2:
            return None  # no user by email
        elif call_count[0] == 3:
            return {"id": new_user_id}  # INSERT new user
        elif call_count[0] == 4:
            return None  # no workspace membership
        elif call_count[0] == 5:
            return {"id": WS_ID, "plan": "cloud"}  # owner workspace
        return None

    mock_conn.fetchrow.side_effect = _fetchrow_side

    profile = {"sub": "google_123", "email": "new@example.com", "name": "New User"}
    mock_httpx = _mock_httpx_google(profile)

    with patch("api.auth.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_httpx)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        resp = await ac.get(
            "/auth/google/callback?code=test_code&state=test_state",
            cookies={"oauth_state": "test_state"},
            follow_redirects=False,
        )

    assert resp.status_code == 302
    assert "/auth/callback.html#token=" in resp.headers["location"]


@pytest.mark.asyncio
async def test_google_callback_links_existing_email_user(client):
    """Google callback links google_id to existing user matched by email."""
    ac, mock_conn = client
    existing_user_id = str(uuid4())

    call_count = [0]

    async def _fetchrow_side(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return None  # no user by google_id
        elif call_count[0] == 2:
            return {"id": existing_user_id}  # found by email
        elif call_count[0] == 3:
            return None  # no workspace membership
        elif call_count[0] == 4:
            return {"id": WS_ID, "plan": "teams"}  # owner workspace
        return None

    mock_conn.fetchrow.side_effect = _fetchrow_side

    profile = {"sub": "google_456", "email": "existing@example.com", "name": "Existing"}
    mock_httpx = _mock_httpx_google(profile)

    with patch("api.auth.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_httpx)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        resp = await ac.get(
            "/auth/google/callback?code=test_code&state=test_state",
            cookies={"oauth_state": "test_state"},
            follow_redirects=False,
        )

    assert resp.status_code == 302
    assert "/auth/callback.html#token=" in resp.headers["location"]
    # Verify google_id was linked (execute was called for UPDATE SET google_id)
    assert mock_conn.execute.called


@pytest.mark.asyncio
async def test_google_callback_auto_accepts_pending_invitation(client):
    """Google callback auto-accepts a pending invitation for matching email."""
    ac, mock_conn = client
    new_user_id = str(uuid4())
    now = datetime.now(timezone.utc)

    call_count = [0]

    async def _fetchrow_side(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return None  # no user by google_id
        elif call_count[0] == 2:
            return None  # no user by email
        elif call_count[0] == 3:
            return {"id": new_user_id}  # INSERT new user
        elif call_count[0] == 4:
            return None  # no workspace membership
        elif call_count[0] == 5:
            return None  # not a workspace owner
        elif call_count[0] == 6:
            # Pending invitation found
            return {
                "id": INV_ID,
                "workspace_id": WS_ID,
                "role": "viewer",
                "invited_by": USER_ID,
                "plan": "teams",
            }
        return None

    mock_conn.fetchrow.side_effect = _fetchrow_side

    profile = {"sub": "google_789", "email": "invited@example.com", "name": "Invited User"}
    mock_httpx = _mock_httpx_google(profile)

    with patch("api.auth.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_httpx)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        resp = await ac.get(
            "/auth/google/callback?code=test_code&state=test_state",
            cookies={"oauth_state": "test_state"},
            follow_redirects=False,
        )

    assert resp.status_code == 302
    assert "/auth/callback.html#token=" in resp.headers["location"]
    # Verify membership was created and invitation was accepted
    execute_calls = [str(c) for c in mock_conn.execute.call_args_list]
    assert any("workspace_members" in c for c in execute_calls)
    assert any("accepted_at" in c for c in execute_calls)


# ---- GitHub OAuth -----------------------------------------------------------

@pytest.mark.asyncio
async def test_github_redirect(client):
    """GET /auth/github redirects to github.com."""
    ac, _ = client
    resp = await ac.get("/auth/github", follow_redirects=False)
    assert resp.status_code == 302
    assert "github.com/login/oauth/authorize" in resp.headers["location"]


@pytest.mark.asyncio
async def test_github_callback_creates_new_user(client):
    """GitHub callback creates a new user when github_id not found."""
    ac, mock_conn = client
    new_user_id = str(uuid4())

    call_count = [0]

    async def _fetchrow_side(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return None  # no user by github_id
        elif call_count[0] == 2:
            return None  # no user by email
        elif call_count[0] == 3:
            return {"id": new_user_id}  # INSERT new user
        elif call_count[0] == 4:
            return None  # no workspace membership
        elif call_count[0] == 5:
            return {"id": WS_ID, "plan": "cloud"}  # owner workspace
        return None

    mock_conn.fetchrow.side_effect = _fetchrow_side

    gh_user = {"id": 12345, "login": "ghuser", "name": "GH User"}
    emails = [{"email": "ghuser@example.com", "primary": True, "verified": True}]
    mock_httpx = _mock_httpx_github(gh_user, emails)

    with patch("api.auth.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_httpx)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        resp = await ac.get(
            "/auth/github/callback?code=gh_test_code&state=test_state",
            cookies={"oauth_state": "test_state"},
            follow_redirects=False,
        )

    assert resp.status_code == 302
    assert "/auth/callback.html#token=" in resp.headers["location"]


@pytest.mark.asyncio
async def test_github_callback_upserts_github_id(client):
    """GitHub callback links github_id to existing user matched by email."""
    ac, mock_conn = client
    existing_user_id = str(uuid4())

    call_count = [0]

    async def _fetchrow_side(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return None  # no user by github_id
        elif call_count[0] == 2:
            return {"id": existing_user_id}  # found by email
        elif call_count[0] == 3:
            return None  # no workspace membership
        elif call_count[0] == 4:
            return {"id": WS_ID, "plan": "cloud"}  # owner workspace
        return None

    mock_conn.fetchrow.side_effect = _fetchrow_side

    gh_user = {"id": 67890, "login": "existing_gh", "name": "Existing GH"}
    emails = [{"email": "existing@example.com", "primary": True, "verified": True}]
    mock_httpx = _mock_httpx_github(gh_user, emails)

    with patch("api.auth.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_httpx)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        resp = await ac.get(
            "/auth/github/callback?code=gh_test_code&state=test_state",
            cookies={"oauth_state": "test_state"},
            follow_redirects=False,
        )

    assert resp.status_code == 302
    assert "/auth/callback.html#token=" in resp.headers["location"]
    # Verify github_id was linked via UPDATE
    assert mock_conn.execute.called


@pytest.mark.asyncio
async def test_sso_without_workspace_redirects_to_signup(client):
    """SSO user with no workspace or invitation is redirected to signup."""
    ac, mock_conn = client
    new_user_id = str(uuid4())

    call_count = [0]

    async def _fetchrow_side(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return None  # no user by google_id
        elif call_count[0] == 2:
            return None  # no user by email
        elif call_count[0] == 3:
            return {"id": new_user_id}  # INSERT new user
        elif call_count[0] == 4:
            return None  # no workspace membership
        elif call_count[0] == 5:
            return None  # not a workspace owner
        elif call_count[0] == 6:
            return None  # no pending invitation
        return None

    mock_conn.fetchrow.side_effect = _fetchrow_side

    profile = {"sub": "google_nows", "email": "nows@example.com", "name": "No WS"}
    mock_httpx = _mock_httpx_google(profile)

    with patch("api.auth.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_httpx)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        resp = await ac.get(
            "/auth/google/callback?code=test_code&state=test_state",
            cookies={"oauth_state": "test_state"},
            follow_redirects=False,
        )

    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "/signup" in location
    assert "email=nows%40example.com" in location
    assert "sso=google" in location


@pytest.mark.asyncio
async def test_csrf_state_mismatch_rejected(client):
    """Callback rejects request when state param doesn't match cookie."""
    ac, _ = client

    resp = await ac.get(
        "/auth/google/callback?code=test_code&state=bad_state",
        cookies={"oauth_state": "correct_state"},
    )

    assert resp.status_code == 400
    assert "CSRF" in resp.text or "state" in resp.text.lower()
