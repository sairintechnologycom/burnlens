"""TOTP (RFC 6238) second factor: secrets, verification, recovery codes, QR.

Pure logic — no FastAPI, no SQL. `totp_api.py` owns the routes and the
persistence; keeping the crypto here means the security-relevant parts are
testable without a request or a database.

Three things in here are easy to get wrong and are the reason this is not
fifteen lines of `hmac`:

* **Replay.** A TOTP code stays valid for its whole step (and, with drift
  tolerance, for the neighbouring ones). Without a record of the last step a
  user consumed, a code shoulder-surfed or captured from a proxy log can be
  replayed for up to 90 seconds. `verify_code` returns the step it matched so
  the caller can persist it and refuse anything at or below it.
* **Brute force.** Six digits is a million combinations, but a valid code lives
  for ~90s and an unthrottled attacker gets unlimited guesses inside that
  window. Attempts must be counted and locked out; see `LOCKOUT_*`.
* **Comparison timing.** `pyotp.TOTP.verify` uses `hmac.compare_digest`
  internally. Do not replace it with `==`.
"""

from __future__ import annotations

import hashlib
import io
import secrets
import time
from dataclasses import dataclass

import pyotp
import qrcode
import qrcode.image.svg

# RFC 6238 defaults. 30s steps, 6 digits, SHA-1 — what every authenticator app
# assumes when it scans a bare otpauth:// URI. Changing these silently breaks
# enrollment for anyone using Google Authenticator, which does not read the
# algorithm/digits parameters at all.
STEP_SECONDS = 30
DIGITS = 6

# Accept the immediately preceding and following step. One step of tolerance
# covers ordinary clock skew and the user typing the last digit as the code
# rolls; more than one widens the replay window for no real usability gain.
DRIFT_STEPS = 1

RECOVERY_CODE_COUNT = 10
# 10 chars of Crockford-ish base32 ≈ 50 bits. These are bearer credentials that
# bypass the second factor entirely, so they get real entropy, not 6 digits.
RECOVERY_CODE_BYTES = 7

# Failed-attempt throttle. Five tries, then a hard 15-minute lock on the
# account's second factor. A legitimate user mistypes once or twice; an
# attacker needs ~100k tries to have a coin-flip chance inside a code's life.
LOCKOUT_THRESHOLD = 5
LOCKOUT_SECONDS = 15 * 60

ISSUER = "BurnLens"

# Excludes I, L, O, U and digits that look like them — recovery codes get read
# off a screen and typed back, often from a screenshot or a printout.
_RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"


class TOTPError(Exception):
    """Raised for malformed secrets or codes — never for a wrong-but-valid code."""


@dataclass(frozen=True)
class VerifiedCode:
    """A successful verification, and the step it consumed.

    `step` must be persisted by the caller and passed back as `min_step` on the
    next attempt. That is the whole replay defence; a caller that ignores it has
    a working-looking 2FA with none of the protection.
    """

    step: int


def generate_secret() -> str:
    """Return a fresh base32 TOTP secret (160 bits, per RFC 4226 §4)."""
    return pyotp.random_base32()


def provisioning_uri(secret: str, account_label: str) -> str:
    """Return the otpauth:// URI an authenticator app scans or imports."""
    return pyotp.TOTP(secret, digits=DIGITS, interval=STEP_SECONDS).provisioning_uri(
        name=account_label, issuer_name=ISSUER
    )


def qr_svg(uri: str) -> str:
    """Render `uri` as a standalone SVG string.

    SVG rather than PNG so the response is text (no base64 bloat, no image
    host) and scales in the settings panel. `SvgPathImage` emits a single
    <path>, which keeps it small enough to inline in JSON.
    """
    image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue().decode("utf-8")


def current_step(now: float | None = None) -> int:
    return int((now if now is not None else time.time()) // STEP_SECONDS)


def verify_code(
    secret: str,
    code: str,
    *,
    min_step: int | None = None,
    now: float | None = None,
) -> VerifiedCode | None:
    """Verify `code` against `secret`, refusing replays at or below `min_step`.

    Returns the matched step on success, None on any failure. `min_step` is the
    step of the last code this user successfully consumed: a code matching that
    step or an earlier one is a replay, not an authentication, and is rejected
    even though the HMAC is perfectly valid.
    """
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != DIGITS:
        return None

    now = now if now is not None else time.time()
    totp = pyotp.TOTP(secret, digits=DIGITS, interval=STEP_SECONDS)

    for offset in range(-DRIFT_STEPS, DRIFT_STEPS + 1):
        candidate_time = now + (offset * STEP_SECONDS)
        # valid_window=0: the drift loop is explicit here so the matched step is
        # known. Letting pyotp scan the window would verify the code but not say
        # WHICH step matched, leaving nothing to persist against replay.
        if totp.verify(code, for_time=candidate_time, valid_window=0):
            step = current_step(candidate_time)
            if min_step is not None and step <= min_step:
                return None
            return VerifiedCode(step=step)
    return None


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """Return `count` single-use recovery codes in `XXXXX-XXXXX` form."""
    codes = []
    for _ in range(count):
        raw = "".join(
            secrets.choice(_RECOVERY_ALPHABET) for _ in range(RECOVERY_CODE_BYTES + 3)
        )
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def normalise_recovery_code(code: str) -> str:
    """Canonicalise user input before hashing: upper, no spaces or dashes."""
    return (code or "").strip().upper().replace("-", "").replace(" ", "")


def hash_recovery_code(code: str) -> str:
    """Hash a recovery code for storage.

    SHA-256 rather than bcrypt, deliberately: these are 50-bit random strings,
    not user-chosen passwords, so there is no dictionary to defend against and a
    slow KDF would only add latency to the login path. Same reasoning as
    `hash_api_key` in auth.py.
    """
    return hashlib.sha256(normalise_recovery_code(code).encode("utf-8")).hexdigest()


def is_locked_out(failed_attempts: int) -> bool:
    return failed_attempts >= LOCKOUT_THRESHOLD
