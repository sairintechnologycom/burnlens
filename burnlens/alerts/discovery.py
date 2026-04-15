"""DiscoveryAlertEngine -- detects and dispatches real-time alerts for shadow assets.

Covers three alert categories:
  - Shadow AI asset detected (ALRT-01)
  - New AI provider detected (ALRT-02)
  - Unusual spend spike on an asset (ALRT-05)

Deduplication prevents the same event or asset from triggering multiple
alerts for the lifetime of the engine process. The engine is fail-open:
errors in any individual check are caught and logged so the proxy is never
disrupted.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from burnlens.alerts.email import EmailSender
    from burnlens.alerts.slack import SlackWebhookAlert

from burnlens.alerts.types import DiscoveryAlert, SpendSpikeAlert
from burnlens.storage.database import mark_alert_fired, was_alert_fired
from burnlens.storage.queries import (
    get_asset_by_id,
    get_asset_spend_history,
    get_assets,
    get_new_provider_events_since,
    get_new_shadow_events_since,
)
from burnlens.config import BurnLensConfig

logger = logging.getLogger(__name__)


class DiscoveryAlertEngine:
    """Engine that queries for new discovery events and dispatches alerts.

    Designed to be called on a schedule (e.g. hourly).  Each call to
    run_all_checks() processes shadow, provider, and spend-spike events
    since the previous check, dispatches to Slack and email, and
    deduplicates so the same event never fires twice.

    Args:
        config:   BurnLensConfig instance with alert and email configuration.
        db_path:  Path to the SQLite database file.
    """

    def __init__(self, config: BurnLensConfig, db_path: str) -> None:
        self._config = config
        self._db_path = db_path

        if config.alerts.slack_webhook:
            from burnlens.alerts.slack import SlackWebhookAlert
            self._slack = SlackWebhookAlert(config.alerts.slack_webhook)
        else:
            self._slack = None

        from burnlens.alerts.email import EmailSender
        self._email = EmailSender(config.email)

        self._last_check = datetime.now(timezone.utc).isoformat()
        self.db_path = db_path

    async def check_shadow_alerts(self) -> int:
        """Fetch new shadow-asset events and dispatch alerts for each unseen one.

        Returns:
            Number of alerts dispatched.
        """
        events = await get_new_shadow_events_since(self._db_path, self._last_check)
        count = 0

        for event in events:
            alert_key = f"shadow:asset_{event.asset_id}"
            try:
                if await was_alert_fired(self.db_path, alert_key, "shadow_detected", within_hours=24):
                    continue
            except Exception:
                logger.warning("DB dedup check failed for %s, allowing alert to fire", alert_key, exc_info=True)

            asset = await get_asset_by_id(self._db_path, event.asset_id)
            if asset is None:
                logger.debug("check_shadow_alerts: asset %s not found, skipping", event.asset_id)
                continue

            alert = DiscoveryAlert(
                alert_type="shadow_detected",
                asset=asset,
                event=event,
                message=f"Shadow AI detected: {asset.model_name} on {asset.provider}",
            )
            await self._dispatch_discovery_alert(alert)

            try:
                await mark_alert_fired(self.db_path, alert_key, "shadow_detected")
            except Exception:
                logger.warning("DB dedup mark failed for %s", alert_key, exc_info=True)

            count += 1

        return count

    async def check_new_provider_alerts(self) -> int:
        """Fetch new provider-change events and dispatch alerts for each unseen one.

        Returns:
            Number of alerts dispatched.
        """
        events = await get_new_provider_events_since(self._db_path, self._last_check)
        count = 0

        for event in events:
            alert_key = f"provider:asset_{event.asset_id}"
            try:
                if await was_alert_fired(self.db_path, alert_key, "new_provider", within_hours=72):
                    continue
            except Exception:
                logger.warning("DB dedup check failed for %s, allowing alert to fire", alert_key, exc_info=True)

            asset = await get_asset_by_id(self._db_path, event.asset_id)
            if asset is None:
                logger.debug("check_new_provider_alerts: asset %s not found, skipping", event.asset_id)
                continue

            alert = DiscoveryAlert(
                alert_type="new_provider",
                asset=asset,
                event=event,
                message=f"New AI provider detected: {asset.provider}",
            )
            await self._dispatch_discovery_alert(alert)

            try:
                await mark_alert_fired(self.db_path, alert_key, "new_provider")
            except Exception:
                logger.warning("DB dedup mark failed for %s", alert_key, exc_info=True)

            count += 1

        return count

    async def check_spend_spikes(self) -> int:
        """Check all active assets for spend spikes above 200% of 30-day average.

        Returns:
            Number of spike alerts dispatched.
        """
        assets = await get_assets(self._db_path, limit=500)
        count = 0

        for asset in assets:
            if asset.status in ("deprecated", "inactive"):
                continue

            alert_key = f"spike:asset_{asset.id}"
            try:
                if await was_alert_fired(self.db_path, alert_key, "spend_spike", within_hours=6):
                    continue
            except Exception:
                logger.warning("DB dedup check failed for %s, allowing alert to fire", alert_key, exc_info=True)

            avg_spend = await get_asset_spend_history(self._db_path, asset.id, days=30)
            if avg_spend == 0:
                continue

            spike_ratio = asset.monthly_spend_usd / avg_spend
            if spike_ratio < 2.0:
                continue

            alert = SpendSpikeAlert(
                asset=asset,
                current_spend=asset.monthly_spend_usd,
                avg_spend=avg_spend,
                spike_ratio=spike_ratio,
                period_days=30,
            )
            await self._dispatch_spend_spike_alert(alert)

            try:
                await mark_alert_fired(self.db_path, alert_key, "spend_spike")
            except Exception:
                logger.warning("DB dedup mark failed for %s", alert_key, exc_info=True)

            count += 1

        return count

    async def run_all_checks(self) -> None:
        """Run all three check methods and update last_check_time.

        Each individual check is wrapped in its own try/except so a failure
        in one check does not prevent the others from running (fail-open).
        """
        try:
            await self.check_shadow_alerts()
        except Exception as exc:
            logger.error("DiscoveryAlertEngine.check_shadow_alerts failed: %s", exc)

        try:
            await self.check_new_provider_alerts()
        except Exception as exc:
            logger.error("DiscoveryAlertEngine.check_new_provider_alerts failed: %s", exc)

        try:
            await self.check_spend_spikes()
        except Exception as exc:
            logger.error("DiscoveryAlertEngine.check_spend_spikes failed: %s", exc)

        self._last_check = datetime.now(timezone.utc).isoformat()

    async def _dispatch_discovery_alert(self, alert: DiscoveryAlert) -> None:
        """Dispatch a DiscoveryAlert to Slack and email.

        Both dispatches are fail-open -- exceptions are caught by the
        individual send methods and logged.
        """
        if self._slack:
            await self._slack.send_discovery(alert)

        if self._config.alerts.alert_recipients:
            subject, body_html = _build_alert_email_html(alert)
            await self._email.send(
                to_addrs=self._config.alerts.alert_recipients,
                subject=subject,
                body_html=body_html,
            )

    async def _dispatch_spend_spike_alert(self, alert: SpendSpikeAlert) -> None:
        """Dispatch a SpendSpikeAlert to Slack and email.

        Both dispatches are fail-open.
        """
        if self._slack:
            await self._slack.send_spend_spike(alert)

        if self._config.alerts.alert_recipients:
            subject, body_html = _build_alert_email_html(alert)
            await self._email.send(
                to_addrs=self._config.alerts.alert_recipients,
                subject=subject,
                body_html=body_html,
            )


def _build_alert_email_html(alert: DiscoveryAlert | SpendSpikeAlert) -> tuple[str, str]:
    """Build (subject, html_body) for an alert email.

    Generates a simple HTML table with alert details suitable for sending
    via EmailSender.

    Args:
        alert: Either a DiscoveryAlert or SpendSpikeAlert instance.

    Returns:
        Tuple of (subject line, HTML body string).
    """
    if isinstance(alert, DiscoveryAlert):
        if alert.alert_type == "shadow_detected":
            subject = f"[BurnLens] Shadow AI Detected: {alert.asset.model_name} on {alert.asset.provider}"
        else:
            subject = f"[BurnLens] New AI Provider Detected: {alert.asset.provider}"

        first_seen = alert.asset.first_seen_at.isoformat() if alert.asset.first_seen_at else "unknown"

        rows = [
            ("Alert Type", alert.alert_type),
            ("Model", alert.asset.model_name),
            ("Provider", alert.asset.provider),
            ("Endpoint", alert.asset.endpoint_url),
            ("First Seen", first_seen),
            ("Message", alert.message),
        ]
    else:
        subject = (
            f"[BurnLens] Spend Spike: {alert.asset.model_name}"
            f" ({alert.spike_ratio * 100:.0f}% of {alert.period_days}-day average)"
        )

        rows = [
            ("Model", alert.asset.model_name),
            ("Provider", alert.asset.provider),
            ("Current Spend (USD)", f"${alert.current_spend:.4f}"),
            (f"{alert.period_days}-Day Average (USD)", f"${alert.avg_spend:.4f}"),
            ("Spike Ratio", f"{alert.spike_ratio * 100:.0f}%"),
        ]

    table_rows_html = "".join(
        f"<tr><td><strong>{label}</strong></td><td>{value}</td></tr>"
        for label, value in rows
    )

    html_body = (
        f"\n<html><body>\n"
        f"<h2>{subject}</h2>\n"
        f'<table border="1" cellpadding="6" cellspacing="0">\n'
        f"{table_rows_html}\n"
        f"</table>\n"
        f'<p style="color: #888; font-size: 11px;">Sent by BurnLens alert engine.</p>\n'
        f"</body></html>\n"
    )

    return subject, html_body
