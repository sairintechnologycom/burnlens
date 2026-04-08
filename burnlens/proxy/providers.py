"""Provider routing config — maps proxy path prefixes to upstream URLs."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    """Routing and extraction config for one AI provider."""

    name: str               # openai | anthropic | google
    proxy_prefix: str       # path prefix as seen by clients, e.g. /proxy/openai
    upstream_base: str      # upstream base URL (no trailing slash)
    env_var: str            # SDK env var to set, e.g. OPENAI_BASE_URL


# Default provider table — overridden at runtime by BurnLensConfig upstreams
DEFAULT_PROVIDERS: list[ProviderConfig] = [
    ProviderConfig(
        name="openai",
        proxy_prefix="/proxy/openai",
        upstream_base="https://api.openai.com",
        env_var="OPENAI_BASE_URL",
    ),
    ProviderConfig(
        name="anthropic",
        proxy_prefix="/proxy/anthropic",
        upstream_base="https://api.anthropic.com",
        env_var="ANTHROPIC_BASE_URL",
    ),
    ProviderConfig(
        name="google",
        proxy_prefix="/proxy/google",
        upstream_base="https://generativelanguage.googleapis.com",
        env_var="GOOGLE_AI_BASE_URL",
    ),
]


def get_provider_for_path(path: str) -> ProviderConfig | None:
    """Return the matching ProviderConfig for a request path, or None."""
    for provider in DEFAULT_PROVIDERS:
        if path.startswith(provider.proxy_prefix):
            return provider
    return None


def strip_proxy_prefix(path: str, provider: ProviderConfig) -> str:
    """Remove the proxy prefix from a path to get the upstream path.

    Example: ``/proxy/openai/v1/chat/completions`` → ``/v1/chat/completions``
    """
    return path[len(provider.proxy_prefix):]


def build_env_exports(host: str, port: int) -> dict[str, str]:
    """Return a dict of env var → proxy URL for all providers."""
    base = f"http://{host}:{port}"
    return {p.env_var: f"{base}{p.proxy_prefix}" for p in DEFAULT_PROVIDERS}
