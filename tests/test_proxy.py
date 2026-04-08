"""Tests for the FastAPI proxy app."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from burnlens.config import BurnLensConfig
from burnlens.proxy.providers import (
    build_env_exports,
    get_provider_for_path,
    strip_proxy_prefix,
)


class TestProviderRouting:
    def test_openai_path_matched(self):
        p = get_provider_for_path("/proxy/openai/v1/chat/completions")
        assert p is not None
        assert p.name == "openai"

    def test_anthropic_path_matched(self):
        p = get_provider_for_path("/proxy/anthropic/v1/messages")
        assert p is not None
        assert p.name == "anthropic"

    def test_google_path_matched(self):
        p = get_provider_for_path("/proxy/google/v1beta/models/gemini:generateContent")
        assert p is not None
        assert p.name == "google"

    def test_unknown_path_returns_none(self):
        assert get_provider_for_path("/proxy/unknown/v1/foo") is None

    def test_strip_prefix_openai(self):
        from burnlens.proxy.providers import DEFAULT_PROVIDERS

        openai = next(p for p in DEFAULT_PROVIDERS if p.name == "openai")
        stripped = strip_proxy_prefix("/proxy/openai/v1/chat/completions", openai)
        assert stripped == "/v1/chat/completions"

    def test_env_exports(self):
        exports = build_env_exports("127.0.0.1", 8420)
        assert exports["OPENAI_BASE_URL"] == "http://127.0.0.1:8420/proxy/openai"
        assert exports["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8420/proxy/anthropic"
        assert exports["GOOGLE_AI_BASE_URL"] == "http://127.0.0.1:8420/proxy/google"


class TestTagExtraction:
    def test_extract_tags_from_interceptor(self):
        from burnlens.proxy.interceptor import _extract_tags

        headers = {
            "x-burnlens-tag-team": "ml",
            "x-burnlens-tag-env": "prod",
            "authorization": "Bearer sk-xxx",
            "content-type": "application/json",
        }
        tags = _extract_tags(headers)
        assert tags == {"team": "ml", "env": "prod"}

    def test_no_tags_returns_empty(self):
        from burnlens.proxy.interceptor import _extract_tags

        tags = _extract_tags({"authorization": "Bearer sk-xxx"})
        assert tags == {}


class TestHeaderCleaning:
    def test_burnlens_headers_stripped(self):
        from burnlens.proxy.interceptor import _clean_request_headers

        headers = {
            "x-burnlens-tag-team": "ml",
            "authorization": "Bearer sk-xxx",
            "content-type": "application/json",
            "host": "localhost",
        }
        cleaned = _clean_request_headers(headers)
        assert "x-burnlens-tag-team" not in cleaned
        assert "host" not in cleaned
        assert "authorization" in cleaned
        assert "content-type" in cleaned


class TestStreamingDetection:
    def test_streaming_true(self):
        from burnlens.proxy.interceptor import _is_streaming

        body = json.dumps({"model": "gpt-4o", "stream": True}).encode()
        assert _is_streaming(body) is True

    def test_streaming_false(self):
        from burnlens.proxy.interceptor import _is_streaming

        body = json.dumps({"model": "gpt-4o", "stream": False}).encode()
        assert _is_streaming(body) is False

    def test_streaming_absent(self):
        from burnlens.proxy.interceptor import _is_streaming

        body = json.dumps({"model": "gpt-4o"}).encode()
        assert _is_streaming(body) is False


class TestSystemPromptHashing:
    def test_hashes_system_message(self):
        from burnlens.proxy.interceptor import _hash_system_prompt

        body = json.dumps(
            {"messages": [{"role": "system", "content": "You are a helpful assistant."}]}
        ).encode()
        h = _hash_system_prompt(body)
        assert h is not None
        assert len(h) == 64  # SHA-256 hex

    def test_same_prompt_same_hash(self):
        from burnlens.proxy.interceptor import _hash_system_prompt

        body = json.dumps(
            {"messages": [{"role": "system", "content": "You are helpful."}]}
        ).encode()
        assert _hash_system_prompt(body) == _hash_system_prompt(body)

    def test_no_system_message_returns_none(self):
        from burnlens.proxy.interceptor import _hash_system_prompt

        body = json.dumps({"messages": [{"role": "user", "content": "Hello"}]}).encode()
        assert _hash_system_prompt(body) is None
