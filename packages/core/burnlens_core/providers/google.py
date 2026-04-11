"""Google billing API integration (stub — proxy-only detection)."""
from __future__ import annotations

import logging
from typing import Any

from burnlens_core.providers.base import UsageProvider

logger = logging.getLogger(__name__)


class GoogleUsageProvider(UsageProvider):
    """Google billing API detection stub.

    Google Generative AI does not expose a billing/usage admin API with
    per-model breakdown suitable for this detection pattern. Detection for
    Google happens through proxy traffic analysis instead.
    """

    def __init__(self, admin_key: str | None = None) -> None:
        self._admin_key = admin_key

    @property
    def provider_name(self) -> str:
        return "google"

    async def fetch_usage(self, since_hours: int = 24) -> list[dict[str, Any]]:
        logger.info(
            "Google detection uses proxy traffic only (no billing API available). "
            "Google AI usage will be captured automatically via the BurnLens proxy."
        )
        return []
