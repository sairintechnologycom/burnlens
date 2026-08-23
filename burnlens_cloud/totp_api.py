"""TOTP second-factor routes: enrollment, confirmation, login challenge, disable.

Per-user and opt-in. A workspace-wide mandate is deliberately NOT here — it
brings its own lockout surface (an owner who enforces before enrolling, invited
members mid-flow) and belongs in its own change.

Route split:

  POST /auth/2fa/setup    (session) mint a secret, return QR — 2FA NOT yet on
  POST /auth/2fa/confirm  (session) prove possession, turn it on, hand back
                          recovery codes exactly once
  GET  /auth/2fa/status   (session) what the settings page renders from
  POST /auth/2fa/disable  (session) requires password AND a current code
  POST /auth/2fa/verify   (challenge token, NOT a session) the login second step

Only `/verify` is reachable without a full session, and it accepts only the
short-lived `mfa_challenge` token minted by /auth/login — never a session
cookie, never a bearer JWT.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import bcrypt as _bcrypt
from fastapi import APIRouter, Depends, HTTPException, Response

from . import totp as totp_lib
from .auth import decode_mfa_challenge, issue_session_for_user, verify_token
from .database import execute_query
from .models import (
    LoginResponse,
    TokenPayload,
    TOTPConfirmRequest,
    TOTPConfirmResponse,
    TOTPDisableRequest,
    TOTPSetupResponse,
    TOTPStatusResponse,
    TOTPVerifyRequest,
)
from .pii_crypto import decrypt_pii, encrypt_pii

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/2fa", tags=["auth"])

# One message for every second-factor failure. Distinguishing "wrong code" from
# "no 2FA enrolled" from "bad challenge" tells an attacker holding a stolen
# password exactly which accounts have a second factor and how far they got.
_INVALID = "Invalid or expired verification code"


async def _load_user_totp(user_id: str):
    rows = await execute_query(
        """
        SELECT id, password_hash, totp_secret_encrypted, totp_confirmed_at,
               totp_last_step, totp_failed_attempts, totp_locked_until
        FROM users WHERE id = $1
        """,
        user_id,
    )
    return rows[0] if rows else None


def _is_locked(row) -> bool:
    locked_until = row["totp_locked_until"]
    if not locked_until:
        return False
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    return locked_until > datetime.now(timezone.utc)


async def _register_failure(user_id: str, attempts: int) -> None:
    """Count a failed attempt and lock the factor once over threshold.

    Without this a six-digit code is guessable inside its own validity window
    by anyone who can send requests fast enough.
    """
    attempts += 1
    locked_until = None
    if totp_lib.is_locked_out(attempts):
        locked_until = datetime.now(timezone.utc) + timedelta(
            seconds=totp_lib.LOCKOUT_SECONDS
        )
    await execute_query(
        "UPDATE users SET totp_failed_attempts = $1, totp_locked_until = $2 WHERE id = $3",
        attempts,
        locked_until,
        user_id,
    )


async def _clear_failures(user_id: str, step: int) -> None:
    """Reset the throttle and burn the consumed step (replay defence)."""
    await execute_query(
        """
        UPDATE users
        SET totp_failed_attempts = 0, totp_locked_until = NULL, totp_last_step = $1
        WHERE id = $2
        """,
        step,
        user_id,
    )


async def _consume_recovery_code(user_id: str, code: str) -> bool:
    """Spend a single-use recovery code. True if one matched and was unused.

    The UPDATE ... WHERE used_at IS NULL RETURNING is what makes it single-use:
    two concurrent requests presenting the same code race on the row and exactly
    one gets a row back. A SELECT-then-UPDATE would let both through.
    """
    rows = await execute_query(
        """
        UPDATE totp_recovery_codes
        SET used_at = now()
        WHERE user_id = $1 AND code_hash = $2 AND used_at IS NULL
        RETURNING id
        """,
        user_id,
        totp_lib.hash_recovery_code(code),
    )
    return bool(rows)


# ---------------------------------------------------------------------------
# Enrollment (full session required)
# ---------------------------------------------------------------------------


@router.post("/setup", response_model=TOTPSetupResponse)
async def setup_totp(token: TokenPayload = Depends(verify_token)):
    """Mint a secret and return enrollment material. Does NOT enable 2FA.

    Re-running this before confirming replaces the pending secret, which is the
    correct behaviour for "I closed the tab / lost the QR". It refuses once 2FA
    is confirmed so an attacker with a live session cannot silently re-enroll
    their own authenticator and keep access after the victim's password reset.
    """
    user_id = str(token.user_id)
    row = await _load_user_totp(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    if row["totp_confirmed_at"]:
        raise HTTPException(
            status_code=409,
            detail={"error": "totp_already_enabled"},
        )

    secret = totp_lib.generate_secret()
    await execute_query(
        "UPDATE users SET totp_secret_encrypted = $1 WHERE id = $2",
        encrypt_pii(secret),
        user_id,
    )

    # The account label is what shows in the authenticator app. user_id rather
    # than the email address: the email is encrypted at rest and decrypting it
    # to build a QR would put plaintext PII in a response body for no gain.
    uri = totp_lib.provisioning_uri(secret, account_label=f"user-{user_id[:8]}")
    return TOTPSetupResponse(secret=secret, otpauth_uri=uri, qr_svg=totp_lib.qr_svg(uri))


@router.post("/confirm", response_model=TOTPConfirmResponse)
async def confirm_totp(
    body: TOTPConfirmRequest, token: TokenPayload = Depends(verify_token)
):
    """Prove possession of the pending secret, then turn 2FA on.

    Returns the recovery codes, once. They are stored hashed and cannot be
    shown again — a user who loses both the authenticator and these codes needs
    support, which is exactly why they are surfaced this prominently.
    """
    user_id = str(token.user_id)
    row = await _load_user_totp(user_id)
    if row is None or not row["totp_secret_encrypted"]:
        raise HTTPException(status_code=400, detail={"error": "totp_setup_not_started"})
    if row["totp_confirmed_at"]:
        raise HTTPException(status_code=409, detail={"error": "totp_already_enabled"})
    if _is_locked(row):
        raise HTTPException(status_code=429, detail={"error": "totp_locked"})

    secret = decrypt_pii(row["totp_secret_encrypted"])
    verified = totp_lib.verify_code(secret, body.code, min_step=row["totp_last_step"])
    if verified is None:
        await _register_failure(user_id, row["totp_failed_attempts"] or 0)
        raise HTTPException(status_code=400, detail=_INVALID)

    codes = totp_lib.generate_recovery_codes()
    await execute_query(
        """
        UPDATE users
        SET totp_confirmed_at = now(), totp_failed_attempts = 0,
            totp_locked_until = NULL, totp_last_step = $1
        WHERE id = $2
        """,
        verified.step,
        user_id,
    )
    # Clear any codes from a previous enrollment so a disable/re-enable cycle
    # cannot be unlocked by a code printed out two enrollments ago.
    await execute_query("DELETE FROM totp_recovery_codes WHERE user_id = $1", user_id)
    for code in codes:
        await execute_query(
            "INSERT INTO totp_recovery_codes (user_id, code_hash) VALUES ($1, $2)",
            user_id,
            totp_lib.hash_recovery_code(code),
        )

    logger.info("2fa.enabled user=%s", user_id)
    return TOTPConfirmResponse(enabled=True, recovery_codes=codes)


@router.get("/status", response_model=TOTPStatusResponse)
async def totp_status(token: TokenPayload = Depends(verify_token)):
    user_id = str(token.user_id)
    row = await _load_user_totp(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")

    remaining = await execute_query(
        "SELECT count(*) AS n FROM totp_recovery_codes WHERE user_id = $1 AND used_at IS NULL",
        user_id,
    )
    return TOTPStatusResponse(
        enabled=bool(row["totp_confirmed_at"]),
        pending=bool(row["totp_secret_encrypted"]) and not row["totp_confirmed_at"],
        recovery_codes_remaining=int(remaining[0]["n"]) if remaining else 0,
    )


@router.post("/disable")
async def disable_totp(
    body: TOTPDisableRequest, token: TokenPayload = Depends(verify_token)
):
    """Turn 2FA off. Requires the password AND a current code.

    Both, deliberately. A live session alone must not be enough: session theft
    is precisely the thing the second factor is there to survive, and a
    one-click disable would hand it straight back.
    """
    user_id = str(token.user_id)
    row = await _load_user_totp(user_id)
    if row is None or not row["totp_confirmed_at"]:
        raise HTTPException(status_code=400, detail={"error": "totp_not_enabled"})
    if _is_locked(row):
        raise HTTPException(status_code=429, detail={"error": "totp_locked"})

    if not row["password_hash"] or not _bcrypt.checkpw(
        body.password.encode("utf-8"), row["password_hash"].encode("utf-8")
    ):
        await _register_failure(user_id, row["totp_failed_attempts"] or 0)
        raise HTTPException(status_code=400, detail=_INVALID)

    secret = decrypt_pii(row["totp_secret_encrypted"])
    if totp_lib.verify_code(secret, body.code, min_step=row["totp_last_step"]) is None:
        await _register_failure(user_id, row["totp_failed_attempts"] or 0)
        raise HTTPException(status_code=400, detail=_INVALID)

    await execute_query(
        """
        UPDATE users
        SET totp_secret_encrypted = NULL, totp_confirmed_at = NULL,
            totp_last_step = NULL, totp_failed_attempts = 0, totp_locked_until = NULL
        WHERE id = $1
        """,
        user_id,
    )
    await execute_query("DELETE FROM totp_recovery_codes WHERE user_id = $1", user_id)

    logger.info("2fa.disabled user=%s", user_id)
    return {"enabled": False}


# ---------------------------------------------------------------------------
# Login second step (challenge token only — NOT a session)
# ---------------------------------------------------------------------------


@router.post("/verify", response_model=LoginResponse)
async def verify_totp(body: TOTPVerifyRequest, response: Response):
    """Trade a valid challenge token + code for a real session.

    Accepts a TOTP code or a single-use recovery code in the same field: users
    reaching for a recovery code are already locked out of their authenticator
    and should not have to find a different form to do it.
    """
    user_id = decode_mfa_challenge(body.challenge_token)
    if not user_id:
        raise HTTPException(status_code=401, detail=_INVALID)

    row = await _load_user_totp(user_id)
    if row is None or not row["totp_confirmed_at"]:
        raise HTTPException(status_code=401, detail=_INVALID)
    if _is_locked(row):
        raise HTTPException(status_code=429, detail={"error": "totp_locked"})

    secret = decrypt_pii(row["totp_secret_encrypted"])
    verified = totp_lib.verify_code(secret, body.code, min_step=row["totp_last_step"])
    if verified is not None:
        await _clear_failures(user_id, verified.step)
    elif await _consume_recovery_code(user_id, body.code):
        logger.info("2fa.recovery_code_used user=%s", user_id)
        await execute_query(
            "UPDATE users SET totp_failed_attempts = 0, totp_locked_until = NULL WHERE id = $1",
            user_id,
        )
    else:
        await _register_failure(user_id, row["totp_failed_attempts"] or 0)
        raise HTTPException(status_code=401, detail=_INVALID)

    await execute_query(
        "UPDATE users SET last_login = $1 WHERE id = $2",
        datetime.now(timezone.utc).replace(tzinfo=None),
        user_id,
    )
    return await issue_session_for_user(user_id, response)
