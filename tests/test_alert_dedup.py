"""Tests for DB-backed alert deduplication.

Verifies that fired_alerts persistence survives process restarts,
respects dedup windows, and fails open when the DB is unavailable.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
import aiosqlite

from burnlens.storage.database import (
    init_db,
    mark_alert_fired,
    purge_old_fired_alerts,
    was_alert_fired,
)
from burnlens.config import BurnLensConfig


@pytest_asyncio.fixture
async def db_path():
    """Create a temporary SQLite database with all tables initialised."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test_burnlens.db")
        await init_db(path)
        yield path


# ---- Query helper tests ----


@pytest.mark.asyncio
async def test_alert_not_fired_on_first_call(db_path: str) -> None:
    """mark_alert_fired → was_alert_fired should return True within window."""
    assert not await was_alert_fired(db_path, "shadow:asset_42", "shadow_detected", within_hours=24)

    await mark_alert_fired(db_path, "shadow:asset_42", "shadow_detected")

    assert await was_alert_fired(db_path, "shadow:asset_42", "shadow_detected", within_hours=24)


@pytest.mark.asyncio
async def test_alert_not_refired_within_window(db_path: str) -> None:
    """Fire alert, immediately check → should be suppressed."""
    await mark_alert_fired(db_path, "shadow:asset_7", "shadow_detected")

    # Immediately after firing, it should be suppressed
    assert await was_alert_fired(db_path, "shadow:asset_7", "shadow_detected", within_hours=24)


@pytest.mark.asyncio
async def test_alert_refires_after_window_expires(db_path: str) -> None:
    """Fire alert with fired_at set to 25h ago → was_alert_fired should return False."""
    # Insert a record and then manually backdate it
    await mark_alert_fired(db_path, "shadow:asset_99", "shadow_detected")

    # Backdate fired_at to 25 hours ago
    old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE fired_alerts SET fired_at = ? WHERE alert_key = ? AND alert_type = ?",
            (old_time, "shadow:asset_99", "shadow_detected"),
        )
        await db.commit()

    # Should no longer be considered fired (24h window expired)
    assert not await was_alert_fired(db_path, "shadow:asset_99", "shadow_detected", within_hours=24)


@pytest.mark.asyncio
async def test_dedup_survives_restart(db_path: str) -> None:
    """Write to DB, create new DiscoveryAlertEngine instance, check → still suppressed.

    This is the key regression test for the original bug where in-memory
    sets were lost on process restart.
    """
    await mark_alert_fired(db_path, "shadow:asset_42", "shadow_detected")

    # Simulate process restart: create a brand new engine instance
    config = BurnLensConfig(db_path=db_path)

    with patch("burnlens.alerts.email.EmailSender"):
        from burnlens.alerts.discovery import DiscoveryAlertEngine

        engine = DiscoveryAlertEngine(config, db_path)

    # The new engine should still see the fired alert via DB
    assert await was_alert_fired(engine.db_path, "shadow:asset_42", "shadow_detected", within_hours=24)


@pytest.mark.asyncio
async def test_db_failure_allows_alert_to_fire(db_path: str) -> None:
    """Mock aiosqlite to raise an exception → alert should still fire (fail-open)."""
    # was_alert_fired should return False (fail-open) when DB raises
    with patch("burnlens.storage.database.aiosqlite") as mock_aiosqlite:
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("DB disk error"))
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_aiosqlite.connect.return_value = mock_ctx

        with pytest.raises(Exception, match="DB disk error"):
            await was_alert_fired(db_path, "shadow:asset_1", "shadow_detected")

    # The DiscoveryAlertEngine wraps was_alert_fired in try/except,
    # so a DB failure lets the alert fire. Verify the engine behaviour:
    config = BurnLensConfig(db_path=db_path)

    with patch("burnlens.alerts.email.EmailSender"):
        from burnlens.alerts.discovery import DiscoveryAlertEngine

        engine = DiscoveryAlertEngine(config, db_path)

    # Mock the dedup check to raise, mock dispatch to track calls
    with (
        patch("burnlens.alerts.discovery.was_alert_fired", side_effect=Exception("DB error")),
        patch("burnlens.alerts.discovery.get_new_shadow_events_since") as mock_events,
        patch("burnlens.alerts.discovery.get_asset_by_id") as mock_get_asset,
        patch.object(engine, "_dispatch_discovery_alert", new_callable=AsyncMock) as mock_dispatch,
        patch("burnlens.alerts.discovery.mark_alert_fired", side_effect=Exception("DB error")),
    ):
        from burnlens.storage.models import AiAsset, DiscoveryEvent

        mock_event = DiscoveryEvent(
            event_type="new_asset_detected",
            asset_id=1,
            id=100,
        )
        mock_events.return_value = [mock_event]

        mock_asset = AiAsset(
            provider="openai",
            model_name="gpt-4o",
            endpoint_url="https://api.openai.com/v1",
            id=1,
        )
        mock_get_asset.return_value = mock_asset

        count = await engine.check_shadow_alerts()

        # Alert should fire despite DB errors (fail-open)
        assert count == 1
        mock_dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_purge_removes_old_records(db_path: str) -> None:
    """Insert records with fired_at 31 days ago → purge → records gone."""
    await mark_alert_fired(db_path, "shadow:asset_old", "shadow_detected")
    await mark_alert_fired(db_path, "spike:asset_old", "spend_spike")
    await mark_alert_fired(db_path, "shadow:asset_recent", "shadow_detected")

    # Backdate two records to 31 days ago
    old_time = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE fired_alerts SET fired_at = ? WHERE alert_key IN (?, ?)",
            (old_time, "shadow:asset_old", "spike:asset_old"),
        )
        await db.commit()

    deleted = await purge_old_fired_alerts(db_path, older_than_days=30)

    assert deleted == 2

    # Old records should be gone
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM fired_alerts")
        row = await cursor.fetchone()
        assert row[0] == 1  # only the recent one remains


# ---- Dedup window tests ----


@pytest.mark.asyncio
async def test_spend_spike_6h_window(db_path: str) -> None:
    """Spend spike alerts use a 6-hour dedup window."""
    await mark_alert_fired(db_path, "spike:asset_7", "spend_spike")

    # Within 6h window → suppressed
    assert await was_alert_fired(db_path, "spike:asset_7", "spend_spike", within_hours=6)

    # Backdate to 7h ago → should re-fire
    old_time = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE fired_alerts SET fired_at = ? WHERE alert_key = ?",
            (old_time, "spike:asset_7"),
        )
        await db.commit()

    assert not await was_alert_fired(db_path, "spike:asset_7", "spend_spike", within_hours=6)


@pytest.mark.asyncio
async def test_new_provider_72h_window(db_path: str) -> None:
    """New provider alerts use a 72-hour dedup window."""
    await mark_alert_fired(db_path, "provider:asset_3", "new_provider")

    # Within 72h window → suppressed
    assert await was_alert_fired(db_path, "provider:asset_3", "new_provider", within_hours=72)

    # Backdate to 73h ago → should re-fire
    old_time = (datetime.now(timezone.utc) - timedelta(hours=73)).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE fired_alerts SET fired_at = ? WHERE alert_key = ?",
            (old_time, "provider:asset_3"),
        )
        await db.commit()

    assert not await was_alert_fired(db_path, "provider:asset_3", "new_provider", within_hours=72)
