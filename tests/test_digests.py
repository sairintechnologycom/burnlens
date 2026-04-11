"""Tests for burnlens.alerts.digests — daily and weekly digest emails."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from burnlens.alerts.digests import send_daily_digest, send_weekly_digest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_email_sender(send_mock: AsyncMock | None = None) -> MagicMock:
    """Return a mock EmailSender with an async send() method."""
    sender = MagicMock()
    sender.send = send_mock or AsyncMock()
    return sender


# ---------------------------------------------------------------------------
# send_daily_digest tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_digest_returns_zero_no_recipients(tmp_path):
    """send_daily_digest returns 0 immediately when recipients list is empty."""
    db_path = str(tmp_path / "test.db")
    sender = _make_email_sender()

    result = await send_daily_digest(db_path, sender, [])

    assert result == 0
    sender.send.assert_not_called()


@pytest.mark.asyncio
async def test_daily_digest_returns_zero_no_events(tmp_path):
    """send_daily_digest returns 0 and sends no email when there are no model_changed events."""
    db_path = str(tmp_path / "test.db")
    sender = _make_email_sender()

    with patch(
        "burnlens.alerts.digests.get_model_change_events_since",
        new=AsyncMock(return_value=[]),
    ):
        result = await send_daily_digest(db_path, sender, ["ops@example.com"])

    assert result == 0
    sender.send.assert_not_called()


@pytest.mark.asyncio
async def test_daily_digest_sends_email_with_events(tmp_path):
    """send_daily_digest sends one email with the correct subject and HTML table when events exist."""
    from burnlens.storage.models import AiAsset, DiscoveryEvent

    db_path = str(tmp_path / "test.db")
    send_mock = AsyncMock()
    sender = _make_email_sender(send_mock)

    now = datetime.now(timezone.utc)
    asset = AiAsset(
        id=1,
        provider="openai",
        model_name="gpt-4",
        endpoint_url="https://api.openai.com/v1/chat/completions",
        api_key_hash="abc",
        owner_team="engineering",
        project="chatbot",
        status="active",
        risk_tier="low",
        first_seen_at=now - timedelta(days=10),
        last_active_at=now,
        monthly_spend_usd=12.5,
        monthly_requests=100,
        tags={},
        created_at=now,
        updated_at=now,
    )
    event = DiscoveryEvent(
        id=1,
        event_type="model_changed",
        asset_id=1,
        details={"old_model": "gpt-3.5-turbo", "new_model": "gpt-4"},
        detected_at=now,
    )

    with (
        patch(
            "burnlens.alerts.digests.get_model_change_events_since",
            new=AsyncMock(return_value=[event]),
        ),
        patch(
            "burnlens.alerts.digests.get_asset_by_id",
            new=AsyncMock(return_value=asset),
        ),
    ):
        result = await send_daily_digest(db_path, sender, ["ops@example.com"])

    assert result == 1
    send_mock.assert_awaited_once()
    call_kwargs = send_mock.call_args
    # subject contains "Daily Digest" and today's date
    subject = call_kwargs.kwargs.get("subject") or call_kwargs.args[1]
    assert "Daily Digest" in subject
    assert "Model Changes" in subject
    # HTML body contains table headers and model info
    html = call_kwargs.kwargs.get("body_html") or call_kwargs.args[2]
    assert "<table" in html.lower()
    assert "gpt-4" in html


@pytest.mark.asyncio
async def test_daily_digest_skips_events_with_missing_asset(tmp_path):
    """send_daily_digest skips events whose asset cannot be found."""
    from burnlens.storage.models import DiscoveryEvent

    db_path = str(tmp_path / "test.db")
    send_mock = AsyncMock()
    sender = _make_email_sender(send_mock)

    now = datetime.now(timezone.utc)
    event = DiscoveryEvent(
        id=1,
        event_type="model_changed",
        asset_id=99,
        details={},
        detected_at=now,
    )

    with (
        patch(
            "burnlens.alerts.digests.get_model_change_events_since",
            new=AsyncMock(return_value=[event]),
        ),
        patch(
            "burnlens.alerts.digests.get_asset_by_id",
            new=AsyncMock(return_value=None),
        ),
    ):
        result = await send_daily_digest(db_path, sender, ["ops@example.com"])

    # All events skipped — no rows in table → no email sent
    assert result == 0
    send_mock.assert_not_called()


# ---------------------------------------------------------------------------
# send_weekly_digest tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weekly_digest_returns_zero_no_recipients(tmp_path):
    """send_weekly_digest returns 0 immediately when recipients list is empty."""
    db_path = str(tmp_path / "test.db")
    sender = _make_email_sender()

    result = await send_weekly_digest(db_path, sender, [])

    assert result == 0
    sender.send.assert_not_called()


@pytest.mark.asyncio
async def test_weekly_digest_returns_zero_no_inactive_assets(tmp_path):
    """send_weekly_digest returns 0 and sends no email when no assets are inactive."""
    db_path = str(tmp_path / "test.db")
    sender = _make_email_sender()

    with patch(
        "burnlens.alerts.digests.get_inactive_assets",
        new=AsyncMock(return_value=[]),
    ):
        result = await send_weekly_digest(db_path, sender, ["ops@example.com"])

    assert result == 0
    sender.send.assert_not_called()


@pytest.mark.asyncio
async def test_weekly_digest_sends_email_with_inactive_assets(tmp_path):
    """send_weekly_digest sends one email with the correct subject and asset list."""
    from burnlens.storage.models import AiAsset

    db_path = str(tmp_path / "test.db")
    send_mock = AsyncMock()
    sender = _make_email_sender(send_mock)

    now = datetime.now(timezone.utc)
    asset = AiAsset(
        id=2,
        provider="anthropic",
        model_name="claude-3-sonnet",
        endpoint_url="https://api.anthropic.com/v1/messages",
        api_key_hash="def",
        owner_team="ml-team",
        project="summarizer",
        status="active",
        risk_tier="medium",
        first_seen_at=now - timedelta(days=90),
        last_active_at=now - timedelta(days=45),
        monthly_spend_usd=0.0,
        monthly_requests=0,
        tags={},
        created_at=now - timedelta(days=90),
        updated_at=now,
    )

    with patch(
        "burnlens.alerts.digests.get_inactive_assets",
        new=AsyncMock(return_value=[asset]),
    ):
        result = await send_weekly_digest(db_path, sender, ["ops@example.com"])

    assert result == 1
    send_mock.assert_awaited_once()
    call_kwargs = send_mock.call_args
    subject = call_kwargs.kwargs.get("subject") or call_kwargs.args[1]
    assert "Weekly Digest" in subject
    assert "Inactive Assets" in subject
    html = call_kwargs.kwargs.get("body_html") or call_kwargs.args[2]
    assert "<table" in html.lower()
    assert "claude-3-sonnet" in html
