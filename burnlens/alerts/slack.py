"""Slack webhook alert delivery."""
from __future__ import annotations

import json
import logging

import httpx

from burnlens.analysis.budget import BudgetAlert

logger = logging.getLogger(__name__)


def _threshold_emoji(pct: float) -> str:
    if pct >= 100:
        return ":red_circle:"
    if pct >= 90:
        return ":large_yellow_circle:"
    return ":large_blue_circle:"


def _build_payload(alert: BudgetAlert, top_model: str | None) -> dict:
    emoji = _threshold_emoji(alert.pct_used)
    period_label = alert.period.capitalize()
    severity = "OVER BUDGET" if alert.pct_used >= 100 else f"{alert.threshold:.0f}% threshold"

    text = (
        f"{emoji} *BurnLens {period_label} Budget Alert — {severity}*\n"
        f"Spent *${alert.spent_usd:.4f}* of *${alert.budget_usd:.2f}* "
        f"({alert.pct_used:.1f}%) since {alert.period_start}\n"
        f"Forecast: *${alert.forecast_usd:.4f}* for full {alert.period}"
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


class SlackWebhookAlert:
    """Posts budget alerts to a Slack incoming webhook."""

    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url

    async def send(self, alert: BudgetAlert, top_model: str | None = None) -> None:
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
                    "Slack webhook returned %s: %s", resp.status_code, resp.text[:200]
                )
        except Exception as exc:
            logger.warning("Slack alert failed: %s", exc)
