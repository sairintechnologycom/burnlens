"""Phase 4: invitation tokens are stored as SHA-256 hashes.

Locks the invariant that the DB never sees the plaintext invitation token,
but accept-by-URL still works. Guards against a regression that would
re-store the plaintext column (or compare plaintext against plaintext).
"""
from __future__ import annotations

import hashlib
import os
import pathlib
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/burnlens_test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests-32ch")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault(
    "PII_MASTER_KEY",
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
)

_FAKE_ENV = pathlib.Path(__file__).parent / "_invitation_hashing_test.env"
if not _FAKE_ENV.exists():
    _FAKE_ENV.write_text("")
import pydantic_settings.sources as _ps_sources  # noqa: E402
_ps_sources.dotenv_values = lambda *a, **k: {}


WS_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_ID = "11111111-1111-1111-1111-111111111111"


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def test_team_api_insert_hashes_the_token():
    """Regression guard: /team/invite must INSERT token_hash, not token."""
    from burnlens_cloud.team_api import _hash_invitation_token

    sample = "deadbeefcafebabe0123456789abcdef"
    assert _hash_invitation_token(sample) == _sha256_hex(sample)
    assert _hash_invitation_token(sample) != sample  # not a no-op


@pytest.mark.asyncio
async def test_accept_invitation_looks_up_by_hash_not_plaintext():
    """Lookup SQL must target `token_hash`, and must be fed the hash of the
    URL-supplied token — not the plaintext."""
    captured_sql = []
    captured_args = []

    async def fake_execute_query(sql, *args):
        captured_sql.append(sql)
        captured_args.append(args)
        # First call: invitation lookup → return nothing so handler 404s.
        return []

    from burnlens_cloud.auth import accept_invitation

    plaintext = "abc123def456abc123def456abc123de"
    with patch("burnlens_cloud.auth.execute_query", side_effect=fake_execute_query):
        with pytest.raises(Exception):
            # HTTPException(404) expected since we return no row.
            await accept_invitation(plaintext, redirect_to=None, request=None)

    # The first query must reference `token_hash`, not `token`.
    assert len(captured_sql) >= 1
    assert "token_hash" in captured_sql[0]
    assert "WHERE token =" not in captured_sql[0]

    # And the query arg must be the sha256 of the URL token, not the plaintext.
    assert captured_args[0][0] == _sha256_hex(plaintext)
    assert captured_args[0][0] != plaintext


@pytest.mark.asyncio
async def test_accept_invitation_matches_hash_roundtrip():
    """End-to-end: simulate a stored hashed invitation and confirm a plaintext
    token from the URL resolves to it."""
    import datetime as _dt

    plaintext = "feedfacefeedfacefeedfacefeedface"
    stored_hash = _sha256_hex(plaintext)

    async def fake_execute_query(sql, *args):
        if "token_hash" in sql:
            assert args[0] == stored_hash
            return [{
                "id": "11111111-2222-3333-4444-555555555555",
                "workspace_id": WS_ID,
                "email": "invitee@example.com",
                "role": "viewer",
                "expires_at": _dt.datetime.utcnow() + _dt.timedelta(hours=1),
                "accepted_at": None,
            }]
        return []

    async def fake_execute_insert(sql, *args):
        return None

    from burnlens_cloud.auth import accept_invitation

    with patch("burnlens_cloud.auth.execute_query", side_effect=fake_execute_query), \
         patch("burnlens_cloud.auth.execute_insert", side_effect=fake_execute_insert):
        # No Authorization header → handler should redirect to signup/?invite=...
        class _Req:
            headers = {}
        resp = await accept_invitation(plaintext, redirect_to=None, request=_Req())

    # RedirectResponse to signup with the plaintext token in query string.
    assert hasattr(resp, "status_code")
    assert resp.status_code in (302, 303)
    location = resp.headers["location"]
    assert f"invite={plaintext}" in location
