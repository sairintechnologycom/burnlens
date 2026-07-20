"""OpenAI-compatible provider plugin.

Groq, Together, and Mistral all speak the OpenAI chat-completions wire
format (request body, response usage block, and SSE streaming shape), so
each is OpenAIProvider with a different config — no new parsing code.
"""
from __future__ import annotations

from burnlens.providers.base import ProviderConfig
from burnlens.providers.openai import OpenAIProvider


class OpenAICompatibleProvider(OpenAIProvider):
    """An OpenAI-wire-format provider addressed by its own proxy path.

    Inherits all request/response/stream handling from OpenAIProvider;
    only the routing config differs per service.
    """

    def __init__(self, name: str, upstream_url: str, env_var: str = "") -> None:
        self.config = ProviderConfig(
            name=name,
            proxy_path=f"/proxy/{name}",
            upstream_url=upstream_url,
            auth_header="Authorization",
            streaming_format="sse-openai",
            pricing_key=name,
            env_var=env_var,
        )


groq_provider = OpenAICompatibleProvider(
    "groq", "https://api.groq.com/openai", env_var="GROQ_BASE_URL"
)
together_provider = OpenAICompatibleProvider("together", "https://api.together.xyz")
mistral_provider = OpenAICompatibleProvider("mistral", "https://api.mistral.ai")
xai_provider = OpenAICompatibleProvider(
    "xai", "https://api.x.ai", env_var="XAI_BASE_URL"
)
deepseek_provider = OpenAICompatibleProvider(
    "deepseek", "https://api.deepseek.com", env_var="DEEPSEEK_BASE_URL"
)
