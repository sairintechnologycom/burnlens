"""Shared pytest fixtures for BurnLens tests."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from burnlens.config import BurnLensConfig
from burnlens.storage.database import init_db


@pytest.fixture
def tmp_db(tmp_path: Path) -> str:
    """Return a path to a fresh temporary SQLite database."""
    return str(tmp_path / "test.db")


@pytest_asyncio.fixture
async def initialized_db(tmp_db: str) -> str:
    """Initialize a fresh database and return its path."""
    await init_db(tmp_db)
    return tmp_db


@pytest.fixture
def default_config(tmp_db: str) -> BurnLensConfig:
    """Return a BurnLensConfig wired to a temp DB."""
    cfg = BurnLensConfig()
    cfg.db_path = tmp_db
    return cfg
