"""Tests for DiscoveryAlertEngine and Slack discovery alert payload builders."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from burnlens.alerts.slack import SlackWebhookAlert
from burnlens.alerts.types import DiscoveryAlert, SpendSpikeAlert
from burnlens.storage.models import AiAsset, DiscoveryEvent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_asset(
    id: int = 1,
    provider: str = "openai",
    model_name: str = "gpt-4o",
    endpoint_url: str = "https://api.openai.com/v1/chat/completions",
    status: str = "shadow",
    monthly_spend_usd: float = 50.0,
) -> AiAsset:
    now = datetime(2026, 4, 11, 0, 0, 0)
    return AiAsset(
        id=id,
        provider=provider,
        model_name=model_name,
        endpoint_url=endpoint_url,
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
    details: dict | None = None,
) -> DiscoveryEvent:
    return DiscoveryEvent(
        id=id,
        event_type=event_type,
        asset_id=asset_id,
        details=details or {"source": "proxy_traffic"},
        detected_at=datetime(2026, 4, 11, 0, 0, 0),
    )


def _make_shadow_alert() -> DiscoveryAlert:
    return DiscoveryAlert(
        alert_type="shadow_detected",
        asset=_make_asset(),
        event=_make_event(),
        message="Shadow AI detected: gpt-4o on openai",
    )


def _make_provider_alert() -> DiscoveryAlert:
    asset = _make_asset(provider="anthropic", model_name="claude-3-opus", endpoint_url="https://api.anthropic.com/v1/messages")
    event = _make_event(event_type="provider_changed", details={"provider": "anthropic"})
    return DiscoveryAlert(
        alert_type="new_provider",
        asset=asset,
        event=event,
        message="New AI provider detected: anthropic",
    )


def _make_spend_spike_alert() -> SpendSpikeAlert:
    return SpendSpikeAlert(
        asset=_make_asset(monthly_spend_usd=150.0),
        current_spend=150.0,
        avg_spend=50.0,
        spike_ratio=3.0,
        period_days=30,
    )


# ---------------------------------------------------------------------------
# Task 1: Slack payload builder tests
# ---------------------------------------------------------------------------


class TestBuildShadowPayload:
    """Tests for _build_shadow_payload."""

    def test_returns_dict_with_blocks(self) -> None:
        from burnlens.alerts.slack import _build_shadow_payload

        alert = _make_shadow_alert()
        payload = _build_shadow_payload(alert)

        assert isinstance(payload, dict)
        assert "blocks" in payload
        assert len(payload["blocks"]) > 0

    def test_contains_red_circle_emoji(self) -> None:
        from burnlens.alerts.slack import _build_shadow_payload

        alert = _make_shadow_alert()
        payload = _build_shadow_payload(alert)
        text = json.dumps(payload)
        assert ":red_circle:" in text

    def test_contains_asset_model(self) -> None:
        from burnlens.alerts.slack import _build_shadow_payload

        alert = _make_shadow_alert()
        payload = _build_shadow_payload(alert)
        text = json.dumps(payload)
        assert "gpt-4o" in text

    def test_contains_provider(self) -> None:
        from burnlens.alerts.slack import _build_shadow_payload

        alert = _make_shadow_alert()
        payload = _build_shadow_payload(alert)
        text = json.dumps(payload)
        assert "openai" in text

    def test_contains_endpoint_url(self) -> None:
        from burnlens.alerts.slack import _build_shadow_payload

        alert = _make_shadow_alert()
        payload = _build_shadow_payload(alert)
        text = json.dumps(payload)
        assert "api.openai.com" in text


class TestBuildNewProviderPayload:
    """Tests for _build_new_provider_payload."""

    def test_returns_dict_with_blocks(self) -> None:
        from burnlens.alerts.slack import _build_new_provider_payload

        alert = _make_provider_alert()
        payload = _build_new_provider_payload(alert)

        assert isinstance(payload, dict)
        assert "blocks" in payload

    def test_contains_warning_emoji(self) -> None:
        from burnlens.alerts.slack import _build_new_provider_payload

        alert = _make_provider_alert()
        payload = _build_new_provider_payload(alert)
        text = json.dumps(payload)
        assert ":warning:" in text

    def test_contains_provider_name(self) -> None:
        from burnlens.alerts.slack import _build_new_provider_payload

        alert = _make_provider_alert()
        payload = _build_new_provider_payload(alert)
        text = json.dumps(payload)
        assert "anthropic" in text

    def test_contains_endpoint_url(self) -> None:
        from burnlens.alerts.slack import _build_new_provider_payload

        alert = _make_provider_alert()
        payload = _build_new_provider_payload(alert)
        text = json.dumps(payload)
        assert "api.anthropic.com" in text


class TestBuildSpendSpikePayload:
    """Tests for _build_spend_spike_payload."""

    def test_returns_dict_with_blocks(self) -> None:
        from burnlens.alerts.slack import _build_spend_spike_payload

        alert = _make_spend_spike_alert()
        payload = _build_spend_spike_payload(alert)

        assert isinstance(payload, dict)
        assert "blocks" in payload

    def test_contains_chart_emoji(self) -> None:
        from burnlens.alerts.slack import _build_spend_spike_payload

        alert = _make_spend_spike_alert()
        payload = _build_spend_spike_payload(alert)
        text = json.dumps(payload)
        assert ":chart_with_upwards_trend:" in text

    def test_contains_model_name(self) -> None:
        from burnlens.alerts.slack import _build_spend_spike_payload

        alert = _make_spend_spike_alert()
        payload = _build_spend_spike_payload(alert)
        text = json.dumps(payload)
        assert "gpt-4o" in text

    def test_contains_current_and_avg_spend(self) -> None:
        from burnlens.alerts.slack import _build_spend_spike_payload

        alert = _make_spend_spike_alert()
        payload = _build_spend_spike_payload(alert)
        text = json.dumps(payload)
        # Current spend is 150.0, avg is 50.0
        assert "150" in text
        assert "50" in text

    def test_contains_spike_ratio(self) -> None:
        from burnlens.alerts.slack import _build_spend_spike_payload

        alert = _make_spend_spike_alert()
        payload = _build_spend_spike_payload(alert)
        text = json.dumps(payload)
        # spike_ratio is 3.0 → 300%
        assert "300" in text


class TestSlackWebhookAlertSendDiscovery:
    """Tests for SlackWebhookAlert.send_discovery."""

    @pytest.mark.asyncio
    async def test_send_discovery_shadow_posts_to_webhook(self) -> None:
        slack = SlackWebhookAlert("https://hooks.slack.com/test")
        alert = _make_shadow_alert()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            await slack.send_discovery(alert)

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[0][0] == "https://hooks.slack.com/test"

    @pytest.mark.asyncio
    async def test_send_discovery_provider_posts_to_webhook(self) -> None:
        slack = SlackWebhookAlert("https://hooks.slack.com/test")
        alert = _make_provider_alert()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            await slack.send_discovery(alert)

        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_discovery_does_not_raise_on_exception(self) -> None:
        slack = SlackWebhookAlert("https://hooks.slack.com/test")
        alert = _make_shadow_alert()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("network error"))
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            # Should not raise
            await slack.send_discovery(alert)

    @pytest.mark.asyncio
    async def test_send_spend_spike_posts_to_webhook(self) -> None:
        slack = SlackWebhookAlert("https://hooks.slack.com/test")
        alert = _make_spend_spike_alert()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            await slack.send_spend_spike(alert)

        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_spend_spike_does_not_raise_on_exception(self) -> None:
        slack = SlackWebhookAlert("https://hooks.slack.com/test")
        alert = _make_spend_spike_alert()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("timeout"))
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            # Should not raise
            await slack.send_spend_spike(alert)


# ---------------------------------------------------------------------------
# Task 2: DiscoveryAlertEngine tests
# ---------------------------------------------------------------------------


class TestDiscoveryAlertEngine:
    """Tests for DiscoveryAlertEngine."""

    def _make_config(self, slack_webhook: str | None = "https://hooks.slack.com/test"):
        from burnlens.config import AlertsConfig, BurnLensConfig, EmailConfig

        config = BurnLensConfig()
        config.alerts = AlertsConfig(slack_webhook=slack_webhook, alert_recipients=["ops@example.com"])
        config.email = EmailConfig(smtp_host=None)  # No SMTP — email will be no-op
        return config

    @pytest.mark.asyncio
    async def test_check_shadow_alerts_dispatches_new_events(self, tmp_path) -> None:
        from burnlens.alerts.discovery import DiscoveryAlertEngine

        db_path = str(tmp_path / "test.db")
        config = self._make_config()
        engine = DiscoveryAlertEngine(config, db_path)

        asset = _make_asset()
        event = _make_event(id=42)

        with (
            patch("burnlens.alerts.discovery.get_new_shadow_events_since", new_callable=AsyncMock) as mock_shadow,
            patch("burnlens.alerts.discovery.get_asset_by_id", new_callable=AsyncMock) as mock_asset,
        ):
            mock_shadow.return_value = [event]
            mock_asset.return_value = asset
            engine._slack = MagicMock()
            engine._slack.send_discovery = AsyncMock()
            engine._email = MagicMock()
            engine._email.send = AsyncMock()

            count = await engine.check_shadow_alerts()

        assert count == 1
        engine._slack.send_discovery.assert_called_once()
        engine._email.send.assert_called_once()
        assert 42 in engine._fired_events

    @pytest.mark.asyncio
    async def test_check_shadow_alerts_skips_already_fired(self, tmp_path) -> None:
        from burnlens.alerts.discovery import DiscoveryAlertEngine

        db_path = str(tmp_path / "test.db")
        config = self._make_config()
        engine = DiscoveryAlertEngine(config, db_path)
        engine._fired_events.add(42)  # Pre-populate dedup set

        event = _make_event(id=42)

        with patch("burnlens.alerts.discovery.get_new_shadow_events_since", new_callable=AsyncMock) as mock_shadow:
            mock_shadow.return_value = [event]
            engine._slack = MagicMock()
            engine._slack.send_discovery = AsyncMock()
            engine._email = MagicMock()
            engine._email.send = AsyncMock()

            count = await engine.check_shadow_alerts()

        assert count == 0
        engine._slack.send_discovery.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_shadow_alerts_skips_missing_asset(self, tmp_path) -> None:
        from burnlens.alerts.discovery import DiscoveryAlertEngine

        db_path = str(tmp_path / "test.db")
        config = self._make_config()
        engine = DiscoveryAlertEngine(config, db_path)

        event = _make_event(id=5)

        with (
            patch("burnlens.alerts.discovery.get_new_shadow_events_since", new_callable=AsyncMock) as mock_shadow,
            patch("burnlens.alerts.discovery.get_asset_by_id", new_callable=AsyncMock) as mock_asset,
        ):
            mock_shadow.return_value = [event]
            mock_asset.return_value = None  # Asset missing

            engine._slack = MagicMock()
            engine._slack.send_discovery = AsyncMock()

            count = await engine.check_shadow_alerts()

        assert count == 0

    @pytest.mark.asyncio
    async def test_check_new_provider_alerts_dispatches_correctly(self, tmp_path) -> None:
        from burnlens.alerts.discovery import DiscoveryAlertEngine

        db_path = str(tmp_path / "test.db")
        config = self._make_config()
        engine = DiscoveryAlertEngine(config, db_path)

        asset = _make_asset(provider="anthropic", model_name="claude-3-opus")
        event = _make_event(id=10, event_type="provider_changed")

        with (
            patch("burnlens.alerts.discovery.get_new_provider_events_since", new_callable=AsyncMock) as mock_provider,
            patch("burnlens.alerts.discovery.get_asset_by_id", new_callable=AsyncMock) as mock_asset,
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
        assert 10 in engine._fired_events

    @pytest.mark.asyncio
    async def test_check_spend_spikes_fires_when_ratio_above_threshold(self, tmp_path) -> None:
        from burnlens.alerts.discovery import DiscoveryAlertEngine

        db_path = str(tmp_path / "test.db")
        config = self._make_config()
        engine = DiscoveryAlertEngine(config, db_path)

        asset = _make_asset(id=7, monthly_spend_usd=300.0)

        with (
            patch("burnlens.alerts.discovery.get_assets", new_callable=AsyncMock) as mock_assets,
            patch("burnlens.alerts.discovery.get_asset_spend_history", new_callable=AsyncMock) as mock_history,
        ):
            mock_assets.return_value = [asset]
            mock_history.return_value = 100.0  # 30-day avg = 100.0, current = 300 → ratio 3.0

            engine._slack = MagicMock()
            engine._slack.send_spend_spike = AsyncMock()
            engine._email = MagicMock()
            engine._email.send = AsyncMock()

            count = await engine.check_spend_spikes()

        assert count == 1
        engine._slack.send_spend_spike.assert_called_once()
        assert 7 in engine._fired_spikes

    @pytest.mark.asyncio
    async def test_check_spend_spikes_skips_when_ratio_below_threshold(self, tmp_path) -> None:
        from burnlens.alerts.discovery import DiscoveryAlertEngine

        db_path = str(tmp_path / "test.db")
        config = self._make_config()
        engine = DiscoveryAlertEngine(config, db_path)

        asset = _make_asset(id=8, monthly_spend_usd=150.0)

        with (
            patch("burnlens.alerts.discovery.get_assets", new_callable=AsyncMock) as mock_assets,
            patch("burnlens.alerts.discovery.get_asset_spend_history", new_callable=AsyncMock) as mock_history,
        ):
            mock_assets.return_value = [asset]
            mock_history.return_value = 100.0  # ratio = 1.5, below 2.0 threshold

            engine._slack = MagicMock()
            engine._slack.send_spend_spike = AsyncMock()

            count = await engine.check_spend_spikes()

        assert count == 0
        engine._slack.send_spend_spike.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_spend_spikes_skips_zero_avg(self, tmp_path) -> None:
        from burnlens.alerts.discovery import DiscoveryAlertEngine

        db_path = str(tmp_path / "test.db")
        config = self._make_config()
        engine = DiscoveryAlertEngine(config, db_path)

        asset = _make_asset(id=9, monthly_spend_usd=100.0)

        with (
            patch("burnlens.alerts.discovery.get_assets", new_callable=AsyncMock) as mock_assets,
            patch("burnlens.alerts.discovery.get_asset_spend_history", new_callable=AsyncMock) as mock_history,
        ):
            mock_assets.return_value = [asset]
            mock_history.return_value = 0.0  # No baseline — skip

            engine._slack = MagicMock()
            engine._slack.send_spend_spike = AsyncMock()

            count = await engine.check_spend_spikes()

        assert count == 0

    @pytest.mark.asyncio
    async def test_check_spend_spikes_skips_deprecated_assets(self, tmp_path) -> None:
        from burnlens.alerts.discovery import DiscoveryAlertEngine

        db_path = str(tmp_path / "test.db")
        config = self._make_config()
        engine = DiscoveryAlertEngine(config, db_path)

        deprecated = _make_asset(id=11, status="deprecated", monthly_spend_usd=500.0)
        inactive = _make_asset(id=12, status="inactive", monthly_spend_usd=500.0)

        with (
            patch("burnlens.alerts.discovery.get_assets", new_callable=AsyncMock) as mock_assets,
            patch("burnlens.alerts.discovery.get_asset_spend_history", new_callable=AsyncMock) as mock_history,
        ):
            mock_assets.return_value = [deprecated, inactive]
            mock_history.return_value = 100.0

            engine._slack = MagicMock()
            engine._slack.send_spend_spike = AsyncMock()

            count = await engine.check_spend_spikes()

        assert count == 0

    @pytest.mark.asyncio
    async def test_check_spend_spikes_skips_already_fired(self, tmp_path) -> None:
        from burnlens.alerts.discovery import DiscoveryAlertEngine

        db_path = str(tmp_path / "test.db")
        config = self._make_config()
        engine = DiscoveryAlertEngine(config, db_path)
        engine._fired_spikes.add(7)

        asset = _make_asset(id=7, monthly_spend_usd=300.0)

        with (
            patch("burnlens.alerts.discovery.get_assets", new_callable=AsyncMock) as mock_assets,
            patch("burnlens.alerts.discovery.get_asset_spend_history", new_callable=AsyncMock) as mock_history,
        ):
            mock_assets.return_value = [asset]
            mock_history.return_value = 100.0

            engine._slack = MagicMock()
            engine._slack.send_spend_spike = AsyncMock()

            count = await engine.check_spend_spikes()

        assert count == 0

    @pytest.mark.asyncio
    async def test_run_all_checks_updates_last_check_time(self, tmp_path) -> None:
        from burnlens.alerts.discovery import DiscoveryAlertEngine

        db_path = str(tmp_path / "test.db")
        config = self._make_config()
        engine = DiscoveryAlertEngine(config, db_path)
        original_check = engine._last_check

        with (
            patch("burnlens.alerts.discovery.get_new_shadow_events_since", new_callable=AsyncMock) as mock_shadow,
            patch("burnlens.alerts.discovery.get_new_provider_events_since", new_callable=AsyncMock) as mock_provider,
            patch("burnlens.alerts.discovery.get_assets", new_callable=AsyncMock) as mock_assets,
        ):
            mock_shadow.return_value = []
            mock_provider.return_value = []
            mock_assets.return_value = []

            await engine.run_all_checks()

        # last_check should be updated to a time at or after original
        assert engine._last_check >= original_check

    @pytest.mark.asyncio
    async def test_run_all_checks_is_fail_open(self, tmp_path) -> None:
        """run_all_checks should not raise even if a check fails."""
        from burnlens.alerts.discovery import DiscoveryAlertEngine

        db_path = str(tmp_path / "test.db")
        config = self._make_config()
        engine = DiscoveryAlertEngine(config, db_path)

        with patch(
            "burnlens.alerts.discovery.get_new_shadow_events_since",
            new_callable=AsyncMock,
            side_effect=Exception("DB unavailable"),
        ):
            # Should not raise
            await engine.run_all_checks()

    def test_no_slack_when_webhook_not_configured(self, tmp_path) -> None:
        from burnlens.alerts.discovery import DiscoveryAlertEngine

        db_path = str(tmp_path / "test.db")
        config = self._make_config(slack_webhook=None)
        engine = DiscoveryAlertEngine(config, db_path)

        assert engine._slack is None
