"""Azure OpenAI provider — registration, env-based endpoint resolution,
deployment-name model extraction, and inherited OpenAI wire-format handling."""
from __future__ import annotations

import pytest

from burnlens.providers import get, get_by_proxy_path
from burnlens.providers.azure import UPSTREAM_ENV, AzureOpenAIProvider


def test_registered():
    provider = get("azure")
    assert isinstance(provider, AzureOpenAIProvider)
    assert provider.config.proxy_path == "/proxy/azure"
    assert provider.config.auth_header == "api-key"
    assert provider.config.streaming_format == "sse-openai"
    assert provider.config.pricing_key == "openai"


def test_proxy_path_routing():
    provider = get_by_proxy_path("/proxy/azure/openai/deployments/gpt-4o/chat/completions")
    assert provider is not None and provider.config.name == "azure"


def test_upstream_from_env(monkeypatch):
    monkeypatch.setenv(UPSTREAM_ENV, "https://myres.openai.azure.com/")
    provider = get("azure")
    path = "/openai/deployments/gpt-4o/chat/completions?api-version=2024-02-01"
    assert (
        provider.resolve_upstream_url(path, {})
        == "https://myres.openai.azure.com/openai/deployments/gpt-4o/chat/completions?api-version=2024-02-01"
    )


def test_missing_endpoint_raises(monkeypatch):
    monkeypatch.delenv(UPSTREAM_ENV, raising=False)
    with pytest.raises(RuntimeError, match=UPSTREAM_ENV):
        _ = get("azure").upstream_base


def test_model_from_body():
    provider = get("azure")
    assert provider.extract_model({"model": "gpt-4o"}, "/openai/deployments/gpt-4o/chat/completions") == "gpt-4o"


def test_model_from_path_when_body_empty():
    provider = get("azure")
    model = provider.extract_model(
        {}, "/openai/deployments/my-gpt4o/chat/completions?api-version=2024-02-01"
    )
    assert model == "my-gpt4o"


def test_cost_resolves_via_provider_name():
    # The interceptor calls calculate_cost(provider.name, ...) — for azure the
    # name ("azure") differs from the pricing_key ("openai"). Regression guard:
    # this must NOT silently cost $0.
    from burnlens.cost.calculator import calculate_cost, TokenUsage
    from burnlens.cost.pricing import get_model_pricing

    assert get_model_pricing("azure", "gpt-4o") is not None
    cost = calculate_cost("azure", "gpt-4o", TokenUsage(input_tokens=1_000_000, output_tokens=0))
    assert cost > 0


def test_stream_usage_extraction_inherited():
    provider = get("azure")
    chunk = b'data: {"usage":{"prompt_tokens":100,"completion_tokens":25}}\n\n'
    acc: dict = {}
    provider.extract_usage_from_stream_chunk(chunk, acc)
    assert acc["input_tokens"] == 100 and acc["output_tokens"] == 25
