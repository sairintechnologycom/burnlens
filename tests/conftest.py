"""Shared test fixtures for burnlens-cloud."""
from __future__ import annotations

import asyncio
import os
import sys

# Ensure api/ package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["DATABASE_URL"] = "postgresql://localhost:5432/burnlens_test"
os.environ["JWT_SECRET"] = "test-secret-key-for-unit-tests"
os.environ["ENVIRONMENT"] = "test"
# Phase 2c: PII encryption is mandatory once plaintext PII columns are
# dropped. A deterministic test key lets unit tests encrypt / hash / decrypt
# without any external setup. 32 bytes base64-encoded.
os.environ.setdefault(
    "PII_MASTER_KEY",
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
)

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport


async def settle_background_tasks(ceiling: float = 5.0) -> None:
    """Deterministically await the fire-and-forget tasks the interceptor spawns
    via create_task() (background logging, WAL flush, anomaly checks) so their DB
    writes land before the caller asserts. Replaces fixed `asyncio.sleep()` waits
    that raced under CI load and flaked (short row counts, rows[0] IndexError,
    "Event loop is closed").

    Waits round-by-round until no pending task *completes* within a short window
    — i.e. the loggers have drained and only idle/long-lived tasks (e.g. a live
    test server sharing the loop) remain. `ceiling` is a safety-net upper bound.
    """
    me = asyncio.current_task()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + ceiling
    while loop.time() < deadline:
        pending = [t for t in asyncio.all_tasks() if t is not me and not t.done()]
        if not pending:
            break
        done, _ = await asyncio.wait(
            pending, timeout=0.1, return_when=asyncio.FIRST_COMPLETED
        )
        if not done:  # nothing completed → remaining tasks are idle; loggers flushed
            break


@pytest_asyncio.fixture
async def client():
    """Test client with mocked DB pool."""
    # Create a mock pool that acts as an async context manager
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("api.database.init_db", new_callable=AsyncMock):
        with patch("api.database.close_db", new_callable=AsyncMock):
            from api.main import app
            import api.database as db_mod
            db_mod.pool = mock_pool

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac, mock_conn


@pytest_asyncio.fixture
async def authed_client(client):
    """Client tuple + a valid JWT token."""
    from api.auth import _encode_jwt
    ac, mock_conn = client
    ws_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    token = _encode_jwt(ws_id, "cloud")

    # Mock the workspace lookup used by get_current_workspace
    mock_conn.fetchrow.return_value = {
        "id": ws_id,
        "name": "Test WS",
        "plan": "cloud",
        "active": True,
    }

    return ac, mock_conn, token, ws_id


# ---------------------------------------------------------------------------
# Cloud backend fixture (used by test_settings_api.py, test_custom_pricing.py, etc.)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def cloud_client():
    """(AsyncClient, FastAPI app) for cloud settings tests.

    Tests unpack as `ac, app = cloud_client` then set
    `app.dependency_overrides[verify_token] = lambda: token` to inject auth.
    """
    from fastapi import FastAPI
    from burnlens_cloud.settings_api import router as settings_router

    app = FastAPI()
    app.include_router(settings_router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac, app


# ---------------------------------------------------------------------------
# OSS proxy fixtures (used by tests/test_export.py, tests/test_storage.py, etc.)
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path):
    """Return a path to a fresh temporary SQLite database."""
    return str(tmp_path / "test.db")


@pytest_asyncio.fixture
async def initialized_db(tmp_db: str) -> str:
    """Initialize a fresh OSS SQLite database and return its path."""
    from burnlens.storage.database import init_db
    await init_db(tmp_db)
    return tmp_db
