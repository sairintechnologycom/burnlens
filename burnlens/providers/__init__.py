"""Provider plugin system — auto-registers the bundled providers on import."""
from burnlens.providers.registry import (  # noqa: F401
    all_providers,
    all_proxy_paths,
    get,
    get_by_proxy_path,
    register,
)
from burnlens.providers.anthropic import anthropic_provider
from burnlens.providers.azure import azure_provider
from burnlens.providers.google import google_provider
from burnlens.providers.openai import openai_provider
from burnlens.providers.openai_compatible import (
    groq_provider,
    mistral_provider,
    together_provider,
)

register(openai_provider)
register(anthropic_provider)
register(google_provider)
register(groq_provider)
register(together_provider)
register(mistral_provider)
register(azure_provider)
