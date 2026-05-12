"""Phase 16 API Keys backend tests.

Covers APIKEY-01 (last_used_at surface), APIKEY-03 (revoke + indistinguishability),
APIKEY-04 (PATCH rename), APIKEY-05 (viewer-role scoping).

Decision refs: D-01, D-03, D-04, D-05, D-06, D-07, D-09, D-10, D-11.

PATTERNS.md crit: tests/test_keys.py is the LOCAL-PROXY SQLite key store test
(burnlens.keys, sqlite, CLI). Cloud-side last_used_at + viewer-filter
assertions belong here, NOT in test_keys.py.
"""

from __future__ import annotations

import datetime as _dt
import time
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from burnlens_cloud.auth import verify_token as _verify_token
from burnlens_cloud.models import TokenPayload


def _auth(app, token):
    app.dependency_overrides[_verify_token] = lambda: token


def _make_keys_app():
    from fastapi import FastAPI

    from burnlens_cloud.api_keys_api import router

    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def owner_token():
    return TokenPayload(
        workspace_id=uuid4(),
        user_id=uuid4(),
        role="owner",
        plan="cloud",
        iat=int(time.time()),
        exp=int(time.time()) + 86400,
    )


@pytest.fixture
def viewer_token():
    return TokenPayload(
        workspace_id=uuid4(),
        user_id=uuid4(),
        role="viewer",
        plan="cloud",
        iat=int(time.time()),
        exp=int(time.time()) + 86400,
    )


# ---------------------------------------------------------------------------
# Task 1 — viewer-role scoping on GET + PATCH validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_keys_owner_returns_all(owner_token):
    from httpx import ASGITransport, AsyncClient

    app = _make_keys_app()
    _auth(app, owner_token)
    mock_rows = [
        {
            "id": uuid4(),
            "name": "Primary",
            "last4": "abcd",
            "created_at": _dt.datetime.utcnow(),
            "revoked_at": None,
            "last_used_at": None,
        }
    ]
    with patch(
        "burnlens_cloud.api_keys_api.execute_query", AsyncMock(return_value=mock_rows)
    ) as mock_exec:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.get("/api-keys")
    assert r.status_code == 200
    # Owner: creator_filter is None — third positional arg (sql, workspace_id, creator_filter)
    assert mock_exec.call_args.args[1] == str(owner_token.workspace_id)
    assert mock_exec.call_args.args[2] is None


@pytest.mark.asyncio
async def test_list_keys_viewer_returns_only_own(viewer_token):
    from httpx import ASGITransport, AsyncClient

    app = _make_keys_app()
    _auth(app, viewer_token)
    with patch(
        "burnlens_cloud.api_keys_api.execute_query", AsyncMock(return_value=[])
    ) as mock_exec:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.get("/api-keys")
    assert r.status_code == 200
    # Viewer: creator_filter must be str(viewer.user_id)
    assert mock_exec.call_args.args[1] == str(viewer_token.workspace_id)
    assert mock_exec.call_args.args[2] == str(viewer_token.user_id)
    sql = mock_exec.call_args.args[0]
    assert "created_by_user_id = $2" in sql
    assert "last_used_at" in sql  # must be in SELECT


@pytest.mark.asyncio
async def test_list_keys_response_includes_last_used_at(owner_token):
    from httpx import ASGITransport, AsyncClient

    app = _make_keys_app()
    _auth(app, owner_token)
    mock_rows = [
        {
            "id": uuid4(),
            "name": "Primary",
            "last4": "abcd",
            "created_at": _dt.datetime(2026, 1, 1),
            "revoked_at": None,
            "last_used_at": _dt.datetime(2026, 5, 10, 12, 0, 0),
        }
    ]
    with patch(
        "burnlens_cloud.api_keys_api.execute_query", AsyncMock(return_value=mock_rows)
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.get("/api-keys")
    body = r.json()
    assert isinstance(body, list) and len(body) == 1
    assert body[0]["last_used_at"] is not None
    assert body[0]["last_used_at"].startswith("2026-05-10")


@pytest.mark.asyncio
async def test_patch_keys_name_max_length_128(owner_token):
    from httpx import ASGITransport, AsyncClient

    app = _make_keys_app()
    _auth(app, owner_token)
    key_id = uuid4()
    new_name = "x" * 128
    updated_row = [
        {
            "id": key_id,
            "name": new_name,
            "last4": "abcd",
            "created_at": _dt.datetime.utcnow(),
            "revoked_at": None,
            "last_used_at": None,
        }
    ]
    with patch(
        "burnlens_cloud.api_keys_api.execute_query", AsyncMock(return_value=updated_row)
    ) as mock_exec:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.patch(f"/api-keys/{key_id}", json={"name": new_name})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == new_name
    sql = mock_exec.call_args.args[0]
    assert "SET name = $1" in sql
    assert "RETURNING" in sql and "last_used_at" in sql
    # PATCH must NOT touch revoked_at — only the RETURNING tail references it
    assert "revoked_at" not in sql.split("RETURNING")[0]


@pytest.mark.asyncio
async def test_patch_keys_name_too_long_422(owner_token):
    from httpx import ASGITransport, AsyncClient

    app = _make_keys_app()
    _auth(app, owner_token)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        r = await ac.patch(f"/api-keys/{uuid4()}", json={"name": "x" * 129})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_keys_name_empty_422(owner_token):
    from httpx import ASGITransport, AsyncClient

    app = _make_keys_app()
    _auth(app, owner_token)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        r = await ac.patch(f"/api-keys/{uuid4()}", json={"name": ""})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_keys_missing_name_422(owner_token):
    from httpx import ASGITransport, AsyncClient

    app = _make_keys_app()
    _auth(app, owner_token)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        r = await ac.patch(f"/api-keys/{uuid4()}", json={})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Task 2 — indistinguishability 404 + throttled last_used_at writer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_keys_viewer_404_on_other_creator(viewer_token):
    """Per D-04: wrong-creator PATCH returns 404, not 403."""
    from httpx import ASGITransport, AsyncClient

    app = _make_keys_app()
    _auth(app, viewer_token)
    with patch(
        "burnlens_cloud.api_keys_api.execute_query", AsyncMock(return_value=[])
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.patch(f"/api-keys/{uuid4()}", json={"name": "renamed"})
    assert r.status_code == 404
    assert r.json() == {"detail": {"error": "api_key_not_found"}}


@pytest.mark.asyncio
async def test_delete_keys_viewer_404_on_other_creator(viewer_token):
    """Viewer DELETE on someone else's key — 404, not 403 (D-04)."""
    from httpx import ASGITransport, AsyncClient

    app = _make_keys_app()
    _auth(app, viewer_token)
    with patch(
        "burnlens_cloud.api_keys_api.execute_query", AsyncMock(return_value=[])
    ), patch("burnlens_cloud.api_keys_api.invalidate_api_key_cache") as mock_inv:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.delete(f"/api-keys/{uuid4()}")
    assert r.status_code == 404
    assert r.json() == {"detail": {"error": "api_key_not_found"}}
    # 404 path must NOT touch the cache
    mock_inv.assert_not_called()


@pytest.mark.asyncio
async def test_patch_keys_cross_tenant_404(owner_token):
    """Owner attempting to PATCH a key from a different workspace — 404."""
    from httpx import ASGITransport, AsyncClient

    app = _make_keys_app()
    _auth(app, owner_token)
    with patch(
        "burnlens_cloud.api_keys_api.execute_query", AsyncMock(return_value=[])
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.patch(f"/api-keys/{uuid4()}", json={"name": "renamed"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_keys_does_not_invalidate_cache(owner_token):
    """Per D-11: hash unchanged on rename → no cache invalidation."""
    from httpx import ASGITransport, AsyncClient

    app = _make_keys_app()
    _auth(app, owner_token)
    key_id = uuid4()
    updated_row = [
        {
            "id": key_id,
            "name": "renamed",
            "last4": "abcd",
            "created_at": _dt.datetime.utcnow(),
            "revoked_at": None,
            "last_used_at": None,
        }
    ]
    with patch(
        "burnlens_cloud.api_keys_api.execute_query", AsyncMock(return_value=updated_row)
    ), patch("burnlens_cloud.api_keys_api.invalidate_api_key_cache") as mock_inv:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.patch(f"/api-keys/{key_id}", json={"name": "renamed"})
    assert r.status_code == 200
    mock_inv.assert_not_called()


@pytest.mark.asyncio
async def test_last_used_at_throttled_sql_predicate():
    """Per D-06: SQL-side throttle of last_used_at writes."""
    import asyncio

    from burnlens_cloud.auth import _schedule_last_used_update

    with patch(
        "burnlens_cloud.auth.execute_query", AsyncMock(return_value=None)
    ) as mock_exec:
        _schedule_last_used_update("some-key-id")
        # Two trampoline ticks so the create_task'd coroutine actually invokes execute_query.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    assert mock_exec.call_count == 1
    sql = mock_exec.call_args.args[0]
    assert "last_used_at = now()" in sql
    assert "last_used_at < now() - interval '60 seconds'" in sql
    # Bound id is the second positional arg
    assert mock_exec.call_args.args[1] == "some-key-id"


@pytest.mark.asyncio
async def test_last_used_at_skips_when_api_key_id_none():
    """Legacy fallback rows have no api_keys.id — must not fire."""
    import asyncio

    from burnlens_cloud.auth import _schedule_last_used_update

    with patch(
        "burnlens_cloud.auth.execute_query", AsyncMock(return_value=None)
    ) as mock_exec:
        _schedule_last_used_update(None)
        await asyncio.sleep(0)
    assert mock_exec.call_count == 0


@pytest.mark.asyncio
async def test_last_used_at_swallows_exceptions(caplog):
    """Per D-07 + CLAUDE.md: a stuck UPDATE must NEVER break ingest."""
    import asyncio
    import logging

    from burnlens_cloud.auth import _schedule_last_used_update

    with patch(
        "burnlens_cloud.auth.execute_query",
        AsyncMock(side_effect=RuntimeError("DB connection lost")),
    ):
        with caplog.at_level(logging.WARNING, logger="burnlens_cloud.auth"):
            _schedule_last_used_update("key-id-x")
            await asyncio.sleep(0)
            await asyncio.sleep(0)
    # Helper must catch + log; no exception bubbles up to this test.
    assert any("last_used_at" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_owner_can_revoke_any_key(owner_token):
    """APIKEY-03: owner DELETE on a key in their workspace succeeds (200 + cache eviction)."""
    from httpx import ASGITransport, AsyncClient

    app = _make_keys_app()
    _auth(app, owner_token)
    key_id = uuid4()
    revoke_result = [{"id": key_id, "key_hash": "abc123"}]

    # execute_query is called twice: UPDATE api_keys + UPDATE workspaces (legacy clear).
    side_effects = [revoke_result, []]

    with patch(
        "burnlens_cloud.api_keys_api.execute_query",
        AsyncMock(side_effect=side_effects),
    ), patch("burnlens_cloud.api_keys_api.invalidate_api_key_cache") as mock_inv:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.delete(f"/api-keys/{key_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["id"] == str(key_id)
    mock_inv.assert_called_once_with("abc123")
