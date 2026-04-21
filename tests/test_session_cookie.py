"""C-3: JWT session cookie transport.

Verifies the cookie-based auth path added so browsers stop reading the JWT
from `localStorage`. We spin up a minimal FastAPI app that mounts the auth
router and a small authed probe route, then exercise:

  1. `POST /auth/login` sets `burnlens_session` with HttpOnly + SameSite=Lax.
  2. A subsequent request with only that cookie passes `verify_token`.
  3. `Authorization: Bearer <jwt>` still works (CLI compatibility).
  4. `POST /auth/logout` emits a Set-Cookie that clears `burnlens_session`.
  5. Missing both transports returns 401.
"""
from __future__ import annotations

import os
import pathlib
from unittest.mock import AsyncMock, patch

import pytest

# Mirror the isolation other burnlens_cloud tests use: redirect the env loader
# to an empty file so proxy-only vars from the project `.env` don't poison
# Settings validation.
os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/burnlens_test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests-32ch")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault(
    "PII_MASTER_KEY",
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
)
_FAKE_ENV = pathlib.Path(__file__).parent / "_session_cookie_test.env"
if not _FAKE_ENV.exists():
    _FAKE_ENV.write_text("")

import pydantic_settings.sources as _ps_sources  # noqa: E402


def _empty_dotenv_values(*args, **kwargs):
    return {}


_ps_sources.dotenv_values = _empty_dotenv_values


WS_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_ID = "11111111-1111-1111-1111-111111111111"


def _build_app():
    from fastapi import Depends, FastAPI

    from burnlens_cloud.auth import router as auth_router, verify_token
    from burnlens_cloud.models import TokenPayload

    app = FastAPI()
    app.include_router(auth_router)

    @app.get("/_probe")
    async def probe(payload: TokenPayload = Depends(verify_token)):
        return {"workspace_id": str(payload.workspace_id), "role": payload.role}

    return app


@pytest.fixture
def app_client():
    from httpx import ASGITransport, AsyncClient

    app = _build_app()
    transport = ASGITransport(app=app)

    async def _factory():
        return AsyncClient(transport=transport, base_url="http://testserver")

    return _factory


@pytest.mark.asyncio
async def test_login_sets_httponly_cookie_and_authorizes_subsequent_request(app_client):
    """End-to-end: login → cookie → probe accepts cookie-only request."""
    from burnlens_cloud.auth import SESSION_COOKIE_NAME

    from burnlens_cloud.pii_crypto import encrypt_pii
    owner_email_enc = encrypt_pii("user@example.com")
    rows_seq = [
        # users SELECT by email_hash — return password_hash hit.
        [{"id": USER_ID, "password_hash": _bcrypt_hash("pw123456")}],
        # workspace_members JOIN workspaces
        [{
            "workspace_id": WS_ID,
            "role": "owner",
            "id": WS_ID,
            "name": "WS",
            "owner_email_encrypted": owner_email_enc,
            "plan": "cloud",
            "api_key_last4": "abcd",
            "created_at": __import__("datetime").datetime.utcnow(),
            "active": True,
        }],
    ]

    async def fake_execute_query(sql, *args):
        return rows_seq.pop(0)

    async def fake_execute_insert(sql, *args):
        return None

    with patch("burnlens_cloud.auth.execute_query", side_effect=fake_execute_query), \
         patch("burnlens_cloud.auth.execute_insert", side_effect=fake_execute_insert):
        async with await app_client() as ac:
            resp = await ac.post(
                "/auth/login",
                json={"email": "user@example.com", "password": "pw123456"},
            )
            assert resp.status_code == 200, resp.text

            # Cookie is present, HttpOnly, SameSite=Lax.
            set_cookie = (resp.headers.get("set-cookie") or "").lower()
            assert f"{SESSION_COOKIE_NAME.lower()}=" in set_cookie
            assert "httponly" in set_cookie
            assert "samesite=lax" in set_cookie
            # In dev/test environment, cookie must NOT be marked Secure so it
            # works on http://localhost; the Secure flag is production-only.
            assert "secure" not in set_cookie

            # Probe using ONLY the cookie — httpx carries it automatically.
            probe_resp = await ac.get("/_probe")
            assert probe_resp.status_code == 200
            assert probe_resp.json()["workspace_id"] == WS_ID


@pytest.mark.asyncio
async def test_authorization_bearer_still_works_for_cli(app_client):
    """Header transport must keep working so the CLI keeps authenticating."""
    from burnlens_cloud.auth import encode_jwt

    token = encode_jwt(WS_ID, USER_ID, "owner", "cloud")

    async with await app_client() as ac:
        resp = await ac.get(
            "/_probe",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["workspace_id"] == WS_ID


@pytest.mark.asyncio
async def test_probe_without_any_auth_returns_401(app_client):
    async with await app_client() as ac:
        resp = await ac.get("/_probe")
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout_clears_cookie(app_client):
    from burnlens_cloud.auth import SESSION_COOKIE_NAME

    async with await app_client() as ac:
        resp = await ac.post("/auth/logout")
        assert resp.status_code == 200
        set_cookie = resp.headers.get("set-cookie") or ""
        assert f"{SESSION_COOKIE_NAME}=" in set_cookie
        # Starlette expresses deletion as Max-Age=0 / expires in the past.
        assert "Max-Age=0" in set_cookie or "max-age=0" in set_cookie or "01 Jan 1970" in set_cookie


def _bcrypt_hash(pw: str) -> str:
    import bcrypt
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
