"""Unit tests for burnlens_cloud.pii_crypto (Phase 0 of PII encryption plan)."""
from __future__ import annotations

import base64
import os

import pytest

from burnlens_cloud import pii_crypto


@pytest.fixture(autouse=True)
def _fresh_master_key(monkeypatch):
    """Provide a deterministic master key and reset memoised singletons.

    Each test gets the same 32-byte key so ciphertexts are reproducible across
    tests, but we reset the in-module cache so any env monkeypatching lands.
    """
    key = base64.b64encode(b"\x01" * 32).decode()
    monkeypatch.setenv("PII_MASTER_KEY", key)
    pii_crypto.reset_for_testing()
    yield
    pii_crypto.reset_for_testing()


# --- encrypt_pii / decrypt_pii roundtrip ------------------------------------

def test_encrypt_decrypt_roundtrip():
    plaintext = "alice@example.com"
    ct = pii_crypto.encrypt_pii(plaintext)
    assert ct.startswith("v1:")
    assert ct != plaintext
    assert pii_crypto.decrypt_pii(ct) == plaintext


def test_encrypt_is_probabilistic():
    """Two encryptions of the same input should differ (Fernet uses random IVs)."""
    a = pii_crypto.encrypt_pii("same")
    b = pii_crypto.encrypt_pii("same")
    assert a != b
    assert pii_crypto.decrypt_pii(a) == "same"
    assert pii_crypto.decrypt_pii(b) == "same"


def test_encrypt_passthrough_for_empty():
    assert pii_crypto.encrypt_pii("") == ""
    assert pii_crypto.encrypt_pii(None) is None  # type: ignore[arg-type]
    assert pii_crypto.decrypt_pii("") == ""
    assert pii_crypto.decrypt_pii(None) is None  # type: ignore[arg-type]


def test_decrypt_rejects_unknown_version():
    with pytest.raises(pii_crypto.PIICryptoError, match="Unknown PII ciphertext version"):
        pii_crypto.decrypt_pii("v99:garbage")


def test_decrypt_rejects_tampered_ciphertext():
    ct = pii_crypto.encrypt_pii("important")
    tampered = ct[:-4] + "AAAA"
    with pytest.raises(pii_crypto.PIICryptoError, match="invalid token"):
        pii_crypto.decrypt_pii(tampered)


# --- lookup_hash ------------------------------------------------------------

def test_lookup_hash_is_deterministic():
    h1 = pii_crypto.lookup_hash("alice@example.com")
    h2 = pii_crypto.lookup_hash("alice@example.com")
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_lookup_hash_normalises_case_and_whitespace():
    assert pii_crypto.lookup_hash("Alice@Example.com") == pii_crypto.lookup_hash(
        "  alice@example.com  "
    )


def test_lookup_hash_differs_across_inputs():
    assert pii_crypto.lookup_hash("a@b.com") != pii_crypto.lookup_hash("c@d.com")


def test_lookup_hash_differs_across_keys(monkeypatch):
    """Changing the master key must yield different HMAC outputs."""
    h_key_a = pii_crypto.lookup_hash("same@x.com")

    monkeypatch.setenv("PII_MASTER_KEY", base64.b64encode(b"\x02" * 32).decode())
    pii_crypto.reset_for_testing()
    h_key_b = pii_crypto.lookup_hash("same@x.com")

    assert h_key_a != h_key_b


# --- key loading errors -----------------------------------------------------

def test_missing_master_key_raises(monkeypatch):
    monkeypatch.delenv("PII_MASTER_KEY", raising=False)
    pii_crypto.reset_for_testing()
    with pytest.raises(pii_crypto.PIICryptoError, match="not set"):
        pii_crypto.encrypt_pii("x")


def test_short_master_key_raises(monkeypatch):
    monkeypatch.setenv("PII_MASTER_KEY", base64.b64encode(b"short").decode())
    pii_crypto.reset_for_testing()
    with pytest.raises(pii_crypto.PIICryptoError, match="32 bytes"):
        pii_crypto.encrypt_pii("x")


def test_urlsafe_base64_key_accepted(monkeypatch):
    """Operators may generate the key via urlsafe base64; accept both forms."""
    raw_key = b"\x03" * 32
    monkeypatch.setenv("PII_MASTER_KEY", base64.urlsafe_b64encode(raw_key).decode())
    pii_crypto.reset_for_testing()
    ct = pii_crypto.encrypt_pii("ok")
    assert pii_crypto.decrypt_pii(ct) == "ok"
