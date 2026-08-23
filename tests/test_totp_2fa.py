"""TOTP second factor: crypto primitives, enrollment, login challenge, lockout.

The assertions that matter most here are the negative ones — replay refused,
challenge token not usable as a session, recovery code single-use, lockout
after N failures. A 2FA implementation that only proves "correct code works" is
the same class of test as the pre-e98c58d cross-tenant asserts: green, and
blind to every way the feature actually fails.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pyotp
import pytest
from httpx import ASGITransport, AsyncClient

from burnlens_cloud import totp as totp_lib
from burnlens_cloud.auth import (
    MFA_CHALLENGE_TYP,
    decode_jwt,
    decode_mfa_challenge,
    encode_jwt,
    encode_mfa_challenge,
    verify_token,
)
from burnlens_cloud.models import TokenPayload


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def test_verify_accepts_the_current_code():
    secret = totp_lib.generate_secret()
    code = pyotp.TOTP(secret).now()
    assert totp_lib.verify_code(secret, code) is not None


def test_verify_rejects_a_wrong_code():
    secret = totp_lib.generate_secret()
    wrong = "000000" if pyotp.TOTP(secret).now() != "000000" else "111111"
    assert totp_lib.verify_code(secret, wrong) is None


def test_verify_rejects_malformed_input():
    secret = totp_lib.generate_secret()
    for bad in ("", "abcdef", "12345", "1234567", None):
        assert totp_lib.verify_code(secret, bad) is None


def test_verify_tolerates_one_step_of_clock_drift():
    secret = totp_lib.generate_secret()
    now = time.time()
    for offset in (-totp_lib.STEP_SECONDS, 0, totp_lib.STEP_SECONDS):
        code = pyotp.TOTP(secret).at(now + offset)
        assert totp_lib.verify_code(secret, code, now=now) is not None


def test_verify_rejects_drift_beyond_the_window():
    """Two steps out must fail — the window is a concession, not a range."""
    secret = totp_lib.generate_secret()
    now = time.time()
    far = pyotp.TOTP(secret).at(now + 3 * totp_lib.STEP_SECONDS)
    assert totp_lib.verify_code(secret, far, now=now) is None


def test_a_used_code_cannot_be_replayed():
    """The core replay defence. A valid code lives ~90s; using it must burn it.

    Without min_step this assertion passes anyway — which is why it asserts the
    step is returned and then feeds it back, rather than just calling verify
    twice.
    """
    secret = totp_lib.generate_secret()
    now = time.time()
    code = pyotp.TOTP(secret).at(now)

    first = totp_lib.verify_code(secret, code, now=now)
    assert first is not None

    replay = totp_lib.verify_code(secret, code, min_step=first.step, now=now)
    assert replay is None, "a consumed TOTP step was accepted a second time"


def test_replay_guard_still_allows_the_next_step():
    secret = totp_lib.generate_secret()
    now = time.time()
    used = totp_lib.verify_code(secret, pyotp.TOTP(secret).at(now), now=now)

    later = now + totp_lib.STEP_SECONDS
    nxt = totp_lib.verify_code(
        secret, pyotp.TOTP(secret).at(later), min_step=used.step, now=later
    )
    assert nxt is not None and nxt.step > used.step


def test_recovery_codes_are_distinct_and_high_entropy():
    codes = totp_lib.generate_recovery_codes()
    assert len(codes) == totp_lib.RECOVERY_CODE_COUNT
    assert len(set(codes)) == len(codes)
    assert all("-" in c and len(c) >= 10 for c in codes)


def test_recovery_code_hash_is_normalisation_insensitive():
    """Users retype these from a screenshot; case and dashes must not matter."""
    code = totp_lib.generate_recovery_codes(1)[0]
    variants = [code, code.lower(), code.replace("-", ""), f"  {code.lower()}  "]
    assert len({totp_lib.hash_recovery_code(v) for v in variants}) == 1


def test_recovery_code_is_not_stored_in_the_clear():
    code = totp_lib.generate_recovery_codes(1)[0]
    hashed = totp_lib.hash_recovery_code(code)
    assert code not in hashed
    assert len(hashed) == 64


def test_qr_svg_embeds_the_uri_as_a_drawable_path():
    secret = totp_lib.generate_secret()
    uri = totp_lib.provisioning_uri(secret, "user-abc123")
    svg = totp_lib.qr_svg(uri)
    assert svg.startswith("<?xml") or svg.lstrip().startswith("<svg")
    assert "<path" in svg
    # The secret must not appear as literal text in the SVG — it is encoded in
    # the module geometry, and a stray text node would leak it to any log or
    # screenshot pipeline that scrapes rendered markup.
    assert secret not in svg


def test_provisioning_uri_carries_issuer_and_secret():
    secret = totp_lib.generate_secret()
    uri = totp_lib.provisioning_uri(secret, "user-abc123")
    assert uri.startswith("otpauth://totp/")
    assert f"secret={secret}" in uri
    assert "issuer=BurnLens" in uri


# ---------------------------------------------------------------------------
# Challenge token must not be a session token
# ---------------------------------------------------------------------------


def test_challenge_token_round_trips_to_a_user_id():
    user_id = str(uuid4())
    assert decode_mfa_challenge(encode_mfa_challenge(user_id)) == user_id


def test_challenge_token_is_rejected_as_a_session_token():
    """The single most important negative test in this file.

    The challenge is signed with the same secret as a session JWT. If
    `decode_jwt` accepted it, the second factor would be optional: log in with
    a password, receive a challenge, send it as `Authorization: Bearer` and
    skip /verify entirely.
    """
    challenge = encode_mfa_challenge(str(uuid4()))
    assert decode_jwt(challenge) is None


def test_session_token_is_rejected_as_a_challenge():
    session = encode_jwt(str(uuid4()), str(uuid4()), "owner", "cloud")
    assert decode_mfa_challenge(session) is None


def test_a_forged_typ_claim_does_not_promote_a_challenge():
    """Even hand-built claims shaped like a session must fail on `typ`."""
    import jwt as _jwt

    from burnlens_cloud.config import settings

    now = int(time.time())
    forged = _jwt.encode(
        {
            "typ": MFA_CHALLENGE_TYP,
            "workspace_id": str(uuid4()),
            "user_id": str(uuid4()),
            "role": "owner",
            "plan": "enterprise",
            "iat": now,
            "exp": now + 3600,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    assert decode_jwt(forged) is None


def test_legacy_token_without_typ_still_validates():
    """Tokens minted before `typ` existed must not log everyone out on deploy."""
    import jwt as _jwt

    from burnlens_cloud.config import settings

    now = int(time.time())
    legacy = _jwt.encode(
        {
            "workspace_id": str(uuid4()),
            "user_id": str(uuid4()),
            "role": "owner",
            "plan": "cloud",
            "iat": now,
            "exp": now + 3600,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    assert decode_jwt(legacy) is not None


def test_malformed_claims_are_unauthenticated_not_a_500():
    import jwt as _jwt

    from burnlens_cloud.config import settings

    now = int(time.time())
    partial = _jwt.encode(
        {"typ": "session", "user_id": str(uuid4()), "iat": now, "exp": now + 60},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    assert decode_jwt(partial) is None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _app():
    from fastapi import FastAPI

    from burnlens_cloud.totp_api import router

    app = FastAPI()
    app.include_router(router)
    return app


def _session(user_id):
    return TokenPayload(
        workspace_id=uuid4(),
        user_id=user_id,
        role="owner",
        plan="cloud",
        iat=int(time.time()),
        exp=int(time.time()) + 3600,
    )


def _login_response():
    """A valid LoginResponse — the routes declare response_model, so a loose
    dict from the mock fails serialisation and shows up as a 500 that looks
    like a handler bug."""
    from burnlens_cloud.models import LoginResponse, WorkspaceResponse

    return LoginResponse(
        token="session-jwt",
        expires_in=86400,
        workspace=WorkspaceResponse(
            id=str(uuid4()),
            name="WS",
            owner_email="a@b.c",
            plan="cloud",
            api_key="bl_live_****abcd",
            created_at=datetime.now(timezone.utc),
            active=True,
        ),
        email_verified=True,
        role="owner",
    )


def _user_row(**overrides):
    row = {
        "id": uuid4(),
        "password_hash": None,
        "totp_secret_encrypted": None,
        "totp_confirmed_at": None,
        "totp_last_step": None,
        "totp_failed_attempts": 0,
        "totp_locked_until": None,
    }
    row.update(overrides)
    return row


class _FakeDB:
    """Routes SQL to canned results by keyword, and records the writes.

    Keyed on statement shape rather than returning one fixed value, because the
    routes issue several different queries and a single blanket return value
    would make the assertions below about the fixture rather than the handler.
    """

    def __init__(self, user_row, recovery_rows=None):
        self.user_row = user_row
        self.recovery_rows = recovery_rows if recovery_rows is not None else []
        self.writes: list[tuple[str, tuple]] = []

    async def __call__(self, sql, *args):
        normalised = " ".join(sql.split()).upper()
        if normalised.startswith("SELECT") and "FROM USERS" in normalised:
            return [self.user_row]
        if "COUNT(*)" in normalised and "TOTP_RECOVERY_CODES" in normalised:
            return [{"n": len(self.recovery_rows)}]
        if normalised.startswith("UPDATE TOTP_RECOVERY_CODES"):
            self.writes.append((normalised, args))
            return self.recovery_rows
        self.writes.append((normalised, args))
        return []


async def _client(app):
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    )


@pytest.mark.asyncio
async def test_setup_returns_qr_and_does_not_enable_2fa():
    user_id = uuid4()
    app = _app()
    app.dependency_overrides[verify_token] = lambda: _session(user_id)
    db = _FakeDB(_user_row(id=user_id))

    with patch("burnlens_cloud.totp_api.execute_query", db):
        async with await _client(app) as ac:
            r = await ac.post("/auth/2fa/setup")

    assert r.status_code == 200
    body = r.json()
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert "<path" in body["qr_svg"]

    # A secret was stored, but nothing set totp_confirmed_at.
    stored = [w for w in db.writes if "TOTP_SECRET_ENCRYPTED" in w[0]]
    assert stored, "setup did not persist a secret"
    assert not any("TOTP_CONFIRMED_AT = NOW()" in w[0] for w in db.writes)


@pytest.mark.asyncio
async def test_setup_refuses_once_2fa_is_already_enabled():
    """Otherwise a stolen session silently re-enrolls its own authenticator."""
    user_id = uuid4()
    app = _app()
    app.dependency_overrides[verify_token] = lambda: _session(user_id)
    db = _FakeDB(_user_row(id=user_id, totp_confirmed_at=datetime.now(timezone.utc)))

    with patch("burnlens_cloud.totp_api.execute_query", db):
        async with await _client(app) as ac:
            r = await ac.post("/auth/2fa/setup")

    assert r.status_code == 409


@pytest.mark.asyncio
async def test_confirm_enables_2fa_and_returns_recovery_codes_once():
    user_id = uuid4()
    secret = totp_lib.generate_secret()
    app = _app()
    app.dependency_overrides[verify_token] = lambda: _session(user_id)
    db = _FakeDB(_user_row(id=user_id, totp_secret_encrypted="enc"))

    with patch("burnlens_cloud.totp_api.execute_query", db), patch(
        "burnlens_cloud.totp_api.decrypt_pii", return_value=secret
    ):
        async with await _client(app) as ac:
            r = await ac.post("/auth/2fa/confirm", json={"code": pyotp.TOTP(secret).now()})

    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert len(body["recovery_codes"]) == totp_lib.RECOVERY_CODE_COUNT

    # Codes reach the DB only as hashes.
    inserted = [w for w in db.writes if w[0].startswith("INSERT INTO TOTP_RECOVERY_CODES")]
    assert len(inserted) == totp_lib.RECOVERY_CODE_COUNT
    hashed = {w[1][1] for w in inserted}
    assert not (set(body["recovery_codes"]) & hashed)


@pytest.mark.asyncio
async def test_confirm_rejects_a_wrong_code_and_counts_the_failure():
    user_id = uuid4()
    secret = totp_lib.generate_secret()
    app = _app()
    app.dependency_overrides[verify_token] = lambda: _session(user_id)
    db = _FakeDB(_user_row(id=user_id, totp_secret_encrypted="enc"))

    wrong = "000000" if pyotp.TOTP(secret).now() != "000000" else "111111"
    with patch("burnlens_cloud.totp_api.execute_query", db), patch(
        "burnlens_cloud.totp_api.decrypt_pii", return_value=secret
    ):
        async with await _client(app) as ac:
            r = await ac.post("/auth/2fa/confirm", json={"code": wrong})

    assert r.status_code == 400
    assert any("TOTP_FAILED_ATTEMPTS" in w[0] for w in db.writes)


@pytest.mark.asyncio
async def test_locked_account_is_refused_before_any_crypto_runs():
    user_id = uuid4()
    secret = totp_lib.generate_secret()
    app = _app()
    app.dependency_overrides[verify_token] = lambda: _session(user_id)
    db = _FakeDB(
        _user_row(
            id=user_id,
            totp_secret_encrypted="enc",
            totp_failed_attempts=totp_lib.LOCKOUT_THRESHOLD,
            totp_locked_until=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
    )

    with patch("burnlens_cloud.totp_api.execute_query", db), patch(
        "burnlens_cloud.totp_api.decrypt_pii", return_value=secret
    ):
        async with await _client(app) as ac:
            r = await ac.post("/auth/2fa/confirm", json={"code": pyotp.TOTP(secret).now()})

    assert r.status_code == 429, "a locked account accepted even a CORRECT code"


@pytest.mark.asyncio
async def test_the_nth_failure_actually_applies_the_lock():
    """Covers the moment the throttle engages, not just the state after it.

    test_locked_account_is_refused... only proves an ALREADY-locked account is
    turned away — it reads `totp_locked_until` and never consults
    `is_locked_out`. Stubbing that function to `return False` left the whole
    suite green, because nothing asserted that reaching the threshold is what
    writes the timestamp. This is that assertion.
    """
    user_id = uuid4()
    secret = totp_lib.generate_secret()
    app = _app()
    app.dependency_overrides[verify_token] = lambda: _session(user_id)
    db = _FakeDB(
        _user_row(
            id=user_id,
            totp_secret_encrypted="enc",
            totp_failed_attempts=totp_lib.LOCKOUT_THRESHOLD - 1,
        )
    )

    with patch("burnlens_cloud.totp_api.execute_query", db), patch(
        "burnlens_cloud.totp_api.decrypt_pii", return_value=secret
    ):
        async with await _client(app) as ac:
            r = await ac.post("/auth/2fa/confirm", json={"code": "000000"})

    assert r.status_code == 400
    locks = [w for w in db.writes if "TOTP_LOCKED_UNTIL" in w[0]]
    assert locks, "the failing attempt did not write a lockout"
    attempts, locked_until = locks[0][1][0], locks[0][1][1]
    assert attempts == totp_lib.LOCKOUT_THRESHOLD
    assert locked_until is not None, (
        "reaching the failure threshold left totp_locked_until NULL — the "
        "throttle counts but never engages, so brute force is unbounded"
    )


@pytest.mark.asyncio
async def test_a_failure_below_the_threshold_does_not_lock():
    user_id = uuid4()
    secret = totp_lib.generate_secret()
    app = _app()
    app.dependency_overrides[verify_token] = lambda: _session(user_id)
    db = _FakeDB(_user_row(id=user_id, totp_secret_encrypted="enc", totp_failed_attempts=0))

    with patch("burnlens_cloud.totp_api.execute_query", db), patch(
        "burnlens_cloud.totp_api.decrypt_pii", return_value=secret
    ):
        async with await _client(app) as ac:
            await ac.post("/auth/2fa/confirm", json={"code": "000000"})

    locks = [w for w in db.writes if "TOTP_LOCKED_UNTIL" in w[0]]
    assert locks and locks[0][1][0] == 1 and locks[0][1][1] is None


@pytest.mark.asyncio
async def test_expired_lockout_lets_a_correct_code_through_again():
    user_id = uuid4()
    secret = totp_lib.generate_secret()
    app = _app()
    app.dependency_overrides[verify_token] = lambda: _session(user_id)
    db = _FakeDB(
        _user_row(
            id=user_id,
            totp_secret_encrypted="enc",
            totp_failed_attempts=totp_lib.LOCKOUT_THRESHOLD,
            totp_locked_until=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
    )

    with patch("burnlens_cloud.totp_api.execute_query", db), patch(
        "burnlens_cloud.totp_api.decrypt_pii", return_value=secret
    ):
        async with await _client(app) as ac:
            r = await ac.post("/auth/2fa/confirm", json={"code": pyotp.TOTP(secret).now()})

    assert r.status_code == 200


@pytest.mark.asyncio
async def test_verify_rejects_a_challenge_for_an_account_without_2fa():
    app = _app()
    user_id = uuid4()
    db = _FakeDB(_user_row(id=user_id))

    with patch("burnlens_cloud.totp_api.execute_query", db):
        async with await _client(app) as ac:
            r = await ac.post(
                "/auth/2fa/verify",
                json={"challenge_token": encode_mfa_challenge(str(user_id)), "code": "123456"},
            )

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_verify_rejects_a_session_token_as_the_challenge():
    """A session JWT must not be spendable at the second-factor endpoint."""
    app = _app()
    session = encode_jwt(str(uuid4()), str(uuid4()), "owner", "cloud")
    db = _FakeDB(_user_row())

    with patch("burnlens_cloud.totp_api.execute_query", db):
        async with await _client(app) as ac:
            r = await ac.post(
                "/auth/2fa/verify", json={"challenge_token": session, "code": "123456"}
            )

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_verify_issues_a_session_for_a_correct_code():
    app = _app()
    user_id = uuid4()
    secret = totp_lib.generate_secret()
    db = _FakeDB(
        _user_row(
            id=user_id,
            totp_secret_encrypted="enc",
            totp_confirmed_at=datetime.now(timezone.utc),
        )
    )
    issued = AsyncMock(return_value=_login_response())

    with patch("burnlens_cloud.totp_api.execute_query", db), patch(
        "burnlens_cloud.totp_api.decrypt_pii", return_value=secret
    ), patch("burnlens_cloud.totp_api.issue_session_for_user", issued):
        async with await _client(app) as ac:
            r = await ac.post(
                "/auth/2fa/verify",
                json={
                    "challenge_token": encode_mfa_challenge(str(user_id)),
                    "code": pyotp.TOTP(secret).now(),
                },
            )

    assert r.status_code == 200
    issued.assert_awaited_once()
    # The consumed step must be burned, or the same code works again.
    assert any("TOTP_LAST_STEP" in w[0] for w in db.writes)


@pytest.mark.asyncio
async def test_verify_accepts_an_unused_recovery_code():
    app = _app()
    user_id = uuid4()
    secret = totp_lib.generate_secret()
    db = _FakeDB(
        _user_row(
            id=user_id,
            totp_secret_encrypted="enc",
            totp_confirmed_at=datetime.now(timezone.utc),
        ),
        recovery_rows=[{"id": uuid4()}],  # the UPDATE ... RETURNING matched
    )
    issued = AsyncMock(return_value=_login_response())

    with patch("burnlens_cloud.totp_api.execute_query", db), patch(
        "burnlens_cloud.totp_api.decrypt_pii", return_value=secret
    ), patch("burnlens_cloud.totp_api.issue_session_for_user", issued):
        async with await _client(app) as ac:
            r = await ac.post(
                "/auth/2fa/verify",
                json={"challenge_token": encode_mfa_challenge(str(user_id)), "code": "ABCDE-FGHJK"},
            )

    assert r.status_code == 200
    issued.assert_awaited_once()


@pytest.mark.asyncio
async def test_verify_rejects_an_already_used_recovery_code():
    """Single-use is enforced by `WHERE used_at IS NULL`; no row back = refused."""
    app = _app()
    user_id = uuid4()
    secret = totp_lib.generate_secret()
    db = _FakeDB(
        _user_row(
            id=user_id,
            totp_secret_encrypted="enc",
            totp_confirmed_at=datetime.now(timezone.utc),
        ),
        recovery_rows=[],  # UPDATE matched nothing — already spent
    )

    with patch("burnlens_cloud.totp_api.execute_query", db), patch(
        "burnlens_cloud.totp_api.decrypt_pii", return_value=secret
    ):
        async with await _client(app) as ac:
            r = await ac.post(
                "/auth/2fa/verify",
                json={"challenge_token": encode_mfa_challenge(str(user_id)), "code": "ABCDE-FGHJK"},
            )

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_recovery_consumption_is_a_conditional_update_not_a_select():
    """Guards the race: two logins presenting one code must not both succeed."""
    from burnlens_cloud.totp_api import _consume_recovery_code

    db = _FakeDB(_user_row(), recovery_rows=[{"id": uuid4()}])
    with patch("burnlens_cloud.totp_api.execute_query", db):
        assert await _consume_recovery_code(str(uuid4()), "ABCDE-FGHJK") is True

    sql = db.writes[0][0]
    assert sql.startswith("UPDATE TOTP_RECOVERY_CODES")
    assert "USED_AT IS NULL" in sql and "RETURNING" in sql


@pytest.mark.asyncio
async def test_disable_requires_both_password_and_code():
    """A live session alone must not be enough to remove the second factor."""
    import bcrypt

    user_id = uuid4()
    secret = totp_lib.generate_secret()
    pw_hash = bcrypt.hashpw(b"correct-horse", bcrypt.gensalt()).decode()
    app = _app()
    app.dependency_overrides[verify_token] = lambda: _session(user_id)

    def fresh_db():
        return _FakeDB(
            _user_row(
                id=user_id,
                password_hash=pw_hash,
                totp_secret_encrypted="enc",
                totp_confirmed_at=datetime.now(timezone.utc),
            )
        )

    # Right code, wrong password.
    db = fresh_db()
    with patch("burnlens_cloud.totp_api.execute_query", db), patch(
        "burnlens_cloud.totp_api.decrypt_pii", return_value=secret
    ):
        async with await _client(app) as ac:
            r = await ac.post(
                "/auth/2fa/disable",
                json={"password": "wrong", "code": pyotp.TOTP(secret).now()},
            )
    assert r.status_code == 400

    # Right password, wrong code.
    db = fresh_db()
    with patch("burnlens_cloud.totp_api.execute_query", db), patch(
        "burnlens_cloud.totp_api.decrypt_pii", return_value=secret
    ):
        async with await _client(app) as ac:
            r = await ac.post(
                "/auth/2fa/disable", json={"password": "correct-horse", "code": "000000"}
            )
    assert r.status_code == 400

    # Both correct.
    db = fresh_db()
    with patch("burnlens_cloud.totp_api.execute_query", db), patch(
        "burnlens_cloud.totp_api.decrypt_pii", return_value=secret
    ):
        async with await _client(app) as ac:
            r = await ac.post(
                "/auth/2fa/disable",
                json={"password": "correct-horse", "code": pyotp.TOTP(secret).now()},
            )
    assert r.status_code == 200
    assert any("TOTP_SECRET_ENCRYPTED = NULL" in w[0] for w in db.writes)
    assert any(w[0].startswith("DELETE FROM TOTP_RECOVERY_CODES") for w in db.writes)


@pytest.mark.asyncio
async def test_every_second_factor_failure_returns_the_same_message():
    """Distinct errors would enumerate which accounts carry a second factor."""
    app = _app()
    secret = totp_lib.generate_secret()
    messages = set()

    # No 2FA on the account.
    db = _FakeDB(_user_row())
    with patch("burnlens_cloud.totp_api.execute_query", db):
        async with await _client(app) as ac:
            r = await ac.post(
                "/auth/2fa/verify",
                json={"challenge_token": encode_mfa_challenge(str(uuid4())), "code": "123456"},
            )
    messages.add(r.json()["detail"])

    # Bad challenge token.
    async with await _client(app) as ac:
        r = await ac.post("/auth/2fa/verify", json={"challenge_token": "junk", "code": "123456"})
    messages.add(r.json()["detail"])

    # Enrolled, wrong code.
    user_id = uuid4()
    db = _FakeDB(
        _user_row(
            id=user_id,
            totp_secret_encrypted="enc",
            totp_confirmed_at=datetime.now(timezone.utc),
        )
    )
    with patch("burnlens_cloud.totp_api.execute_query", db), patch(
        "burnlens_cloud.totp_api.decrypt_pii", return_value=secret
    ):
        async with await _client(app) as ac:
            r = await ac.post(
                "/auth/2fa/verify",
                json={"challenge_token": encode_mfa_challenge(str(user_id)), "code": "000000"},
            )
    messages.add(r.json()["detail"])

    assert len(messages) == 1, f"second-factor failures are distinguishable: {messages}"


@pytest.mark.asyncio
async def test_status_reports_pending_separately_from_enabled():
    user_id = uuid4()
    app = _app()
    app.dependency_overrides[verify_token] = lambda: _session(user_id)

    db = _FakeDB(_user_row(id=user_id, totp_secret_encrypted="enc"))
    with patch("burnlens_cloud.totp_api.execute_query", db):
        async with await _client(app) as ac:
            r = await ac.get("/auth/2fa/status")
    assert r.json() == {"enabled": False, "pending": True, "recovery_codes_remaining": 0}

    db = _FakeDB(
        _user_row(
            id=user_id,
            totp_secret_encrypted="enc",
            totp_confirmed_at=datetime.now(timezone.utc),
        ),
        recovery_rows=[1, 2, 3],
    )
    with patch("burnlens_cloud.totp_api.execute_query", db):
        async with await _client(app) as ac:
            r = await ac.get("/auth/2fa/status")
    assert r.json() == {"enabled": True, "pending": False, "recovery_codes_remaining": 3}


# ---------------------------------------------------------------------------
# Login fork
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_with_2fa_returns_a_challenge_and_no_session_cookie():
    """The password step must not set a cookie or reveal the workspace."""
    import bcrypt
    from fastapi import FastAPI

    from burnlens_cloud.auth import router as auth_router

    user_id = uuid4()
    pw_hash = bcrypt.hashpw(b"hunter2hunter2", bcrypt.gensalt()).decode()

    async def fake_query(sql, *args):
        normalised = " ".join(sql.split()).upper()
        if "PASSWORD_HASH FROM USERS" in normalised:
            return [{"id": user_id, "password_hash": pw_hash}]
        if "TOTP_CONFIRMED_AT FROM USERS" in normalised:
            return [{"totp_confirmed_at": datetime.now(timezone.utc)}]
        return []

    app = FastAPI()
    app.include_router(auth_router)
    with patch("burnlens_cloud.auth.execute_query", fake_query), patch(
        "burnlens_cloud.auth.execute_insert", AsyncMock(return_value="")
    ), patch("burnlens_cloud.pii_crypto.lookup_hash", return_value="h"):
        async with await _client(app) as ac:
            r = await ac.post(
                "/auth/login", json={"email": "a@b.c", "password": "hunter2hunter2"}
            )

    assert r.status_code == 200
    body = r.json()
    assert body["mfa_required"] is True
    assert decode_mfa_challenge(body["challenge_token"]) == str(user_id)
    assert "workspace" not in body and "token" not in body
    assert "burnlens_session" not in r.cookies


@pytest.mark.asyncio
async def test_login_without_2fa_is_unchanged():
    """Accounts with no second factor must still get a session in one step."""
    import bcrypt
    from fastapi import FastAPI

    from burnlens_cloud.auth import router as auth_router

    user_id = uuid4()
    pw_hash = bcrypt.hashpw(b"hunter2hunter2", bcrypt.gensalt()).decode()

    async def fake_query(sql, *args):
        normalised = " ".join(sql.split()).upper()
        if "PASSWORD_HASH FROM USERS" in normalised:
            return [{"id": user_id, "password_hash": pw_hash}]
        if "TOTP_CONFIRMED_AT FROM USERS" in normalised:
            return [{"totp_confirmed_at": None}]
        return []

    issued = AsyncMock(return_value=_login_response())
    app = FastAPI()
    app.include_router(auth_router)
    with patch("burnlens_cloud.auth.execute_query", fake_query), patch(
        "burnlens_cloud.auth.execute_insert", AsyncMock(return_value="")
    ), patch("burnlens_cloud.pii_crypto.lookup_hash", return_value="h"), patch(
        "burnlens_cloud.auth.issue_session_for_user", issued
    ):
        async with await _client(app) as ac:
            r = await ac.post(
                "/auth/login", json={"email": "a@b.c", "password": "hunter2hunter2"}
            )

    assert r.status_code == 200
    issued.assert_awaited_once()
