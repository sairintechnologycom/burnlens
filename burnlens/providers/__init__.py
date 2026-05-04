"""Provider plugin system — auto-registers the three bundled providers on import."""
from burnlens.providers.registry import (  # noqa: F401
    all_providers,
    all_proxy_paths,
    get,
    get_by_proxy_path,
    register,
)
from burnlens.providers.anthropic import anthropic_provider
from burnlens.providers.google import google_provider
from burnlens.providers.openai import openai_provider

register(openai_provider)
register(anthropic_provider)
register(google_provider)
