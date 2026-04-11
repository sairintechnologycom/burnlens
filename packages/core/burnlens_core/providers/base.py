"""Abstract base class for provider billing API integrations.

Follows the TokenLens UsageProvider ABC pattern: each provider implements
fetch_usage() to retrieve usage data from their admin/billing API.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class UsageProvider(ABC):
    """Abstract interface for fetching usage data from a provider's billing API."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the canonical provider name (e.g. 'openai', 'anthropic')."""
        ...

    @abstractmethod
    async def fetch_usage(self, since_hours: int = 24) -> list[dict[str, Any]]:
        """Fetch usage data from the provider's billing API.

        Args:
            since_hours: How many hours back to query.

        Returns:
            List of usage records. Each record should contain at minimum:
            - model: str — the model name
            - input_tokens: int — total input tokens
            - output_tokens: int — total output tokens
            Other provider-specific fields may also be present.
        """
        ...

    def endpoint_url(self) -> str:
        """Return the canonical API endpoint URL for this provider."""
        return _CANONICAL_URLS.get(self.provider_name, f"https://{self.provider_name}.api")


_CANONICAL_URLS = {
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
    "google": "https://generativelanguage.googleapis.com",
    "azure_openai": "https://openai.azure.com",
    "bedrock": "https://bedrock-runtime.amazonaws.com",
    "cohere": "https://api.cohere.com",
    "mistral": "https://api.mistral.ai",
}
