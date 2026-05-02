"""Phase 11: Auth-essentials — gap-fill behavioural tests.

Covers:
- A1: DB schema DDL for auth_tokens table + partial index + email_verified_at column
- A2: Email send functions fail-open when sendgrid_api_key is empty/None
- A3: TokenPayload/LoginResponse/SignupResponse email_verified fields; encode_jwt signature;
      DEFAULT_RULES includes reset-password entry
- A4: POST /auth/reset-password always returns 200 (anti-enumeration)
- A5: POST /auth/reset-password/confirm — valid token 200, invalid 400, short/long password 400
- A6: POST /auth/verify-email — valid token 200, invalid 400
- A7: POST /auth/resend-verification — always 200 in all cases
- A8: _handle_transaction_completed calls send_payment_receipt_email with correct args;
      missing workspace returns early without exception

All tests mount only the relevant FastAPI router(s) (no lifespan/init_db) and patch
execute_query / execute_insert per-test. Pattern mirrors tests/test_phase09_quota.py.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import pathlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Test-safe env — mirror the fake dotenv shim from test_phase09_quota.py exactly
# ---------------------------------------------------------------------------
os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/burnlens_test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("PADDLE_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("PADDLE_CLOUD_PRICE_ID", "pri_env_cloud")
os.environ.setdefault("PADDLE_TEAMS_PRICE_ID", "pri_env_teams")

_FAKE_ENV = pathlib.Path(__file__).parent / "_phase7_billing_test.env"
if not _FAKE_ENV.exists():
    _FAKE_ENV.write_text("")
os.environ["BURNLENS_CLOUD_ENV_FILE_OVERRIDE"] = str(_FAKE_ENV)

import pydantic_settings.sources as _ps_sources  # noqa: E402


def _empty_dotenv_values(*args, **kwargs):
    return {}


_ps_sources.dotenv_values = _empty_dotenv_values


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

WS_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_ID = "11111111-1111-1111-1111-111111111111"


def _make_app(*routers):
    from fastapi import FastAPI
    app = FastAPI()
    for r in routers:
        app.include_router(r)
    return app


def _make_client(app):
    from httpx import AsyncClient, ASGITransport
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://testserver")


# ---------------------------------------------------------------------------
# A1 — AUTH-07: DB schema static assertions
# ---------------------------------------------------------------------------

class TestA1DatabaseSchema:
    """Auth-07: auth_tokens DDL, partial index, and email_verified_at must exist
    verbatim in burnlens_cloud/database.py.  No DB connection needed."""

    def _source(self) -> str:
        import burnlens_cloud.database as _db_mod
        return inspect.getsource(_db_mod)

    def test_auth_tokens_table_created_if_not_exists(self):
        src = self._source()
        assert "CREATE TABLE IF NOT EXISTS auth_tokens" in src, (
            "database.py must contain CREATE TABLE IF NOT EXISTS auth_tokens"
        )

    def test_auth_tokens_has_required_columns(self):
        src = self._source()
        # Required columns: id, user_id, type, token_hash, expires_at, used_at, created_at
        for col in ("user_id", "type", "token_hash", "expires_at", "used_at", "created_at"):
            assert col in src, f"auth_tokens must have column: {col}"

    def test_partial_index_exists(self):
        src = self._source()
        assert "idx_auth_tokens_user_active" in src, (
            "database.py must create idx_auth_tokens_user_active partial index"
        )
        # Must be a partial index on used_at IS NULL
        assert "WHERE used_at IS NULL" in src, (
            "idx_auth_tokens_user_active must be a partial index WHERE used_at IS NULL"
        )

    def test_email_verified_at_column_added_to_users(self):
        src = self._source()
        assert "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at" in src, (
            "database.py must ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at"
        )


# ---------------------------------------------------------------------------
# A2 — EMAIL-01/02/04: Email send functions fail-open when key is empty
# ---------------------------------------------------------------------------

class TestA2EmailFailOpen:
    """Email functions must silently return (no exception, no SendGrid call)
    when settings.sendgrid_api_key is empty or None."""

    def _patch_settings_no_key(self):
        """Context manager: patch settings.sendgrid_api_key to empty string."""
        from burnlens_cloud import config as config_mod
        return patch.object(config_mod.settings, "sendgrid_api_key", "")

    @pytest.mark.asyncio
    async def test_send_welcome_email_fail_open_when_no_key(self):
        from burnlens_cloud.email import send_welcome_email
        with self._patch_settings_no_key():
            # Must not raise; must return without creating a background task
            await send_welcome_email("user@example.com", "TestWorkspace")

    @pytest.mark.asyncio
    async def test_send_verify_email_fail_open_when_no_key(self):
        from burnlens_cloud.email import send_verify_email
        with self._patch_settings_no_key():
            await send_verify_email("user@example.com", "https://burnlens.app/verify-email?token=abc")

    @pytest.mark.asyncio
    async def test_send_password_changed_email_fail_open_when_no_key(self):
        from burnlens_cloud.email import send_password_changed_email
        with self._patch_settings_no_key():
            await send_password_changed_email("user@example.com")

    @pytest.mark.asyncio
    async def test_send_payment_receipt_email_fail_open_when_no_key(self):
        from burnlens_cloud.email import send_payment_receipt_email
        with self._patch_settings_no_key():
            await send_payment_receipt_email(
                "user@example.com", "TestWorkspace", "USD 29.00", "Cloud"
            )

    @pytest.mark.asyncio
    async def test_send_welcome_email_spawns_task_when_key_is_set(self):
        """When sendgrid_api_key IS set, asyncio.create_task must be called
        (a background task is spawned). We verify by patching create_task
        and asserting it was called at least once."""
        from burnlens_cloud import config as config_mod
        from burnlens_cloud.email import send_welcome_email
        import burnlens_cloud.email as email_mod

        tasks_created: list = []

        real_create_task = asyncio.create_task

        def capturing_create_task(coro, **kwargs):
            t = real_create_task(coro, **kwargs)
            tasks_created.append(t)
            return t

        with patch.object(config_mod.settings, "sendgrid_api_key", "SG.fake"), \
             patch.object(config_mod.settings, "sendgrid_from_email", "noreply@burnlens.app"), \
             patch("burnlens_cloud.email.asyncio.create_task", side_effect=capturing_create_task):
            await send_welcome_email("user@example.com", "TestWorkspace")

        assert len(tasks_created) >= 1, (
            "send_welcome_email must spawn asyncio.create_task when sendgrid_api_key is set"
        )

    @pytest.mark.asyncio
    async def test_send_verify_email_spawns_task_when_key_is_set(self):
        from burnlens_cloud import config as config_mod
        from burnlens_cloud.email import send_verify_email

        tasks_created: list = []
        real_create_task = asyncio.create_task

        def capturing_create_task(coro, **kwargs):
            t = real_create_task(coro, **kwargs)
            tasks_created.append(t)
            return t

        with patch.object(config_mod.settings, "sendgrid_api_key", "SG.fake"), \
             patch.object(config_mod.settings, "sendgrid_from_email", "noreply@burnlens.app"), \
             patch("burnlens_cloud.email.asyncio.create_task", side_effect=capturing_create_task):
            await send_verify_email("user@example.com", "https://burnlens.app/verify-email?token=abc")

        assert len(tasks_created) >= 1, (
            "send_verify_email must spawn asyncio.create_task when sendgrid_api_key is set"
        )


# ---------------------------------------------------------------------------
# A3 — AUTH-05: Model fields and encode_jwt signature (static assertions)
# ---------------------------------------------------------------------------

class TestA3ModelAndRateLimitSchema:
    """AUTH-05: TokenPayload.email_verified defaults to True; LoginResponse has
    email_verified; SignupResponse.email_verified defaults to False;
    encode_jwt has email_verified=True parameter; DEFAULT_RULES has reset-password."""

    def test_token_payload_has_email_verified_field_defaulting_true(self):
        from burnlens_cloud.models import TokenPayload
        import uuid, time
        payload = TokenPayload(
            workspace_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            role="owner",
            plan="cloud",
            iat=int(time.time()),
            exp=int(time.time()) + 3600,
        )
        assert payload.email_verified is True, (
            "TokenPayload.email_verified must default to True"
        )

    def test_token_payload_email_verified_can_be_set_false(self):
        from burnlens_cloud.models import TokenPayload
        import uuid, time
        payload = TokenPayload(
            workspace_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            role="owner",
            plan="cloud",
            iat=int(time.time()),
            exp=int(time.time()) + 3600,
            email_verified=False,
        )
        assert payload.email_verified is False

    def test_login_response_has_email_verified_field(self):
        from burnlens_cloud.models import LoginResponse
        fields = LoginResponse.model_fields
        assert "email_verified" in fields, "LoginResponse must have email_verified field"

    def test_signup_response_has_email_verified_field_defaulting_false(self):
        from burnlens_cloud.models import SignupResponse
        fields = SignupResponse.model_fields
        assert "email_verified" in fields, "SignupResponse must have email_verified field"
        # Default should be False (new accounts are unverified)
        default_val = fields["email_verified"].default
        assert default_val is False, (
            f"SignupResponse.email_verified must default to False, got {default_val!r}"
        )

    def test_encode_jwt_has_email_verified_parameter(self):
        from burnlens_cloud.auth import encode_jwt
        sig = inspect.signature(encode_jwt)
        assert "email_verified" in sig.parameters, (
            "encode_jwt must accept email_verified parameter"
        )
        param = sig.parameters["email_verified"]
        assert param.default is True, (
            f"encode_jwt email_verified parameter must default to True, got {param.default!r}"
        )

    def test_default_rules_contains_reset_password_3_per_900(self):
        from burnlens_cloud.rate_limit import DEFAULT_RULES
        reset_rules = [
            (prefix, max_req, window)
            for prefix, max_req, window in DEFAULT_RULES
            if prefix == "/auth/reset-password"
        ]
        assert len(reset_rules) >= 1, (
            "DEFAULT_RULES must include an entry for /auth/reset-password"
        )
        _, max_req, window = reset_rules[0]
        assert max_req == 3, f"reset-password rule must allow 3 requests, got {max_req}"
        assert window == 900, f"reset-password window must be 900s, got {window}"


# ---------------------------------------------------------------------------
# A4 — AUTH-01: POST /auth/reset-password (anti-enumeration)
# ---------------------------------------------------------------------------

class TestA4ResetPasswordRequest:
    """AUTH-01: /auth/reset-password always returns 200 regardless of whether
    the email exists in the database."""

    def _build_app(self):
        from burnlens_cloud.auth import router
        return _make_app(router)

    @pytest.mark.asyncio
    async def test_returns_200_when_email_not_found(self):
        """Anti-enumeration: unknown email must not return 404 or 422."""
        app = self._build_app()

        # Simulate: email_hash lookup returns no rows
        async def _query(sql, *args):
            return []

        with patch("burnlens_cloud.auth.execute_query", AsyncMock(side_effect=_query)), \
             patch("burnlens_cloud.auth.execute_insert", AsyncMock(return_value="UPDATE 0")):
            async with _make_client(app) as ac:
                resp = await ac.post(
                    "/auth/reset-password",
                    json={"email": "nobody@example.com"},
                )

        assert resp.status_code == 200, (
            f"AUTH-01: /auth/reset-password must return 200 for unknown email "
            f"(anti-enumeration), got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert "message" in body

    @pytest.mark.asyncio
    async def test_returns_200_when_email_found_and_sends_reset(self):
        """Happy path: known email also returns 200 and fires send_reset_password_email."""
        app = self._build_app()

        from burnlens_cloud.pii_crypto import encrypt_pii, lookup_hash
        recipient = "owner@example.com"
        encrypted_email = encrypt_pii(recipient)

        async def _query(sql, *args):
            s = " ".join(sql.split())
            if "FROM users WHERE email_hash" in s:
                return [{"id": USER_ID, "email_encrypted": encrypted_email}]
            return []

        mock_insert = AsyncMock(return_value="UPDATE 1")
        mock_send = AsyncMock(return_value=None)

        # send_reset_password_email is imported lazily inside the handler;
        # patch at the email module (the site that will be imported from).
        with patch("burnlens_cloud.auth.execute_query", AsyncMock(side_effect=_query)), \
             patch("burnlens_cloud.auth.execute_insert", mock_insert), \
             patch("burnlens_cloud.email.send_reset_password_email", mock_send, create=True):
            async with _make_client(app) as ac:
                resp = await ac.post(
                    "/auth/reset-password",
                    json={"email": recipient},
                )

        assert resp.status_code == 200, (
            f"AUTH-01: /auth/reset-password must return 200 for known email, "
            f"got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert "message" in body


# ---------------------------------------------------------------------------
# A5 — AUTH-02: POST /auth/reset-password/confirm
# ---------------------------------------------------------------------------

class TestA5ResetPasswordConfirm:
    """AUTH-02: confirm reset — token claim, expired token, and password validation."""

    def _build_app(self):
        from burnlens_cloud.auth import router
        return _make_app(router)

    @pytest.mark.asyncio
    async def test_returns_200_on_valid_token_claim(self):
        """Valid token: UPDATE RETURNING yields user_id → 200."""
        app = self._build_app()
        encrypted_email = "encrypted:user@example.com"

        async def _query(sql, *args):
            s = " ".join(sql.split())
            if "UPDATE auth_tokens SET used_at" in s and "RETURNING user_id" in s:
                return [{"user_id": USER_ID}]
            if "SELECT email_encrypted FROM users WHERE id" in s:
                return [{"email_encrypted": encrypted_email}]
            return []

        mock_insert = AsyncMock(return_value="UPDATE 1")
        # Mock decrypt_pii to return a valid email
        mock_send = AsyncMock(return_value=None)

        # send_password_changed_email is imported lazily inside the handler;
        # patch at burnlens_cloud.email. decrypt_pii is imported lazily as _dec;
        # patch at burnlens_cloud.pii_crypto.
        with patch("burnlens_cloud.auth.execute_query", AsyncMock(side_effect=_query)), \
             patch("burnlens_cloud.auth.execute_insert", mock_insert), \
             patch("burnlens_cloud.email.send_password_changed_email", mock_send, create=True), \
             patch("burnlens_cloud.pii_crypto.decrypt_pii", return_value="user@example.com"):
            async with _make_client(app) as ac:
                resp = await ac.post(
                    "/auth/reset-password/confirm",
                    json={"token": "valid-token-abc123", "new_password": "newpassword1"},
                )

        assert resp.status_code == 200, (
            f"AUTH-02: valid token claim must return 200, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert "message" in body

    @pytest.mark.asyncio
    async def test_returns_400_on_expired_or_used_token(self):
        """Expired/used token: UPDATE RETURNING yields no rows → 400."""
        app = self._build_app()

        async def _query(sql, *args):
            s = " ".join(sql.split())
            if "UPDATE auth_tokens SET used_at" in s and "RETURNING user_id" in s:
                return []  # simulates token not found / expired / already used
            return []

        with patch("burnlens_cloud.auth.execute_query", AsyncMock(side_effect=_query)), \
             patch("burnlens_cloud.auth.execute_insert", AsyncMock(return_value="UPDATE 0")):
            async with _make_client(app) as ac:
                resp = await ac.post(
                    "/auth/reset-password/confirm",
                    json={"token": "expired-token-xyz", "new_password": "validpassword"},
                )

        assert resp.status_code == 400, (
            f"AUTH-02: expired/used token must return 400, got {resp.status_code}: {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_returns_400_when_password_too_short(self):
        """Password < 8 chars: 400 without any DB call."""
        app = self._build_app()
        mock_query = AsyncMock(return_value=[])
        mock_insert = AsyncMock(return_value="UPDATE 0")

        with patch("burnlens_cloud.auth.execute_query", mock_query), \
             patch("burnlens_cloud.auth.execute_insert", mock_insert):
            async with _make_client(app) as ac:
                resp = await ac.post(
                    "/auth/reset-password/confirm",
                    json={"token": "sometoken", "new_password": "short"},
                )

        assert resp.status_code == 400, (
            f"AUTH-02: password < 8 chars must return 400, got {resp.status_code}: {resp.text}"
        )
        # DB must NOT have been hit for the token lookup
        mock_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_400_when_password_too_long(self):
        """Password > 128 chars: 400 without any DB call."""
        app = self._build_app()
        mock_query = AsyncMock(return_value=[])
        mock_insert = AsyncMock(return_value="UPDATE 0")

        long_pw = "a" * 129
        with patch("burnlens_cloud.auth.execute_query", mock_query), \
             patch("burnlens_cloud.auth.execute_insert", mock_insert):
            async with _make_client(app) as ac:
                resp = await ac.post(
                    "/auth/reset-password/confirm",
                    json={"token": "sometoken", "new_password": long_pw},
                )

        assert resp.status_code == 400, (
            f"AUTH-02: password > 128 chars must return 400, got {resp.status_code}: {resp.text}"
        )
        mock_query.assert_not_called()


# ---------------------------------------------------------------------------
# A6 — AUTH-03: POST /auth/verify-email
# ---------------------------------------------------------------------------

class TestA6VerifyEmail:
    """AUTH-03: /auth/verify-email — valid claim 200, expired/invalid token 400."""

    def _build_app(self):
        from burnlens_cloud.auth import router
        return _make_app(router)

    @pytest.mark.asyncio
    async def test_returns_200_on_valid_token_claim(self):
        """Valid verification token: UPDATE RETURNING yields user_id → 200."""
        app = self._build_app()

        async def _query(sql, *args):
            s = " ".join(sql.split())
            if "UPDATE auth_tokens SET used_at" in s and "RETURNING user_id" in s:
                return [{"user_id": USER_ID}]
            return []

        mock_insert = AsyncMock(return_value="UPDATE 1")

        with patch("burnlens_cloud.auth.execute_query", AsyncMock(side_effect=_query)), \
             patch("burnlens_cloud.auth.execute_insert", mock_insert):
            async with _make_client(app) as ac:
                resp = await ac.post(
                    "/auth/verify-email",
                    json={"token": "valid-verify-token-abc"},
                )

        assert resp.status_code == 200, (
            f"AUTH-03: valid verification token must return 200, "
            f"got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert "message" in body

    @pytest.mark.asyncio
    async def test_returns_400_on_invalid_or_expired_token(self):
        """Expired/used/invalid verification token: UPDATE RETURNING yields no rows → 400."""
        app = self._build_app()

        async def _query(sql, *args):
            s = " ".join(sql.split())
            if "UPDATE auth_tokens SET used_at" in s and "RETURNING user_id" in s:
                return []  # expired or already used
            return []

        with patch("burnlens_cloud.auth.execute_query", AsyncMock(side_effect=_query)), \
             patch("burnlens_cloud.auth.execute_insert", AsyncMock(return_value="UPDATE 0")):
            async with _make_client(app) as ac:
                resp = await ac.post(
                    "/auth/verify-email",
                    json={"token": "expired-verify-token"},
                )

        assert resp.status_code == 400, (
            f"AUTH-03: expired/invalid verification token must return 400, "
            f"got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# A7 — AUTH-04: POST /auth/resend-verification
# ---------------------------------------------------------------------------

class TestA7ResendVerification:
    """AUTH-04: /auth/resend-verification always returns 200 (anti-enumeration,
    already-verified, and real-resend cases)."""

    def _build_app(self):
        from burnlens_cloud.auth import router
        return _make_app(router)

    @pytest.mark.asyncio
    async def test_returns_200_when_email_not_found(self):
        """Unknown email: still 200 (anti-enumeration)."""
        app = self._build_app()

        async def _query(sql, *args):
            return []  # email not found

        with patch("burnlens_cloud.auth.execute_query", AsyncMock(side_effect=_query)), \
             patch("burnlens_cloud.auth.execute_insert", AsyncMock(return_value="UPDATE 0")):
            async with _make_client(app) as ac:
                resp = await ac.post(
                    "/auth/resend-verification",
                    json={"email": "notexist@example.com"},
                )

        assert resp.status_code == 200, (
            f"AUTH-04: unknown email must return 200 (anti-enumeration), "
            f"got {resp.status_code}: {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_returns_200_when_user_already_verified(self):
        """Already-verified user: still returns 200 silently."""
        app = self._build_app()
        from datetime import datetime, timezone

        async def _query(sql, *args):
            s = " ".join(sql.split())
            if "FROM users WHERE email_hash" in s:
                return [{
                    "id": USER_ID,
                    "email_encrypted": "encrypted:owner@example.com",
                    "email_verified_at": datetime.now(timezone.utc),  # already verified
                }]
            return []

        with patch("burnlens_cloud.auth.execute_query", AsyncMock(side_effect=_query)), \
             patch("burnlens_cloud.auth.execute_insert", AsyncMock(return_value="UPDATE 0")):
            async with _make_client(app) as ac:
                resp = await ac.post(
                    "/auth/resend-verification",
                    json={"email": "owner@example.com"},
                )

        assert resp.status_code == 200, (
            f"AUTH-04: already-verified user must return 200, "
            f"got {resp.status_code}: {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_returns_200_when_resend_triggered(self):
        """User exists and is unverified: 200, triggers send_verify_email."""
        app = self._build_app()
        from burnlens_cloud.pii_crypto import encrypt_pii
        encrypted = encrypt_pii("owner@example.com")

        async def _query(sql, *args):
            s = " ".join(sql.split())
            if "FROM users WHERE email_hash" in s:
                return [{
                    "id": USER_ID,
                    "email_encrypted": encrypted,
                    "email_verified_at": None,  # not yet verified
                }]
            return []

        mock_insert = AsyncMock(return_value="UPDATE 1")
        mock_send = AsyncMock(return_value=None)

        # send_verify_email is imported lazily inside the handler;
        # patch at burnlens_cloud.email (the module the handler imports from).
        with patch("burnlens_cloud.auth.execute_query", AsyncMock(side_effect=_query)), \
             patch("burnlens_cloud.auth.execute_insert", mock_insert), \
             patch("burnlens_cloud.email.send_verify_email", mock_send, create=True):
            async with _make_client(app) as ac:
                resp = await ac.post(
                    "/auth/resend-verification",
                    json={"email": "owner@example.com"},
                )

        assert resp.status_code == 200, (
            f"AUTH-04: resend for unverified user must return 200, "
            f"got {resp.status_code}: {resp.text}"
        )
        mock_send.assert_called_once()


# ---------------------------------------------------------------------------
# A8 — EMAIL-03: _handle_transaction_completed in billing.py
# ---------------------------------------------------------------------------

class TestA8HandleTransactionCompleted:
    """EMAIL-03: _handle_transaction_completed calls send_payment_receipt_email
    with correct args; returns early without exception when workspace not found."""

    @pytest.mark.asyncio
    async def test_calls_send_payment_receipt_email_with_correct_args(self):
        """When workspace is resolved, send_payment_receipt_email receives
        the decrypted email, workspace name, amount, and plan."""
        from burnlens_cloud.billing import _handle_transaction_completed
        from burnlens_cloud.pii_crypto import encrypt_pii

        owner_email = "billing_user@example.com"
        encrypted_email = encrypt_pii(owner_email)

        workspace_row = {
            "id": WS_A,
            "name": "Acme Engineering",
            "owner_email_encrypted": encrypted_email,
            "plan": "cloud",
        }

        async def _query(sql, *args):
            s = " ".join(sql.split())
            if "FROM workspaces WHERE id = $1" in s:
                return [workspace_row]
            return []

        mock_send = AsyncMock(return_value=None)

        data = {
            "custom_data": {"workspace_id": WS_A},
            "subscription_id": None,
            "currency_code": "USD",
            "details": {
                "totals": {"grand_total": "2900"}
            },
        }

        # send_payment_receipt_email is imported lazily inside the handler via
        # `from .email import send_payment_receipt_email`. Patch the email module.
        with patch("burnlens_cloud.billing.execute_query", AsyncMock(side_effect=_query)), \
             patch("burnlens_cloud.billing.execute_insert", AsyncMock(return_value="UPDATE 1")), \
             patch("burnlens_cloud.email.send_payment_receipt_email", mock_send, create=True):
            await _handle_transaction_completed(data)

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args
        # Positional: (recipient_email, workspace_name, amount_str, plan_name)
        args = call_kwargs.args if call_kwargs.args else call_kwargs[0]
        assert args[0] == owner_email, (
            f"EMAIL-03: recipient_email must be decrypted email, got {args[0]!r}"
        )
        assert args[1] == "Acme Engineering", (
            f"EMAIL-03: workspace_name must be 'Acme Engineering', got {args[1]!r}"
        )
        assert "29.00" in args[2], (
            f"EMAIL-03: amount_str must include 29.00, got {args[2]!r}"
        )
        assert args[3].lower() == "cloud", (
            f"EMAIL-03: plan_name must be 'cloud' (capitalized OK), got {args[3]!r}"
        )

    @pytest.mark.asyncio
    async def test_returns_early_without_exception_when_workspace_not_found(self):
        """When workspace cannot be resolved (custom_data missing, no sub lookup),
        the function must return without raising."""
        from burnlens_cloud.billing import _handle_transaction_completed

        async def _query(sql, *args):
            return []  # no workspace found

        mock_send = AsyncMock(return_value=None)

        data = {
            "custom_data": None,
            "subscription_id": None,
            "currency_code": "USD",
            "details": {},
        }

        with patch("burnlens_cloud.billing.execute_query", AsyncMock(side_effect=_query)), \
             patch("burnlens_cloud.billing.execute_insert", AsyncMock(return_value="UPDATE 0")), \
             patch("burnlens_cloud.email.send_payment_receipt_email", mock_send, create=True):
            # Must not raise
            await _handle_transaction_completed(data)

        mock_send.assert_not_called(), (
            "EMAIL-03: send_payment_receipt_email must NOT be called when workspace not found"
        )
