"""Tests for the provider plugin architecture (burnlens/providers/)."""
from __future__ import annotations

import pytest

import burnlens.providers as providers_pkg
from burnlens.providers.base import Provider, ProviderConfig
from burnlens.providers.registry import (
    get,
    get_by_proxy_path,
    all_providers,
    register,
    _PROVIDERS,
)
from burnlens.providers.anthropic import anthropic_provider
from burnlens.providers.google import google_provider
from burnlens.providers.openai import openai_provider
from burnlens.cost.calculator import TokenUsage


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_register_and_get(self):
        name = openai_provider.config.name
        assert get(name) is openai_provider

    def test_get_unknown_raises_key_error(self):
        with pytest.raises(KeyError, match="not registered"):
            get("nonexistent-provider-xyz")

    def test_get_by_proxy_path_matches_prefix(self):
        result = get_by_proxy_path("/proxy/openai/v1/chat/completions")
        assert result is not None
        assert result.config.name == "openai"

    def test_get_by_proxy_path_anthropic(self):
        result = get_by_proxy_path("/proxy/anthropic/v1/messages")
        assert result is not None
        assert result.config.name == "anthropic"

    def test_get_by_proxy_path_google(self):
        result = get_by_proxy_path("/proxy/google/v1beta/models/gemini:generateContent")
        assert result is not None
        assert result.config.name == "google"

    def test_get_by_proxy_path_returns_none_on_miss(self):
        assert get_by_proxy_path("/proxy/unknown/v1/foo") is None

    def test_get_by_proxy_path_returns_none_empty(self):
        assert get_by_proxy_path("/") is None


# ---------------------------------------------------------------------------
# All three providers registered on import
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_all_three_providers_registered(self):
        registered = all_providers()
        assert "openai" in registered
        assert "anthropic" in registered
        assert "google" in registered

    def test_all_three_are_provider_instances(self):
        for _, p in all_providers().items():
            assert isinstance(p, Provider)


# ---------------------------------------------------------------------------
# Provider config correctness
# ---------------------------------------------------------------------------


class TestProviderConfig:
    def test_openai_resolve_upstream_url(self):
        url = openai_provider.resolve_upstream_url("/v1/chat/completions", {})
        assert url == "https://api.openai.com/v1/chat/completions"

    def test_anthropic_resolve_upstream_url(self):
        url = anthropic_provider.resolve_upstream_url("/v1/messages", {})
        assert url == "https://api.anthropic.com/v1/messages"

    def test_google_resolve_upstream_url(self):
        url = google_provider.resolve_upstream_url(
            "/v1beta/models/gemini-1.5-pro:generateContent", {}
        )
        assert url == (
            "https://generativelanguage.googleapis.com"
            "/v1beta/models/gemini-1.5-pro:generateContent"
        )

    def test_streaming_format_openai(self):
        assert openai_provider.config.streaming_format == "sse-openai"

    def test_streaming_format_anthropic(self):
        assert anthropic_provider.config.streaming_format == "sse-anthropic"

    def test_streaming_format_google(self):
        assert google_provider.config.streaming_format == "sse-google"

    def test_headers_to_strip_includes_burnlens_tags(self):
        strip = openai_provider.headers_to_strip()
        assert "x-burnlens-tag-feature" in strip
        assert "x-burnlens-tag-team" in strip
        assert "x-burnlens-tag-customer" in strip

    def test_normalize_model_name_default_is_identity(self):
        for p in (openai_provider, anthropic_provider, google_provider):
            assert p.normalize_model_name("my-model") == "my-model"


# ---------------------------------------------------------------------------
# Backward-compat property aliases (used by shim + tests that access .name etc)
# ---------------------------------------------------------------------------


class TestBackwardCompatAliases:
    def test_name_property(self):
        assert openai_provider.name == "openai"
        assert anthropic_provider.name == "anthropic"
        assert google_provider.name == "google"

    def test_proxy_prefix_property(self):
        assert openai_provider.proxy_prefix == "/proxy/openai"
        assert anthropic_provider.proxy_prefix == "/proxy/anthropic"
        assert google_provider.proxy_prefix == "/proxy/google"

    def test_upstream_base_property(self):
        assert openai_provider.upstream_base == "https://api.openai.com"
        assert anthropic_provider.upstream_base == "https://api.anthropic.com"

    def test_env_var_openai(self):
        assert openai_provider.env_var == "OPENAI_BASE_URL"

    def test_env_var_anthropic(self):
        assert anthropic_provider.env_var == "ANTHROPIC_BASE_URL"

    def test_env_var_google_empty(self):
        assert google_provider.env_var == ""


# ---------------------------------------------------------------------------
# extract_model
# ---------------------------------------------------------------------------


class TestExtractModel:
    def test_openai_reads_from_body(self):
        assert openai_provider.extract_model({"model": "gpt-4o"}, "/v1/chat/completions") == "gpt-4o"

    def test_anthropic_reads_from_body(self):
        assert anthropic_provider.extract_model(
            {"model": "claude-sonnet-4-6"}, "/v1/messages"
        ) == "claude-sonnet-4-6"

    def test_google_reads_model_from_path(self):
        model = google_provider.extract_model(
            {}, "/v1beta/models/gemini-1.5-pro:generateContent"
        )
        assert model == "gemini-1.5-pro"

    def test_google_strips_method_suffix(self):
        model = google_provider.extract_model(
            {}, "/v1beta/models/gemini-2.0-flash:streamGenerateContent"
        )
        assert model == "gemini-2.0-flash"

    def test_google_falls_back_to_body(self):
        model = google_provider.extract_model({"model": "gemini-pro"}, "/v1beta/other")
        assert model == "gemini-pro"


# ---------------------------------------------------------------------------
# extract_usage (non-streaming)
# ---------------------------------------------------------------------------


class TestExtractUsage:
    def test_openai_extract_usage(self):
        resp = {"usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        usage = openai_provider.extract_usage(resp)
        assert usage.input_tokens == 10
        assert usage.output_tokens == 5

    def test_anthropic_extract_usage(self):
        resp = {"usage": {"input_tokens": 20, "output_tokens": 15}}
        usage = anthropic_provider.extract_usage(resp)
        assert usage.input_tokens == 20
        assert usage.output_tokens == 15

    def test_google_extract_usage(self):
        resp = {"usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 10}}
        usage = google_provider.extract_usage(resp)
        assert usage.input_tokens == 30
        assert usage.output_tokens == 10


# ---------------------------------------------------------------------------
# extract_usage_from_stream_chunk + accumulator
# ---------------------------------------------------------------------------


class TestStreamChunkAccumulation:
    def test_openai_accumulates_usage(self):
        import json
        chunk = f'data: {json.dumps({"usage": {"prompt_tokens": 8, "completion_tokens": 4}})}\n\n'
        acc: dict = {}
        openai_provider.extract_usage_from_stream_chunk(chunk.encode(), acc)
        assert acc["input_tokens"] == 8
        assert acc["output_tokens"] == 4

    def test_anthropic_accumulates_across_events(self):
        import json
        start_chunk = f'data: {json.dumps({"type": "message_start", "message": {"usage": {"input_tokens": 25}}})}\n\n'
        delta_chunk = f'data: {json.dumps({"type": "message_delta", "usage": {"output_tokens": 12}})}\n\n'
        acc: dict = {}
        anthropic_provider.extract_usage_from_stream_chunk(start_chunk.encode(), acc)
        anthropic_provider.extract_usage_from_stream_chunk(delta_chunk.encode(), acc)
        assert acc["input_tokens"] == 25
        assert acc["output_tokens"] == 12

    def test_google_last_chunk_wins(self):
        import json
        chunk1 = f'data: {json.dumps({"usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2}})}\n\n'
        chunk2 = f'data: {json.dumps({"usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 7}})}\n\n'
        acc: dict = {}
        google_provider.extract_usage_from_stream_chunk(chunk1.encode(), acc)
        google_provider.extract_usage_from_stream_chunk(chunk2.encode(), acc)
        assert acc["input_tokens"] == 5
        assert acc["output_tokens"] == 7
