"""Startup coverage for the optional ClickHouse analytics plane."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from burnlens_cloud.config import settings
from burnlens_cloud.main import lifespan


@pytest.mark.asyncio
async def test_lifespan_skips_clickhouse_when_streaming_is_disabled(monkeypatch):
    monkeypatch.setattr(settings, "streaming_enabled", False)
    monkeypatch.setattr(settings, "scheduler_enabled", False)

    with (
        patch("burnlens_cloud.main.init_db", new_callable=AsyncMock),
        patch("burnlens_cloud.main.close_db", new_callable=AsyncMock),
        patch("burnlens_cloud.main.init_clickhouse", new_callable=AsyncMock) as init_clickhouse,
        patch("burnlens_cloud.main.close_clickhouse", new_callable=AsyncMock) as close_clickhouse,
        patch("burnlens_cloud.main.close_streaming_producer", new_callable=AsyncMock) as close_streaming,
        patch("burnlens_cloud.main.drain_pending_email_tasks", new_callable=AsyncMock),
    ):
        async with lifespan(MagicMock()):
            pass

    init_clickhouse.assert_not_awaited()
    close_clickhouse.assert_not_awaited()
    close_streaming.assert_not_awaited()


@pytest.mark.asyncio
async def test_lifespan_initializes_clickhouse_when_streaming_is_enabled(monkeypatch):
    monkeypatch.setattr(settings, "streaming_enabled", True)
    monkeypatch.setattr(settings, "scheduler_enabled", False)

    with (
        patch("burnlens_cloud.main.init_db", new_callable=AsyncMock),
        patch("burnlens_cloud.main.close_db", new_callable=AsyncMock),
        patch("burnlens_cloud.main.init_clickhouse", new_callable=AsyncMock) as init_clickhouse,
        patch("burnlens_cloud.main.close_clickhouse", new_callable=AsyncMock) as close_clickhouse,
        patch("burnlens_cloud.main.close_streaming_producer", new_callable=AsyncMock) as close_streaming,
        patch("burnlens_cloud.main.drain_pending_email_tasks", new_callable=AsyncMock),
    ):
        async with lifespan(MagicMock()):
            pass

    init_clickhouse.assert_awaited_once()
    close_clickhouse.assert_awaited_once()
    close_streaming.assert_awaited_once()
