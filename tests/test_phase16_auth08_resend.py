"""Phase 16 AUTH-08 regression test — resend-verification reads identity
from the session JWT, not from a request body.

Decision refs: D-12 (signature change), D-14 (always-200), D-15 (regression).
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from burnlens_cloud.auth import router as auth_router
from burnlens_cloud.auth import verify_token as _verify_token
from burnlens_cloud.models import TokenPayload


def _make_auth_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router)
    return app


@pytest.fixture
def user_token() -> TokenPayload:
    return TokenPayload(
        workspace_id=uuid4(),
        user_id=uuid4(),
        role="owner",
        plan="cloud",
        iat=int(time.time()),
        exp=int(time.time()) + 86400,
    )


def _auth(app: FastAPI, token: TokenPayload) -> None:
    app.dependency_overrides[_verify_token] = lambda: token


@pytest.mark.asyncio
async def test_resend_verification_uses_jwt_not_body(user_token):
    app = _make_auth_app()
    _auth(app, user_token)

    unverified_row = [{
        "id": user_token.user_id,
        "email_encrypted": b"ENCRYPTED_BLOB",
        "email_verified_at": None,
    }]

    with patch("burnlens_cloud.auth.execute_query", AsyncMock(return_value=unverified_row)) as mock_exec, \
         patch("burnlens_cloud.auth.execute_insert", AsyncMock(return_value=None)), \
         patch("burnlens_cloud.pii_crypto.decrypt_pii", return_value="user@example.com") as mock_dec, \
         patch("burnlens_cloud.email.send_verify_email", AsyncMock(return_value=None)) as mock_send:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.post("/auth/resend-verification")
    assert r.status_code == 200, r.text
    # First call: SELECT email_encrypted by id from users
    first_call_sql = mock_exec.call_args_list[0].args[0]
    assert "WHERE id = $1" in first_call_sql
    assert "FROM users" in first_call_sql
    assert mock_exec.call_args_list[0].args[1] == str(user_token.user_id)
    mock_dec.assert_called_once()
    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_resend_verification_returns_200_for_already_verified(user_token):
    app = _make_auth_app()
    _auth(app, user_token)
    import datetime as _dt
    verified_row = [{
        "id": user_token.user_id,
        "email_encrypted": b"BLOB",
        "email_verified_at": _dt.datetime.utcnow(),
    }]
    with patch("burnlens_cloud.auth.execute_query", AsyncMock(return_value=verified_row)), \
         patch("burnlens_cloud.auth.execute_insert", AsyncMock(return_value=None)), \
         patch("burnlens_cloud.email.send_verify_email", AsyncMock(return_value=None)) as mock_send:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.post("/auth/resend-verification")
    assert r.status_code == 200, r.text
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_resend_verification_returns_200_for_missing_user(user_token):
    app = _make_auth_app()
    _auth(app, user_token)
    with patch("burnlens_cloud.auth.execute_query", AsyncMock(return_value=[])), \
         patch("burnlens_cloud.auth.execute_insert", AsyncMock(return_value=None)), \
         patch("burnlens_cloud.email.send_verify_email", AsyncMock(return_value=None)) as mock_send:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.post("/auth/resend-verification")
    assert r.status_code == 200, r.text
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_resend_verification_no_body_required(user_token):
    """POST with no JSON body and no Content-Type still returns 200 — proves
    the request-body shape is gone (D-12)."""
    app = _make_auth_app()
    _auth(app, user_token)
    unverified_row = [{
        "id": user_token.user_id,
        "email_encrypted": b"BLOB",
        "email_verified_at": None,
    }]
    with patch("burnlens_cloud.auth.execute_query", AsyncMock(return_value=unverified_row)), \
         patch("burnlens_cloud.auth.execute_insert", AsyncMock(return_value=None)), \
         patch("burnlens_cloud.pii_crypto.decrypt_pii", return_value="u@e.com"), \
         patch("burnlens_cloud.email.send_verify_email", AsyncMock(return_value=None)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            # No json= and no Content-Type — completely empty body
            r = await ac.post("/auth/resend-verification")
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_resend_verification_requires_session():
    """Without dependency override, verify_token returns 401."""
    app = _make_auth_app()  # No _auth() call — real verify_token runs
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        r = await ac.post("/auth/resend-verification")
    assert r.status_code in (401, 403), r.text
