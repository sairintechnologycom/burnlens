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


@pytest.mark.asyncio
async def test_resend_verification_handles_null_email_encrypted(user_token):
    """CR-02: NULL email_encrypted (rotated PII master key / partial backfill / dev row)
    MUST NOT 500. Endpoint returns the standard always-200 envelope and does NOT call
    send_verify_email. Enumeration safety per D-14 + CLAUDE.md fail-open posture."""
    app = _make_auth_app()
    _auth(app, user_token)

    null_blob_row = [{
        "id": user_token.user_id,
        "email_encrypted": None,         # ← the failure mode
        "email_verified_at": None,
    }]

    # NB: decrypt_pii is imported INSIDE resend_verification (auth.py:~1149
    # via `from .pii_crypto import decrypt_pii as _dec`), so patching at the
    # source module (burnlens_cloud.pii_crypto.decrypt_pii) works because
    # the local import re-resolves the name on every call. If a future
    # refactor hoists the import to module scope, change the patch target
    # to 'burnlens_cloud.auth._dec' (or whichever alias the module binds).
    with patch("burnlens_cloud.auth.execute_query", AsyncMock(return_value=null_blob_row)), \
         patch("burnlens_cloud.auth.execute_insert", AsyncMock(return_value=None)), \
         patch("burnlens_cloud.pii_crypto.decrypt_pii") as mock_dec, \
         patch("burnlens_cloud.email.send_verify_email", AsyncMock(return_value=None)) as mock_send:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.post("/auth/resend-verification")

    assert r.status_code == 200, r.text
    assert r.json() == {"message": "If applicable, a verification email has been sent."}
    mock_dec.assert_not_called()        # NULL guard hits BEFORE decrypt
    mock_send.assert_not_called()       # no email attempted with empty recipient


@pytest.mark.asyncio
async def test_resend_verification_handles_decrypt_error(user_token):
    """CR-02 (corollary): decrypt_pii raising (corrupted blob, wrong master key) MUST
    NOT 500. Endpoint returns 200, send_verify_email NOT called.

    NB: decrypt_pii is imported INSIDE resend_verification (auth.py:~1149 via
    `from .pii_crypto import decrypt_pii as _dec`), so patching at the source
    module (burnlens_cloud.pii_crypto.decrypt_pii) works because the local
    import re-resolves the name on every call. If a future refactor hoists
    the import to module scope, change the patch target to
    'burnlens_cloud.auth._dec' (or whichever alias the module binds).
    """
    app = _make_auth_app()
    _auth(app, user_token)

    corrupt_row = [{
        "id": user_token.user_id,
        "email_encrypted": b"CORRUPTED_BLOB",
        "email_verified_at": None,
    }]

    with patch("burnlens_cloud.auth.execute_query", AsyncMock(return_value=corrupt_row)), \
         patch("burnlens_cloud.auth.execute_insert", AsyncMock(return_value=None)), \
         patch("burnlens_cloud.pii_crypto.decrypt_pii", side_effect=ValueError("decrypt failed")), \
         patch("burnlens_cloud.email.send_verify_email", AsyncMock(return_value=None)) as mock_send:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.post("/auth/resend-verification")

    assert r.status_code == 200, r.text
    assert r.json() == {"message": "If applicable, a verification email has been sent."}
    mock_send.assert_not_called()
