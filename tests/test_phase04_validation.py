"""Phase 4 Nyquist validation tests -- fills gaps in ALRT requirement coverage.

Gaps addressed:
  1. ALRT-02: new provider alert dispatches to BOTH Slack and email
  2. ALRT-05: spend spike alert dispatches to BOTH Slack and email
  3. ALRT-05: 200% threshold boundary -- ratio exactly 2.0 must NOT fire
  4. ALRT-01/05: _build_alert_email_html produces valid HTML for both alert types
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from burnlens.alerts.discovery import DiscoveryAlertEngine, _build_alert_email_html
from burnlens.alerts.types import DiscoveryAlert, SpendSpikeAlert
from burnlens.config import AlertsConfig, BurnLensConfig, EmailConfig
from burnlens.storage.models import AiAsset, DiscoveryEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(slack_webhook: str | None = "https://hooks.slack.com/test") -> BurnLensConfig:
    config = BurnLensConfig()
    config.alerts = AlertsConfig(
        slack_webhook=slack_webhook,
        alert_recipients=["ops@example.com"],
    )
    config.email = EmailConfig(smtp_host=None)
    return config


def _make_asset(
    id: int = 1,
    provider: str = "openai",
    model_name: str = "gpt-4o",
    status: str = "shadow",
    monthly_spend_usd: float = 50.0,
) -> AiAsset:
    now = datetime(2026, 4, 11, 0, 0, 0, tzinfo=timezone.utc)
    return AiAsset(
        id=id,
        provider=provider,
        model_name=model_name,
        endpoint_url=f"https://api.{provider}.com/v1/chat/completions",
        api_key_hash=None,
        owner_team=None,
        project=None,
        status=status,
        risk_tier="high",
        first_seen_at=now,
        last_active_at=now,
        monthly_spend_usd=monthly_spend_usd,
        monthly_requests=10,
        tags={},
        created_at=now,
        updated_at=now,
    )


def _make_event(
    id: int = 1,
    event_type: str = "new_asset_detected",
    asset_id: int = 1,
) -> DiscoveryEvent:
    return DiscoveryEvent(
        id=id,
        event_type=event_type,
        asset_id=asset_id,
        details={"source": "proxy_traffic"},
        detected_at=datetime(2026, 4, 11, 0, 0, 0, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Gap 1: ALRT-02 -- new provider alert sends BOTH Slack and email
# ---------------------------------------------------------------------------


class TestNewProviderAlertDispatchesBothChannels:
    """ALRT-02 requires Slack AND email when a new provider is detected."""

    @pytest.mark.asyncio
    async def test_new_provider_alert_sends_email(self, tmp_path) -> None:
        """check_new_provider_alerts dispatches to email (not just Slack)."""
        db_path = str(tmp_path / "test.db")
        config = _make_config()
        engine = DiscoveryAlertEngine(config, db_path)

        asset = _make_asset(provider="anthropic", model_name="claude-3-opus")
        event = _make_event(id=20, event_type="provider_changed")

        with (
            patch(
                "burnlens.alerts.discovery.get_new_provider_events_since",
                new_callable=AsyncMock,
            ) as mock_provider,
            patch(
                "burnlens.alerts.discovery.get_asset_by_id",
                new_callable=AsyncMock,
            ) as mock_asset,
        ):
            mock_provider.return_value = [event]
            mock_asset.return_value = asset
            engine._slack = MagicMock()
            engine._slack.send_discovery = AsyncMock()
            engine._email = MagicMock()
            engine._email.send = AsyncMock()

            count = await engine.check_new_provider_alerts()

        assert count == 1
        engine._slack.send_discovery.assert_called_once()
        engine._email.send.assert_called_once()


# ---------------------------------------------------------------------------
# Gap 2: ALRT-05 -- spend spike alert sends BOTH Slack and email
# ---------------------------------------------------------------------------


class TestSpendSpikeAlertDispatchesBothChannels:
    """ALRT-05 requires Slack AND email when spend spike is detected."""

    @pytest.mark.asyncio
    async def test_spend_spike_alert_sends_email(self, tmp_path) -> None:
        """check_spend_spikes dispatches to email (not just Slack)."""
        db_path = str(tmp_path / "test.db")
        config = _make_config()
        engine = DiscoveryAlertEngine(config, db_path)

        asset = _make_asset(id=7, monthly_spend_usd=300.0)

        with (
            patch(
                "burnlens.alerts.discovery.get_assets",
                new_callable=AsyncMock,
            ) as mock_assets,
            patch(
                "burnlens.alerts.discovery.get_asset_spend_history",
                new_callable=AsyncMock,
            ) as mock_history,
        ):
            mock_assets.return_value = [asset]
            mock_history.return_value = 100.0  # ratio = 3.0

            engine._slack = MagicMock()
            engine._slack.send_spend_spike = AsyncMock()
            engine._email = MagicMock()
            engine._email.send = AsyncMock()

            count = await engine.check_spend_spikes()

        assert count == 1
        engine._slack.send_spend_spike.assert_called_once()
        engine._email.send.assert_called_once()


# ---------------------------------------------------------------------------
# Gap 3: ALRT-05 -- 200% threshold boundary test
# ---------------------------------------------------------------------------


class TestSpendSpikeThresholdBoundary:
    """ALRT-05 threshold is >200% (ratio > 2.0). Exactly 2.0 must NOT fire."""

    @pytest.mark.asyncio
    async def test_exactly_200_percent_does_not_fire(self, tmp_path) -> None:
        """Spend spike at exactly 2.0 ratio (200%) does NOT trigger alert."""
        db_path = str(tmp_path / "test.db")
        config = _make_config()
        engine = DiscoveryAlertEngine(config, db_path)

        # monthly_spend_usd = 200.0, avg = 100.0 -> ratio = 2.0 exactly
        asset = _make_asset(id=15, monthly_spend_usd=200.0)

        with (
            patch(
                "burnlens.alerts.discovery.get_assets",
                new_callable=AsyncMock,
            ) as mock_assets,
            patch(
                "burnlens.alerts.discovery.get_asset_spend_history",
                new_callable=AsyncMock,
            ) as mock_history,
        ):
            mock_assets.return_value = [asset]
            mock_history.return_value = 100.0  # ratio = 200.0 / 100.0 = 2.0

            engine._slack = MagicMock()
            engine._slack.send_spend_spike = AsyncMock()

            count = await engine.check_spend_spikes()

        assert count == 0
        engine._slack.send_spend_spike.assert_not_called()

    @pytest.mark.asyncio
    async def test_just_above_200_percent_fires(self, tmp_path) -> None:
        """Spend spike at 2.01 ratio (201%) DOES trigger alert."""
        db_path = str(tmp_path / "test.db")
        config = _make_config()
        engine = DiscoveryAlertEngine(config, db_path)

        # monthly_spend_usd = 201.0, avg = 100.0 -> ratio = 2.01
        asset = _make_asset(id=16, monthly_spend_usd=201.0)

        with (
            patch(
                "burnlens.alerts.discovery.get_assets",
                new_callable=AsyncMock,
            ) as mock_assets,
            patch(
                "burnlens.alerts.discovery.get_asset_spend_history",
                new_callable=AsyncMock,
            ) as mock_history,
        ):
            mock_assets.return_value = [asset]
            mock_history.return_value = 100.0  # ratio = 201.0 / 100.0 = 2.01

            engine._slack = MagicMock()
            engine._slack.send_spend_spike = AsyncMock()
            engine._email = MagicMock()
            engine._email.send = AsyncMock()

            count = await engine.check_spend_spikes()

        assert count == 1
        engine._slack.send_spend_spike.assert_called_once()


# ---------------------------------------------------------------------------
# Gap 4: _build_alert_email_html produces valid HTML for both alert types
# ---------------------------------------------------------------------------


class TestBuildAlertEmailHtml:
    """Verify email HTML builder produces correct output for ALRT-01 and ALRT-05."""

    def test_shadow_detected_email_contains_model_and_provider(self) -> None:
        """Email HTML for shadow_detected includes model name and provider."""
        asset = _make_asset(model_name="gpt-4o", provider="openai")
        event = _make_event()
        alert = DiscoveryAlert(
            alert_type="shadow_detected",
            asset=asset,
            event=event,
            message="Shadow AI detected: gpt-4o on openai",
        )
        subject, html = _build_alert_email_html(alert)
        assert "Shadow AI Detected" in subject
        assert "gpt-4o" in subject
        assert "openai" in subject
        assert "gpt-4o" in html
        assert "openai" in html
        assert "<table" in html.lower()

    def test_new_provider_email_contains_provider(self) -> None:
        """Email HTML for new_provider includes provider name."""
        asset = _make_asset(provider="anthropic", model_name="claude-3-opus")
        event = _make_event(event_type="provider_changed")
        alert = DiscoveryAlert(
            alert_type="new_provider",
            asset=asset,
            event=event,
            message="New AI provider detected: anthropic",
        )
        subject, html = _build_alert_email_html(alert)
        assert "New AI Provider Detected" in subject
        assert "anthropic" in subject
        assert "anthropic" in html
        assert "<table" in html.lower()

    def test_spend_spike_email_contains_spend_details(self) -> None:
        """Email HTML for spend spike includes current spend, avg, and ratio."""
        asset = _make_asset(monthly_spend_usd=150.0)
        alert = SpendSpikeAlert(
            asset=asset,
            current_spend=150.0,
            avg_spend=50.0,
            spike_ratio=3.0,
            period_days=30,
        )
        subject, html = _build_alert_email_html(alert)
        assert "Spend Spike" in subject
        assert "300%" in subject  # spike_ratio * 100
        assert "150" in html
        assert "50" in html
        assert "<table" in html.lower()
