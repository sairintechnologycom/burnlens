"""OpenAI-compatible providers (Groq / Together / Mistral) — registration,
routing, pricing resolution, and inherited OpenAI wire-format handling."""
from __future__ import annotations

import pytest

from burnlens.cost.calculator import TokenUsage
from burnlens.cost.pricing import get_model_pricing
from burnlens.providers import all_providers, get, get_by_proxy_path
from burnlens.providers.openai_compatible import OpenAICompatibleProvider

NEW_PROVIDERS = ["groq", "together", "mistral"]


@pytest.mark.parametrize("name", NEW_PROVIDERS)
def test_registered(name):
    provider = get(name)
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.config.proxy_path == f"/proxy/{name}"
    assert provider.config.streaming_format == "sse-openai"
    assert provider.config.auth_header == "Authorization"


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/proxy/groq/v1/chat/completions", "groq"),
        ("/proxy/together/v1/chat/completions", "together"),
        ("/proxy/mistral/v1/chat/completions", "mistral"),
        # existing providers must not be shadowed by prefix collisions
        ("/proxy/openai/v1/chat/completions", "openai"),
    ],
)
def test_proxy_path_routing(path, expected):
    provider = get_by_proxy_path(path)
    assert provider is not None
    assert provider.config.name == expected


def test_upstream_url_building():
    groq = get("groq")
    assert (
        groq.resolve_upstream_url("/v1/chat/completions", {})
        == "https://api.groq.com/openai/v1/chat/completions"
    )


@pytest.mark.parametrize(
    "provider,model",
    [
        ("groq", "llama-3.3-70b-versatile"),
        ("together", "deepseek-ai/DeepSeek-R1"),
        ("mistral", "mistral-large-latest"),
    ],
)
def test_pricing_resolves(provider, model):
    p = get_model_pricing(provider, model)
    assert p is not None
    assert p["input_per_million"] > 0
    assert p["output_per_million"] > 0


def test_unknown_model_has_no_pricing():
    assert get_model_pricing("groq", "llama-99-mega") is None


def test_stream_usage_extraction_inherited():
    provider = get("mistral")
    chunk = (
        b'data: {"id":"x","usage":{"prompt_tokens":100,"completion_tokens":25}}\n\n'
        b"data: [DONE]\n\n"
    )
    acc: dict = {}
    provider.extract_usage_from_stream_chunk(chunk, acc)
    assert acc["input_tokens"] == 100
    assert acc["output_tokens"] == 25


def test_non_streaming_usage_extraction_inherited():
    provider = get("groq")
    usage = provider.extract_usage(
        {"usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    )
    assert isinstance(usage, TokenUsage)
    assert usage.input_tokens == 10
    assert usage.output_tokens == 5


def test_registry_contains_all_six():
    names = set(all_providers())
    assert {"openai", "anthropic", "google", *NEW_PROVIDERS} <= names
