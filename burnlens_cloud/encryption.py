"""Encryption utilities for sensitive data (API keys, etc.)."""

import base64
import logging
from cryptography.fernet import Fernet, InvalidToken

from .config import settings

logger = logging.getLogger(__name__)


class EncryptionManager:
    """Manages encryption/decryption of sensitive data using Fernet."""

    def __init__(self, encryption_key: str):
        """
        Initialize with encryption key.

        Args:
            encryption_key: Base64-encoded 32-byte key from environment.
                           Generate with: Fernet.generate_key().decode()
        """
        self.encryption_key = encryption_key

    def _get_cipher(self) -> Fernet:
        """Get Fernet cipher instance."""
        try:
            # Ensure key is properly encoded
            if isinstance(self.encryption_key, str):
                key_bytes = self.encryption_key.encode() if isinstance(
                    self.encryption_key, str
                ) else self.encryption_key
            else:
                key_bytes = self.encryption_key

            return Fernet(key_bytes)
        except Exception as e:
            logger.error(f"Failed to initialize Fernet cipher: {e}")
            raise ValueError("Invalid encryption key")

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext to ciphertext (base64-encoded)."""
        if not plaintext:
            return ""

        try:
            cipher = self._get_cipher()
            ciphertext = cipher.encrypt(plaintext.encode())
            return ciphertext.decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt ciphertext back to plaintext."""
        if not ciphertext:
            return ""

        try:
            cipher = self._get_cipher()
            plaintext = cipher.decrypt(ciphertext.encode())
            return plaintext.decode()
        except InvalidToken:
            logger.error("Failed to decrypt: Invalid token (wrong key?)")
            raise ValueError("Decryption failed: Invalid token")
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise

    @staticmethod
    def mask_api_key(api_key: str, visible_chars: int = 4) -> str:
        """
        Mask API key for display, showing only last N characters.

        Example: "Bearer sk-1234567890abcdefghijklmnopqrst" → "Bearer ****...rstu"
        """
        if not api_key or len(api_key) <= visible_chars:
            return "****"

        visible = api_key[-visible_chars:]
        prefix_len = min(8, len(api_key) // 2)
        prefix = api_key[:prefix_len]

        return f"{prefix}****...{visible}"


def get_encryption_manager() -> EncryptionManager:
    """Get encryption manager instance."""
    if not settings.otel_encryption_key:
        raise ValueError(
            "OTEL_ENCRYPTION_KEY environment variable not set. "
            "Generate with: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    return EncryptionManager(settings.otel_encryption_key)
