"""Tests for Phase 4 alert system: email sender, alert types, and discovery queries."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from burnlens.alerts.types import DigestPayload, DiscoveryAlert, SpendSpikeAlert
from burnlens.alerts.email import EmailSender
from burnlens.config import AlertsConfig, EmailConfig, load_config
from burnlens.storage.models import AiAsset, DiscoveryEvent
from burnlens.storage.database import init_db
from burnlens.storage.queries import (
    get_asset_spend_history,
    get_inactive_assets,
    get_model_change_events_since,
    get_new_provider_events_since,
    get_new_shadow_events_since,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_asset() -> AiAsset:
    """Return a sample AiAsset for use in tests."""
    return AiAsset(
        provider="openai",
        model_name="gpt-4o",
        endpoint_url="https://api.openai.com/v1/chat/completions",
        status="shadow",
        risk_tier="high",
    )


@pytest.fixture
def sample_event(sample_asset: AiAsset) -> DiscoveryEvent:
    """Return a sample DiscoveryEvent for use in tests."""
    return DiscoveryEvent(
        event_type="new_asset_detected",
        asset_id=1,
        details={"provider": "openai"},
    )


@pytest.fixture
async def test_db(tmp_path) -> str:
    """Create a fresh test database and return its path."""
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    return db_path


# ---------------------------------------------------------------------------
# Task 1: Alert type dataclass tests
# ---------------------------------------------------------------------------


class TestDiscoveryAlert:
    """Test DiscoveryAlert dataclass construction and fields."""

    def test_construction(self, sample_asset: AiAsset, sample_event: DiscoveryEvent) -> None:
        """DiscoveryAlert can be constructed with required fields."""
        alert = DiscoveryAlert(
            alert_type="shadow_detected",
            asset=sample_asset,
            event=sample_event,
            message="New shadow AI asset detected: gpt-4o",
        )
        assert alert.alert_type == "shadow_detected"
        assert alert.asset is sample_asset
        assert alert.event is sample_event
        assert alert.message == "New shadow AI asset detected: gpt-4o"

    def test_all_event_types(self, sample_asset: AiAsset, sample_event: DiscoveryEvent) -> None:
        """DiscoveryAlert accepts any string as alert_type."""
        for event_type in ["shadow_detected", "new_provider", "model_changed"]:
            alert = DiscoveryAlert(
                alert_type=event_type,
                asset=sample_asset,
                event=sample_event,
                message="Test message",
            )
            assert alert.alert_type == event_type


class TestSpendSpikeAlert:
    """Test SpendSpikeAlert dataclass construction and defaults."""

    def test_construction(self, sample_asset: AiAsset) -> None:
        """SpendSpikeAlert can be constructed with required fields."""
        alert = SpendSpikeAlert(
            asset=sample_asset,
            current_spend=150.0,
            avg_spend=50.0,
            spike_ratio=3.0,
        )
        assert alert.asset is sample_asset
        assert alert.current_spend == 150.0
        assert alert.avg_spend == 50.0
        assert alert.spike_ratio == 3.0
        assert alert.period_days == 30  # default

    def test_custom_period(self, sample_asset: AiAsset) -> None:
        """SpendSpikeAlert accepts a custom period_days."""
        alert = SpendSpikeAlert(
            asset=sample_asset,
            current_spend=200.0,
            avg_spend=100.0,
            spike_ratio=2.0,
            period_days=7,
        )
        assert alert.period_days == 7


class TestDigestPayload:
    """Test DigestPayload dataclass construction and fields."""

    def test_construction(self) -> None:
        """DigestPayload can be constructed with required fields."""
        now = datetime.utcnow()
        payload = DigestPayload(
            subject="Weekly AI Asset Digest",
            items=[{"asset": "gpt-4o", "spend": 42.0}],
            generated_at=now,
        )
        assert payload.subject == "Weekly AI Asset Digest"
        assert len(payload.items) == 1
        assert payload.generated_at == now

    def test_empty_items(self) -> None:
        """DigestPayload works with an empty items list."""
        payload = DigestPayload(
            subject="Empty digest",
            items=[],
            generated_at=datetime.utcnow(),
        )
        assert payload.items == []


# ---------------------------------------------------------------------------
# Task 1: EmailSender tests
# ---------------------------------------------------------------------------


class TestEmailSender:
    """Test EmailSender class behavior."""

    def test_no_op_when_smtp_host_none(self) -> None:
        """EmailSender does not raise when smtp_host is None."""
        cfg = EmailConfig(smtp_host=None)
        sender = EmailSender(cfg)
        assert sender is not None

    @pytest.mark.asyncio
    async def test_send_is_noop_when_smtp_host_none(self) -> None:
        """send() is a no-op (returns without error) when smtp_host is None."""
        cfg = EmailConfig(smtp_host=None)
        sender = EmailSender(cfg)
        # Should not raise
        await sender.send(
            to_addrs=["test@example.com"],
            subject="Test",
            body_html="<p>Test</p>",
        )

    @pytest.mark.asyncio
    async def test_send_calls_smtplib_when_configured(self) -> None:
        """send() calls smtplib.SMTP when smtp_host is configured."""
        cfg = EmailConfig(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="secret",
            from_addr="noreply@example.com",
        )
        sender = EmailSender(cfg)

        mock_smtp_instance = MagicMock()
        mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=mock_smtp_instance) as mock_smtp_cls:
            await sender.send(
                to_addrs=["recipient@example.com"],
                subject="Test Subject",
                body_html="<p>Hello</p>",
            )

        mock_smtp_cls.assert_called_once_with("smtp.example.com", 587)
        mock_smtp_instance.starttls.assert_called_once()
        mock_smtp_instance.login.assert_called_once_with("user@example.com", "secret")
        mock_smtp_instance.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_catches_smtp_error(self) -> None:
        """send() catches SMTP errors and does not raise (fail-open)."""
        cfg = EmailConfig(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="secret",
            from_addr="noreply@example.com",
        )
        sender = EmailSender(cfg)

        with patch("smtplib.SMTP", side_effect=Exception("Connection refused")):
            # Should not raise
            await sender.send(
                to_addrs=["recipient@example.com"],
                subject="Test Subject",
                body_html="<p>Hello</p>",
            )

    @pytest.mark.asyncio
    async def test_send_uses_asyncio_to_thread(self) -> None:
        """send() wraps smtplib calls in asyncio.to_thread for non-blocking I/O."""
        cfg = EmailConfig(
            smtp_host="smtp.example.com",
            smtp_port=25,  # Plain SMTP (no STARTTLS)
            smtp_user=None,
            smtp_password=None,
            from_addr="from@example.com",
        )
        sender = EmailSender(cfg)

        mock_smtp_instance = MagicMock()
        mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)

        call_thread_ids: list[int] = []

        original_to_thread = asyncio.to_thread

        async def patched_to_thread(func, *args, **kwargs):
            result = await original_to_thread(func, *args, **kwargs)
            call_thread_ids.append(1)
            return result

        with patch("smtplib.SMTP", return_value=mock_smtp_instance):
            with patch("asyncio.to_thread", side_effect=patched_to_thread) as mock_to_thread:
                await sender.send(
                    to_addrs=["r@example.com"],
                    subject="S",
                    body_html="<b>B</b>",
                )
                mock_to_thread.assert_called_once()


# ---------------------------------------------------------------------------
# Task 1: AlertsConfig tests
# ---------------------------------------------------------------------------


class TestAlertsConfig:
    """Test AlertsConfig.alert_recipients field."""

    def test_alert_recipients_defaults_to_empty_list(self) -> None:
        """AlertsConfig.alert_recipients defaults to an empty list."""
        cfg = AlertsConfig()
        assert cfg.alert_recipients == []

    def test_alert_recipients_can_be_set(self) -> None:
        """AlertsConfig.alert_recipients can be set to a list of email addresses."""
        cfg = AlertsConfig(alert_recipients=["a@example.com", "b@example.com"])
        assert cfg.alert_recipients == ["a@example.com", "b@example.com"]

    def test_load_config_parses_alert_recipients(self, tmp_path) -> None:
        """load_config() parses alerts.alert_recipients from YAML."""
        yaml_content = """
alerts:
  alert_recipients:
    - "devops@example.com"
    - "platform@example.com"
"""
        config_file = tmp_path / "burnlens.yaml"
        config_file.write_text(yaml_content)

        cfg = load_config(str(config_file))
        assert cfg.alerts.alert_recipients == ["devops@example.com", "platform@example.com"]

    def test_load_config_alert_recipients_defaults_when_absent(self, tmp_path) -> None:
        """load_config() defaults alert_recipients to [] when not in YAML."""
        yaml_content = """
alerts:
  terminal: true
"""
        config_file = tmp_path / "burnlens.yaml"
        config_file.write_text(yaml_content)

        cfg = load_config(str(config_file))
        assert cfg.alerts.alert_recipients == []


# ---------------------------------------------------------------------------
# Task 2: Discovery alert query tests
# ---------------------------------------------------------------------------


async def _insert_asset(db_path: str, **overrides) -> int:
    """Helper: insert a minimal AiAsset and return its id."""
    import aiosqlite

    now = datetime.utcnow().isoformat()
    defaults = {
        "provider": "openai",
        "model_name": "gpt-4o",
        "endpoint_url": "https://api.openai.com/v1/chat/completions",
        "api_key_hash": None,
        "owner_team": None,
        "project": None,
        "status": "shadow",
        "risk_tier": "unclassified",
        "first_seen_at": now,
        "last_active_at": now,
        "monthly_spend_usd": 0.0,
        "monthly_requests": 0,
        "tags": "{}",
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO ai_assets
                (provider, model_name, endpoint_url, api_key_hash, owner_team, project,
                 status, risk_tier, first_seen_at, last_active_at,
                 monthly_spend_usd, monthly_requests, tags, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                defaults["provider"], defaults["model_name"], defaults["endpoint_url"],
                defaults["api_key_hash"], defaults["owner_team"], defaults["project"],
                defaults["status"], defaults["risk_tier"],
                defaults["first_seen_at"], defaults["last_active_at"],
                defaults["monthly_spend_usd"], defaults["monthly_requests"],
                defaults["tags"], defaults["created_at"], defaults["updated_at"],
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def _insert_event(db_path: str, event_type: str, asset_id: int | None, detected_at: str, details: dict | None = None) -> int:
    """Helper: insert a DiscoveryEvent and return its id."""
    import aiosqlite

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "INSERT INTO discovery_events (event_type, asset_id, details, detected_at) VALUES (?, ?, ?, ?)",
            (event_type, asset_id, json.dumps(details or {}), detected_at),
        )
        await db.commit()
        return cursor.lastrowid


async def _insert_request(db_path: str, provider: str, model: str, cost_usd: float, timestamp: str) -> None:
    """Helper: insert a minimal request record for spend history testing."""
    import aiosqlite

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO requests
                (provider, model, request_path, timestamp, input_tokens, output_tokens,
                 cost_usd, duration_ms, status_code, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (provider, model, "/v1/chat/completions", timestamp, 100, 50, cost_usd, 200, 200, "{}"),
        )
        await db.commit()


class TestGetNewShadowEventsSince:
    """Tests for get_new_shadow_events_since query."""

    @pytest.mark.asyncio
    async def test_returns_shadow_events_after_cutoff(self, test_db: str) -> None:
        """Returns new_asset_detected events detected after since_iso."""
        cutoff = "2026-04-01T00:00:00"
        asset_id = await _insert_asset(test_db)

        # Before cutoff — should NOT be returned
        await _insert_event(test_db, "new_asset_detected", asset_id, "2026-03-31T12:00:00")
        # After cutoff — should be returned
        event_id = await _insert_event(test_db, "new_asset_detected", asset_id, "2026-04-02T10:00:00")
        # Different event type — should NOT be returned
        await _insert_event(test_db, "model_changed", asset_id, "2026-04-03T10:00:00")

        events = await get_new_shadow_events_since(test_db, cutoff)
        assert len(events) == 1
        assert events[0].id == event_id
        assert events[0].event_type == "new_asset_detected"

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_shadow_events(self, test_db: str) -> None:
        """Returns empty list when no matching events exist."""
        events = await get_new_shadow_events_since(test_db, "2026-01-01T00:00:00")
        assert events == []


class TestGetNewProviderEventsSince:
    """Tests for get_new_provider_events_since query."""

    @pytest.mark.asyncio
    async def test_returns_provider_changed_events(self, test_db: str) -> None:
        """Returns provider_changed events detected after since_iso."""
        cutoff = "2026-04-01T00:00:00"
        asset_id = await _insert_asset(test_db)

        event_id = await _insert_event(test_db, "provider_changed", asset_id, "2026-04-05T08:00:00")
        # Old event — should NOT be returned
        await _insert_event(test_db, "provider_changed", asset_id, "2026-03-15T08:00:00")
        # Different type
        await _insert_event(test_db, "new_asset_detected", asset_id, "2026-04-06T08:00:00")

        events = await get_new_provider_events_since(test_db, cutoff)
        assert len(events) == 1
        assert events[0].id == event_id
        assert events[0].event_type == "provider_changed"


class TestGetModelChangeEventsSince:
    """Tests for get_model_change_events_since query."""

    @pytest.mark.asyncio
    async def test_returns_model_changed_events(self, test_db: str) -> None:
        """Returns model_changed events detected after since_iso."""
        cutoff = "2026-04-01T00:00:00"
        asset_id = await _insert_asset(test_db)

        event_id = await _insert_event(test_db, "model_changed", asset_id, "2026-04-04T09:00:00")
        # Old event — should NOT be returned
        await _insert_event(test_db, "model_changed", asset_id, "2026-03-10T09:00:00")

        events = await get_model_change_events_since(test_db, cutoff)
        assert len(events) == 1
        assert events[0].id == event_id
        assert events[0].event_type == "model_changed"


class TestGetInactiveAssets:
    """Tests for get_inactive_assets query."""

    @pytest.mark.asyncio
    async def test_returns_assets_inactive_longer_than_threshold(self, test_db: str) -> None:
        """Returns assets with last_active_at older than inactive_days."""
        old_date = (datetime.utcnow() - timedelta(days=45)).isoformat()
        recent_date = (datetime.utcnow() - timedelta(days=5)).isoformat()

        old_id = await _insert_asset(test_db, last_active_at=old_date, model_name="old-model")
        await _insert_asset(test_db, last_active_at=recent_date, model_name="new-model")

        inactive = await get_inactive_assets(test_db, inactive_days=30)
        ids = [a.id for a in inactive]
        assert old_id in ids
        # Recent asset should not be in the list
        assert all(a.model_name != "new-model" for a in inactive)

    @pytest.mark.asyncio
    async def test_excludes_deprecated_and_inactive_status(self, test_db: str) -> None:
        """Assets with status deprecated or inactive are excluded."""
        old_date = (datetime.utcnow() - timedelta(days=60)).isoformat()

        await _insert_asset(test_db, last_active_at=old_date, status="deprecated", model_name="dep-model")
        await _insert_asset(test_db, last_active_at=old_date, status="inactive", model_name="inact-model")
        shadow_id = await _insert_asset(test_db, last_active_at=old_date, status="shadow", model_name="shadow-model")

        inactive = await get_inactive_assets(test_db, inactive_days=30)
        ids = [a.id for a in inactive]
        assert shadow_id in ids
        assert all(a.status not in ("deprecated", "inactive") for a in inactive)

    @pytest.mark.asyncio
    async def test_returns_empty_when_all_assets_active(self, test_db: str) -> None:
        """Returns empty list when no assets are inactive."""
        recent_date = (datetime.utcnow() - timedelta(days=1)).isoformat()
        await _insert_asset(test_db, last_active_at=recent_date)

        inactive = await get_inactive_assets(test_db, inactive_days=30)
        assert inactive == []


class TestGetAssetSpendHistory:
    """Tests for get_asset_spend_history query."""

    @pytest.mark.asyncio
    async def test_returns_total_spend_for_asset(self, test_db: str) -> None:
        """Returns total spend for an asset's model+provider over the period."""
        asset_id = await _insert_asset(test_db, provider="openai", model_name="gpt-4o")

        recent_ts = (datetime.utcnow() - timedelta(days=5)).isoformat()
        await _insert_request(test_db, "openai", "gpt-4o", 0.25, recent_ts)
        await _insert_request(test_db, "openai", "gpt-4o", 0.30, recent_ts)

        total = await get_asset_spend_history(test_db, asset_id, days=30)
        assert abs(total - 0.55) < 0.001

    @pytest.mark.asyncio
    async def test_excludes_old_requests_outside_period(self, test_db: str) -> None:
        """Only includes requests within the specified days period."""
        asset_id = await _insert_asset(test_db, provider="openai", model_name="gpt-4o")

        # Old request outside 30-day window
        old_ts = (datetime.utcnow() - timedelta(days=60)).isoformat()
        await _insert_request(test_db, "openai", "gpt-4o", 1.00, old_ts)

        total = await get_asset_spend_history(test_db, asset_id, days=30)
        assert total == 0.0

    @pytest.mark.asyncio
    async def test_returns_zero_for_nonexistent_asset(self, test_db: str) -> None:
        """Returns 0.0 when the asset_id does not exist."""
        total = await get_asset_spend_history(test_db, asset_id=9999, days=30)
        assert total == 0.0

    @pytest.mark.asyncio
    async def test_excludes_other_models_spend(self, test_db: str) -> None:
        """Does not include spend from other models/providers."""
        asset_id = await _insert_asset(test_db, provider="openai", model_name="gpt-4o")

        recent_ts = (datetime.utcnow() - timedelta(days=3)).isoformat()
        # Matching
        await _insert_request(test_db, "openai", "gpt-4o", 0.50, recent_ts)
        # Different model — should not be included
        await _insert_request(test_db, "openai", "gpt-4-turbo", 5.00, recent_ts)
        # Different provider
        await _insert_request(test_db, "anthropic", "gpt-4o", 3.00, recent_ts)

        total = await get_asset_spend_history(test_db, asset_id, days=30)
        assert abs(total - 0.50) < 0.001
