"""Shared test fixtures for burnlens-cloud."""
from __future__ import annotations

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
