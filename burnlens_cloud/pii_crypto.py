"""PII encryption + keyed-hash lookup primitives.

Phase 0 of the PII encryption plan. Provides:
  - encrypt_pii(plaintext)     → versioned ciphertext suitable for storage
  - decrypt_pii(ciphertext)    → plaintext, version-aware
  - lookup_hash(value)         → HMAC-SHA256 hex, for equality lookups

Key hierarchy:
  PII_MASTER_KEY (env, base64, 32 bytes)
    ├─ HKDF(info="pii-encrypt-v1") → Fernet encryption key
    └─ HKDF(info="pii-lookup-v1")  → HMAC-SHA256 lookup key

Rotation strategy: a v2 column can be introduced later with info="pii-encrypt-v2"
and prefix "v2:". Decryption is dispatched by prefix, so v1 and v2 can coexist
during a rolling re-encryption.

Why HMAC for lookup hashes, not plain SHA-256?
    Emails and OAuth IDs have low entropy by attacker standards. SHA-256 of
    "user@gmail.com" is brute-forceable with a wordlist. HMAC with a secret
    key makes the offline attack infeasible unless the master key leaks too.

Why Fernet, not AES-GCM directly?
    Fernet is the battle-tested high-level wrapper from pyca/cryptography:
    AES-128-CBC + HMAC-SHA256, random 128-bit IV, version byte. It is
    already used elsewhere in this codebase (OTEL key storage) so we keep
    the crypto surface small.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
from typing import Final

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

logger = logging.getLogger(__name__)


_VERSION_PREFIX_V1: Final[str] = "v1:"
_ENCRYPT_INFO_V1: Final[bytes] = b"burnlens-pii-encrypt-v1"
_LOOKUP_INFO_V1: Final[bytes] = b"burnlens-pii-lookup-v1"


class PIICryptoError(RuntimeError):
    """Raised when encryption / decryption or key setup fails."""


def _load_master_key() -> bytes:
    """Read PII_MASTER_KEY from env, base64-decode, validate length.

    Returns the raw 32-byte master key, or raises PIICryptoError in any
    situation where a production process should NOT boot.

    Accepts either raw base64 or urlsafe base64 to be lenient with how the
    operator generated it.
    """
    raw = os.getenv("PII_MASTER_KEY", "").strip()
    if not raw:
        raise PIICryptoError(
            "PII_MASTER_KEY env var is not set. Generate one with:\n"
            '  python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"'
        )
    # Try both alphabets; Fernet-style is urlsafe, operators may have used std.
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            decoded = decoder(raw.encode("utf-8"))
        except Exception:
            continue
        if len(decoded) == 32:
            return decoded
    raise PIICryptoError(
        "PII_MASTER_KEY must decode to exactly 32 bytes of base64. "
        f"Got {len(raw)} base64 chars instead."
    )


def _derive(master: bytes, info: bytes, length: int = 32) -> bytes:
    """HKDF-SHA256 subkey derivation."""
    return HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=None,
        info=info,
    ).derive(master)


# ---------------------------------------------------------------------------
# Lazy singletons. We do not read env at import time because tests may want
# to monkeypatch before the first use. First call materializes the keys.
# ---------------------------------------------------------------------------

_encrypt_key_v1: bytes | None = None
_lookup_key_v1: bytes | None = None
_fernet_v1: Fernet | None = None


def _init() -> None:
    global _encrypt_key_v1, _lookup_key_v1, _fernet_v1
    if _fernet_v1 is not None:
        return
    master = _load_master_key()
    _encrypt_key_v1 = _derive(master, _ENCRYPT_INFO_V1)
    _lookup_key_v1 = _derive(master, _LOOKUP_INFO_V1)
    # Fernet wants a urlsafe-base64-encoded 32-byte key.
    _fernet_v1 = Fernet(base64.urlsafe_b64encode(_encrypt_key_v1))


def reset_for_testing() -> None:
    """Clear memoized keys so a test can reconfigure PII_MASTER_KEY."""
    global _encrypt_key_v1, _lookup_key_v1, _fernet_v1
    _encrypt_key_v1 = None
    _lookup_key_v1 = None
    _fernet_v1 = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def encrypt_pii(plaintext: str) -> str:
    """Encrypt a PII value. Returns storage-safe string (ASCII).

    Empty/None input is a pass-through so NULL rows stay NULL.
    """
    if plaintext is None or plaintext == "":
        return plaintext
    _init()
    assert _fernet_v1 is not None  # for type checkers
    token = _fernet_v1.encrypt(plaintext.encode("utf-8")).decode("ascii")
    return _VERSION_PREFIX_V1 + token


def decrypt_pii(ciphertext: str) -> str:
    """Decrypt a value previously returned by encrypt_pii.

    Dispatches by version prefix so future rotations (v2:, v3:...) can
    coexist with already-encrypted rows.
    """
    if ciphertext is None or ciphertext == "":
        return ciphertext
    if ciphertext.startswith(_VERSION_PREFIX_V1):
        _init()
        assert _fernet_v1 is not None
        body = ciphertext[len(_VERSION_PREFIX_V1):]
        try:
            return _fernet_v1.decrypt(body.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise PIICryptoError(
                "Failed to decrypt PII: invalid token (wrong master key, "
                "corrupted ciphertext, or tampered row)"
            ) from exc
    raise PIICryptoError(
        f"Unknown PII ciphertext version: {ciphertext[:8]!r}. "
        "Either the DB row predates encryption (bug in migration) or a "
        "newer key version is required."
    )


def lookup_hash(value: str) -> str:
    """Return a deterministic HMAC-SHA256 hex digest suitable for an indexed
    equality lookup column.

    The input is normalised (stripped + lowercased) so that casing or
    whitespace variations produce the same hash — matching how the app
    already treats email comparisons (`WHERE LOWER(email) = $1`).

    Do NOT use for passwords — this is reversible under dictionary attack
    if the master key ever leaks. It is strictly a lookup tool.
    """
    if value is None:
        return value  # type: ignore[return-value]
    _init()
    assert _lookup_key_v1 is not None
    normalised = value.strip().lower().encode("utf-8")
    return hmac.new(_lookup_key_v1, normalised, hashlib.sha256).hexdigest()
