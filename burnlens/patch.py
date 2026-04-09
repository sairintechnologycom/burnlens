"""Monkey-patch SDK clients to route through the BurnLens proxy.

Usage::

    import burnlens.patch
    burnlens.patch.patch_all()

OpenAI and Anthropic are handled via env vars (``OPENAI_BASE_URL``,
``ANTHROPIC_BASE_URL``).  The Google ``generativeai`` SDK does not honour
a base-URL env var, so :func:`patch_google` calls ``genai.configure``
directly.
"""
from __future__ import annotations

import os

_DEFAULT_PROXY = "http://127.0.0.1:8420"


def patch_google(proxy: str | None = None) -> None:
    """Configure ``google.generativeai`` to route through BurnLens.

    Args:
        proxy: Base proxy URL.  Defaults to ``BURNLENS_PROXY`` env var
               or ``http://127.0.0.1:8420``.
    """
    import google.generativeai as genai  # type: ignore[import-untyped]

    base = proxy or os.environ.get("BURNLENS_PROXY", _DEFAULT_PROXY)
    endpoint = f"{base.rstrip('/')}/proxy/google"

    genai.configure(
        api_key=os.environ.get("GOOGLE_API_KEY", ""),
        client_options={"api_endpoint": endpoint},
        transport="rest",
    )


def patch_all(proxy: str | None = None) -> None:
    """Patch all supported SDKs to route through BurnLens.

    Currently patches:
    - Google ``generativeai`` (requires ``google-generativeai`` installed)

    OpenAI and Anthropic are handled by env vars set by ``burnlens start``.

    Args:
        proxy: Base proxy URL override.
    """
    try:
        patch_google(proxy=proxy)
    except ImportError:
        pass  # google-generativeai not installed — skip silently
