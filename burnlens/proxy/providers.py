"""Compatibility shim — re-exports provider symbols from burnlens.providers.

Deprecated: import from burnlens.providers directly.
Will be removed in v0.4.
"""
from __future__ import annotations

# Trigger provider registration before any symbol is used.
import burnlens.providers as _pkg

from burnlens.providers.base import Provider, ProviderConfig  # noqa: F401
from burnlens.providers.registry import get_by_proxy_path

# Backward-compat list — items are Provider instances, but they expose
# .name, .proxy_prefix, .upstream_base, and .env_var as properties so
# existing code (and tests) that accessed ProviderConfig fields directly
# continues to work without modification.
DEFAULT_PROVIDERS: list[Provider] = list(_pkg.all_providers().values())


def get_provider_for_path(path: str) -> Provider | None:
    """Return the matching provider for a request path, or None."""
    return get_by_proxy_path(path)


def strip_proxy_prefix(path: str, provider: Provider) -> str:
    """Remove the proxy prefix from a path to get the upstream path.

    Works with both the old ProviderConfig (via .proxy_prefix) and new
    Provider instances (which expose .proxy_prefix as a property alias).
    """
    return path[len(provider.proxy_prefix):]


def build_env_exports(host: str, port: int) -> dict[str, str]:
    """Return env-var → proxy-URL mapping for providers that use env vars."""
    base = f"http://{host}:{port}"
    return {
        p.env_var: f"{base}{p.proxy_prefix}"
        for p in DEFAULT_PROVIDERS
        if p.env_var
    }
