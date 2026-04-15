"""Slack webhook alert delivery."""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from burnlens.analysis.budget import BudgetAlert
    from burnlens.alerts.types import DiscoveryAlert, SpendSpikeAlert

logger = logging.getLogger(__name__)


def _threshold_emoji(pct: float) -> str:
    if pct >= 100:
        return ":red_circle:"
    if pct >= 90:
        return ":large_yellow_circle:"
    return ":large_blue_circle:"


def _build_payload(alert: BudgetAlert, top_model: str | None = None) -> dict:
    emoji = _threshold_emoji(alert.pct_used)
    period_label = alert.period.capitalize()

    if alert.pct_used >= 100:
        severity = "OVER BUDGET"
    else:
        severity = f"{alert.threshold:.0f}% threshold"

    text = (
        f"{emoji} *BurnLens {period_label} Budget Alert — {severity}*\n"
        f"Spent *${alert.spent_usd:.4f}* of *${alert.budget_usd:.2f}* "
        f"({alert.pct_used:.1f}%) since {alert.period_start}\n"
        f"Forecast: *${alert.forecast_usd:.4f}* for full {period_label}"
    )

    if top_model:
        text += f"\nTop cost driver: `{top_model}`"

    return {
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text},
            }
        ]
    }


def _build_shadow_payload(alert: DiscoveryAlert) -> dict:
    """Build a Slack blocks payload for a shadow AI detection alert.

    Args:
        alert: DiscoveryAlert with alert_type='shadow_detected'.

    Returns:
        Slack blocks payload dict ready for POST to webhook.
    """
    asset = alert.asset
    first_seen = asset.first_seen_at.isoformat() if asset.first_seen_at else "unknown"

    text = (
        f":red_circle: *Shadow AI Detected*\n"
        f"Model: `{asset.model_name}`\n"
        f"Provider: `{asset.provider}`\n"
        f"Endpoint: `{asset.endpoint_url}`\n"
        f"First seen: {first_seen}\n"
        f"Details: {json.dumps(alert.event.details)}"
    )

    return {
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text},
            }
        ]
    }


def _build_new_provider_payload(alert: DiscoveryAlert) -> dict:
    """Build a Slack blocks payload for a new AI provider detection alert.

    Args:
        alert: DiscoveryAlert with alert_type='new_provider'.

    Returns:
        Slack blocks payload dict ready for POST to webhook.
    """
    asset = alert.asset

    text = (
        f":warning: *New AI Provider Detected*\n"
        f"Provider: `{asset.provider}`\n"
        f"Model: `{asset.model_name}`\n"
        f"Endpoint: `{asset.endpoint_url}`"
    )

    return {
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text},
            }
        ]
    }


def _build_spend_spike_payload(alert: SpendSpikeAlert) -> dict:
    """Build a Slack blocks payload for a spend spike alert.

    Args:
        alert: SpendSpikeAlert with current_spend, avg_spend, and spike_ratio.

    Returns:
        Slack blocks payload dict ready for POST to webhook.
    """
    asset = alert.asset
    spike_pct = alert.spike_ratio * 100

    text = (
        f":chart_with_upwards_trend: *Spend Spike Alert*\n"
        f"Model: `{asset.model_name}` ({asset.provider})\n"
        f"Current spend: *${alert.current_spend:.4f}*\n"
        f"{alert.period_days}-day average: *${alert.avg_spend:.4f}*\n"
        f"Spike ratio: *{spike_pct:.0f}%* of average"
    )

    return {
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text},
            }
        ]
    }


class SlackWebhookAlert:
    """Posts budget alerts to a Slack incoming webhook."""

    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url

    async def send(
        self,
        alert: BudgetAlert,
        top_model: str | None = None,
    ) -> None:
        """POST alert to Slack. Errors are logged, never raised."""
        payload = _build_payload(alert, top_model)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    self._webhook_url,
                    content=json.dumps(payload),
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code != 200:
                    logger.warning(
                        "Slack webhook returned %s: %s",
                        resp.status_code,
                        resp.text,
                    )
        except Exception as exc:
            logger.warning("Slack alert failed: %s", exc)

    async def send_discovery(self, alert: DiscoveryAlert) -> None:
        """POST a discovery alert (shadow or new provider) to Slack.

        Routes to the appropriate payload builder based on alert.alert_type.
        Errors are logged and never raised (fail-open).

        Args:
            alert: DiscoveryAlert to dispatch.
        """
        if alert.alert_type == "shadow_detected":
            payload = _build_shadow_payload(alert)
        else:
            payload = _build_new_provider_payload(alert)

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    self._webhook_url,
                    content=json.dumps(payload),
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code != 200:
                    logger.warning(
                        "Slack discovery alert webhook returned %s: %s",
                        resp.status_code,
                        resp.text,
                    )
        except Exception as exc:
            logger.warning("Slack discovery alert failed: %s", exc)

    async def send_spend_spike(self, alert: SpendSpikeAlert) -> None:
        """POST a spend spike alert to Slack.

        Errors are logged and never raised (fail-open).

        Args:
            alert: SpendSpikeAlert to dispatch.
        """
        payload = _build_spend_spike_payload(alert)

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    self._webhook_url,
                    content=json.dumps(payload),
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code != 200:
                    logger.warning(
                        "Slack spend spike webhook returned %s: %s",
                        resp.status_code,
                        resp.text,
                    )
        except Exception as exc:
            logger.warning("Slack spend spike alert failed: %s", exc)
