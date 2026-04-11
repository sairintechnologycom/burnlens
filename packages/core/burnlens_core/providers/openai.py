"""OpenAI billing API integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from burnlens_core.providers.base import UsageProvider

logger = logging.getLogger(__name__)


class OpenAIUsageProvider(UsageProvider):
    """Fetch usage data from the OpenAI organization billing API."""

    def __init__(self, admin_key: str | None = None) -> None:
        self._admin_key = admin_key

    @property
    def provider_name(self) -> str:
        return "openai"

    async def fetch_usage(self, since_hours: int = 24) -> list[dict[str, Any]]:
        if self._admin_key is None:
            logger.warning(
                "openai_admin_key not configured — skipping OpenAI billing API detection. "
                "Set openai_admin_key in config or OPENAI_ADMIN_KEY env var."
            )
            return []

        since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        start_time = int(since.timestamp())

        headers = {
            "Authorization": f"Bearer {self._admin_key}",
            "Content-Type": "application/json",
        }
        params: dict[str, Any] = {
            "start_time": start_time,
            "group_by[]": ["model", "api_key_id"],
        }

        url = "https://api.openai.com/v1/organization/usage/completions"

        def _extract(payload: dict) -> list[dict]:
            results = []
            for bucket in payload.get("data", []):
                results.extend(bucket.get("results", []))
            return results

        return await _paginate_usage(url, headers, params, data_extractor=_extract)


async def _paginate_usage(
    url: str,
    headers: dict[str, str],
    params: dict[str, Any],
    data_extractor: Any = None,
) -> list[dict]:
    """Follow has_more / next_page pagination, collecting all results."""
    all_results: list[dict] = []
    current_params = dict(params)

    async with httpx.AsyncClient() as client:
        while True:
            try:
                response = await client.get(url, headers=headers, params=current_params)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "HTTP error fetching billing data from %s: %s %s",
                    url,
                    exc.response.status_code,
                    exc.response.text[:200],
                )
                break
            except httpx.RequestError as exc:
                logger.error("Request error fetching billing data from %s: %s", url, exc)
                break

            payload = response.json()

            if data_extractor is not None:
                page_results = data_extractor(payload)
            else:
                page_results = payload.get("data", [])

            all_results.extend(page_results)

            if not payload.get("has_more"):
                break

            next_page = payload.get("next_page")
            if not next_page:
                break
            current_params["page"] = next_page

    return all_results
