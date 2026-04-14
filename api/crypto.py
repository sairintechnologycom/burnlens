"""Fernet encryption helpers for sensitive data (OTEL API keys)."""
from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken

from . import config

logger = logging.getLogger(__name__)


def _get_cipher() -> Fernet:
    """Return a Fernet cipher from the OTEL_ENCRYPTION_KEY env var."""
    key = config.OTEL_ENCRYPTION_KEY
    if not key:
        raise ValueError(
            "OTEL_ENCRYPTION_KEY not set. "
            "Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: str) -> str:
    """Encrypt plaintext string, return base64-encoded ciphertext."""
    if not plaintext:
        return ""
    return _get_cipher().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt base64-encoded ciphertext back to plaintext."""
    if not ciphertext:
        return ""
    try:
        return _get_cipher().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        logger.error("Decryption failed: invalid token (wrong key?)")
        raise ValueError("Decryption failed")


def mask_api_key(api_key: str) -> str:
    """Mask API key for display: '****...xxxx' (last 4 chars visible)."""
    if not api_key or len(api_key) <= 4:
        return "****"
    return f"****...{api_key[-4:]}"
