"""Provider plugin interface — base class and config dataclass."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from burnlens.cost.calculator import TokenUsage


@dataclass(frozen=True)
class ProviderConfig:
    name: str            # "openai", "anthropic", "google", etc.
    proxy_path: str      # "/proxy/openai"
    upstream_url: str    # base upstream URL, no trailing slash
    auth_header: str     # "Authorization", "x-api-key", "x-goog-api-key"
    streaming_format: str  # "sse-openai", "sse-anthropic", "sse-google"
    pricing_key: str     # matches pricing_data/{pricing_key}.json
    env_var: str = ""    # SDK env var, e.g. "OPENAI_BASE_URL"; "" if unsupported


class Provider(ABC):
    config: ProviderConfig

    # ------------------------------------------------------------------
    # Backward-compat properties so Provider instances can be used
    # wherever the old ProviderConfig dataclass was expected.
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def proxy_prefix(self) -> str:
        """Alias for config.proxy_path — keeps strip_proxy_prefix working."""
        return self.config.proxy_path

    @property
    def upstream_base(self) -> str:
        """Alias for config.upstream_url — keeps interceptor URL building working."""
        return self.config.upstream_url

    @property
    def env_var(self) -> str:
        return self.config.env_var

    # ------------------------------------------------------------------
    # Abstract interface — every provider must implement these
    # ------------------------------------------------------------------

    @abstractmethod
    def resolve_upstream_url(self, request_path: str, headers: dict[str, str]) -> str:
        """Return the full upstream URL for the given stripped request path."""

    @abstractmethod
    def extract_model(self, request_body: dict, request_path: str) -> Optional[str]:
        """Return model name from request body or path, or None if not found."""

    @abstractmethod
    def extract_usage(self, response_body: dict) -> TokenUsage:
        """Extract token counts from a non-streaming response body."""

    @abstractmethod
    def extract_usage_from_stream_chunk(
        self, chunk: bytes, accumulator: dict
    ) -> Optional[TokenUsage]:
        """Accumulate usage from one SSE chunk into accumulator dict.

        Mutates accumulator in-place.  Returns a complete TokenUsage only
        when this chunk is the definitive final usage event; otherwise None.
        The caller builds the final TokenUsage from the accumulator after
        all chunks are consumed.
        """

    @abstractmethod
    def should_buffer_chunk(self, chunk: bytes) -> bool:
        """Return True if this raw chunk may contain usage data."""

    # ------------------------------------------------------------------
    # Optional overrides
    # ------------------------------------------------------------------

    def normalize_model_name(self, raw_model: str) -> str:
        """Map raw provider model name to pricing key. Default: identity."""
        return raw_model

    def headers_to_strip(self) -> set[str]:
        """BurnLens tag headers to remove before forwarding upstream."""
        return {
            "x-burnlens-tag-feature",
            "x-burnlens-tag-team",
            "x-burnlens-tag-customer",
            "x-burnlens-key",
        }
