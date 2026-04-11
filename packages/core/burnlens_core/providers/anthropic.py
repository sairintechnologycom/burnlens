"""Anthropic billing API integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from burnlens_core.providers.base import UsageProvider

logger = logging.getLogger(__name__)


class AnthropicUsageProvider(UsageProvider):
    """Fetch usage data from the Anthropic organization billing API."""

    def __init__(self, admin_key: str | None = None) -> None:
        self._admin_key = admin_key

    @property
    def provider_name(self) -> str:
        return "anthropic"

    async def fetch_usage(self, since_hours: int = 24) -> list[dict[str, Any]]:
        if self._admin_key is None:
            logger.warning(
                "anthropic_admin_key not configured — skipping Anthropic billing API detection. "
                "Set anthropic_admin_key in config or ANTHROPIC_ADMIN_KEY env var."
            )
            return []

        since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        start_time = since.strftime("%Y-%m-%dT%H:%M:%SZ")

        headers = {
            "x-api-key": self._admin_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        params: dict[str, Any] = {
            "start_time": start_time,
            "group_by[]": "model",
        }

        url = "https://api.anthropic.com/v1/organizations/usage_report/messages"

        # Reuse pagination from openai module (same pattern)
        from burnlens_core.providers.openai import _paginate_usage

        return await _paginate_usage(url, headers, params)
