"""Provider registry — register and look up Provider instances by name or path."""
from __future__ import annotations

from typing import Optional

from burnlens.providers.base import Provider

_PROVIDERS: dict[str, Provider] = {}


def register(provider: Provider) -> None:
    _PROVIDERS[provider.config.name] = provider


def get(name: str) -> Provider:
    if name not in _PROVIDERS:
        raise KeyError(f"Provider not registered: {name}")
    return _PROVIDERS[name]


def all_providers() -> dict[str, Provider]:
    return dict(_PROVIDERS)


def inclusive_prompt_token_providers() -> tuple[str, ...]:
    """Provider names whose stored ``input_tokens`` already includes the cache.

    The single source of truth for anyone who has to add or subtract the cache
    columns — the cost calculator and every query that reports a prompt size.
    Derived from the registry rather than hand-listed so a newly registered
    provider cannot be forgotten; a scan-only source name that is not a
    registered provider (e.g. ``cursor``) is absent and therefore treated as
    disjoint, which is the safe default.
    """
    return tuple(
        sorted(
            name
            for name, p in _PROVIDERS.items()
            if p.config.prompt_tokens_include_cache
        )
    )


def all_proxy_paths() -> dict[str, Provider]:
    return {p.config.proxy_path: p for p in _PROVIDERS.values()}


def get_by_proxy_path(path: str) -> Optional[Provider]:
    """Return the first provider whose proxy_path is a prefix of path."""
    for p in _PROVIDERS.values():
        if path.startswith(p.config.proxy_path):
            return p
    return None
