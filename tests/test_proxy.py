"""Tests for the FastAPI proxy app."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from burnlens.config import BurnLensConfig
from burnlens.proxy.interceptor import handle_request
from burnlens.proxy.providers import (
    DEFAULT_PROVIDERS,
    build_env_exports,
    get_provider_for_path,
    strip_proxy_prefix,
)
from burnlens.storage.queries import get_recent_requests, get_usage_by_model


# ---------------------------------------------------------------------------
# Provider routing helpers
# ---------------------------------------------------------------------------


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
        openai = next(p for p in DEFAULT_PROVIDERS if p.name == "openai")
        stripped = strip_proxy_prefix("/proxy/openai/v1/chat/completions", openai)
        assert stripped == "/v1/chat/completions"

    def test_strip_prefix_anthropic(self):
        anthropic = next(p for p in DEFAULT_PROVIDERS if p.name == "anthropic")
        stripped = strip_proxy_prefix("/proxy/anthropic/v1/messages", anthropic)
        assert stripped == "/v1/messages"

    def test_env_exports(self):
        exports = build_env_exports("127.0.0.1", 8420)
        assert exports["OPENAI_BASE_URL"] == "http://127.0.0.1:8420/proxy/openai"
        assert exports["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8420/proxy/anthropic"
        # Google SDK doesn't support a base URL env var — handled by burnlens.patch
        assert "GOOGLE_AI_BASE_URL" not in exports

    def test_env_exports_custom_port(self):
        exports = build_env_exports("0.0.0.0", 9999)
        assert "9999" in exports["OPENAI_BASE_URL"]


# ---------------------------------------------------------------------------
# Tag extraction
# ---------------------------------------------------------------------------


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

    def test_case_insensitive_prefix_check(self):
        from burnlens.proxy.interceptor import _extract_tags

        # The prefix match uses key.lower(), so mixed-case headers are detected.
        # The suffix after the prefix retains its original casing.
        headers = {"X-BurnLens-Tag-Service": "chatbot"}
        tags = _extract_tags(headers)
        assert "chatbot" in tags.values()

    def test_tag_value_preserved(self):
        from burnlens.proxy.interceptor import _extract_tags

        headers = {"x-burnlens-tag-feature": "search-v2"}
        assert _extract_tags(headers) == {"feature": "search-v2"}


# ---------------------------------------------------------------------------
# Header cleaning
# ---------------------------------------------------------------------------


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

    def test_hop_by_hop_headers_stripped(self):
        from burnlens.proxy.interceptor import _clean_request_headers

        headers = {
            "connection": "keep-alive",
            "transfer-encoding": "chunked",
            "te": "trailers",
            "authorization": "Bearer sk-xxx",
        }
        cleaned = _clean_request_headers(headers)
        assert "connection" not in cleaned
        assert "transfer-encoding" not in cleaned
        assert "te" not in cleaned
        assert "authorization" in cleaned

    def test_non_burnlens_x_headers_kept(self):
        from burnlens.proxy.interceptor import _clean_request_headers

        headers = {"x-request-id": "abc123", "x-api-key": "sk-xxx"}
        cleaned = _clean_request_headers(headers)
        assert "x-request-id" in cleaned
        assert "x-api-key" in cleaned


# ---------------------------------------------------------------------------
# Streaming detection
# ---------------------------------------------------------------------------


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

    def test_invalid_json_not_streaming(self):
        from burnlens.proxy.interceptor import _is_streaming

        assert _is_streaming(b"not-json") is False


# ---------------------------------------------------------------------------
# System prompt hashing
# ---------------------------------------------------------------------------


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

    def test_different_prompts_different_hashes(self):
        from burnlens.proxy.interceptor import _hash_system_prompt

        body1 = json.dumps({"messages": [{"role": "system", "content": "Prompt A"}]}).encode()
        body2 = json.dumps({"messages": [{"role": "system", "content": "Prompt B"}]}).encode()
        assert _hash_system_prompt(body1) != _hash_system_prompt(body2)

    def test_no_system_message_returns_none(self):
        from burnlens.proxy.interceptor import _hash_system_prompt

        body = json.dumps({"messages": [{"role": "user", "content": "Hello"}]}).encode()
        assert _hash_system_prompt(body) is None

    def test_anthropic_top_level_system(self):
        from burnlens.proxy.interceptor import _hash_system_prompt

        body = json.dumps({"system": "You are Claude.", "messages": []}).encode()
        h = _hash_system_prompt(body)
        assert h is not None
        assert len(h) == 64

    def test_invalid_json_returns_none(self):
        from burnlens.proxy.interceptor import _hash_system_prompt

        assert _hash_system_prompt(b"not-json") is None


# ---------------------------------------------------------------------------
# handle_request integration (non-streaming)
# ---------------------------------------------------------------------------


class MockAsyncTransport(httpx.AsyncBaseTransport):
    """Captures the forwarded request and returns a canned JSON response."""

    def __init__(self, response_json: dict, status_code: int = 200):
        self.captured_request: httpx.Request | None = None
        self._response_json = response_json
        self._status_code = status_code

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.captured_request = request
        content = json.dumps(self._response_json).encode()
        return httpx.Response(
            status_code=self._status_code,
            content=content,
            headers={"content-type": "application/json"},
        )


def _openai_response(input_tokens: int = 100, output_tokens: int = 50) -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "gpt-4o",
        "choices": [{"message": {"role": "assistant", "content": "Hello"}}],
        "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens},
    }


async def _flush_tasks() -> None:
    """Yield control until background tasks finish."""
    for _ in range(10):
        await asyncio.sleep(0.05)


class TestHandleRequest:
    async def test_non_streaming_forwarded_correctly(self, initialized_db: str):
        transport = MockAsyncTransport(_openai_response())
        client = httpx.AsyncClient(transport=transport)
        provider = get_provider_for_path("/proxy/openai/v1/chat/completions")

        body = json.dumps({"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]}).encode()

        status, resp_headers, body_out, stream = await handle_request(
            client=client,
            provider=provider,
            path="/proxy/openai/v1/chat/completions",
            method="POST",
            headers={"content-type": "application/json"},
            body_bytes=body,
            query_string="",
            db_path=initialized_db,
            alert_engine=None,
        )
        await _flush_tasks()

        assert status == 200
        assert stream is None
        assert body_out is not None
        assert json.loads(body_out)["model"] == "gpt-4o"

        # Verify upstream path had proxy prefix stripped
        assert transport.captured_request is not None
        assert str(transport.captured_request.url.path) == "/v1/chat/completions"

    async def test_burnlens_tag_headers_stripped_before_forwarding(self, initialized_db: str):
        transport = MockAsyncTransport(_openai_response())
        client = httpx.AsyncClient(transport=transport)
        provider = get_provider_for_path("/proxy/openai/v1/chat/completions")

        body = json.dumps({"model": "gpt-4o", "messages": []}).encode()

        await handle_request(
            client=client,
            provider=provider,
            path="/proxy/openai/v1/chat/completions",
            method="POST",
            headers={
                "content-type": "application/json",
                "x-burnlens-tag-team": "ml",
                "x-burnlens-tag-env": "prod",
                "authorization": "Bearer sk-test",
            },
            body_bytes=body,
            query_string="",
            db_path=initialized_db,
            alert_engine=None,
        )

        forwarded_headers = dict(transport.captured_request.headers)
        assert "x-burnlens-tag-team" not in forwarded_headers
        assert "x-burnlens-tag-env" not in forwarded_headers
        # Real headers should pass through
        assert "authorization" in forwarded_headers

    async def test_response_body_returned_unmodified(self, initialized_db: str):
        expected_body = _openai_response(input_tokens=300, output_tokens=150)
        transport = MockAsyncTransport(expected_body)
        client = httpx.AsyncClient(transport=transport)
        provider = get_provider_for_path("/proxy/openai/v1/chat/completions")

        body = json.dumps({"model": "gpt-4o", "messages": []}).encode()
        _, _, resp_body, _ = await handle_request(
            client=client,
            provider=provider,
            path="/proxy/openai/v1/chat/completions",
            method="POST",
            headers={"content-type": "application/json"},
            body_bytes=body,
            query_string="",
            db_path=initialized_db,
            alert_engine=None,
        )
        await _flush_tasks()

        assert json.loads(resp_body) == expected_body

    async def test_request_logged_to_sqlite(self, initialized_db: str):
        transport = MockAsyncTransport(_openai_response(input_tokens=100, output_tokens=50))
        client = httpx.AsyncClient(transport=transport)
        provider = get_provider_for_path("/proxy/openai/v1/chat/completions")

        body = json.dumps({"model": "gpt-4o", "messages": []}).encode()
        await handle_request(
            client=client,
            provider=provider,
            path="/proxy/openai/v1/chat/completions",
            method="POST",
            headers={"content-type": "application/json"},
            body_bytes=body,
            query_string="",
            db_path=initialized_db,
            alert_engine=None,
        )

        await _flush_tasks()

        rows = await get_recent_requests(initialized_db, limit=5)
        assert len(rows) == 1
        row = rows[0]
        assert row["provider"] == "openai"
        assert row["model"] == "gpt-4o"
        assert row["input_tokens"] == 100
        assert row["output_tokens"] == 50
        assert row["cost_usd"] > 0  # gpt-4o has a price

    async def test_tags_logged_to_sqlite(self, initialized_db: str):
        transport = MockAsyncTransport(_openai_response())
        client = httpx.AsyncClient(transport=transport)
        provider = get_provider_for_path("/proxy/openai/v1/chat/completions")

        body = json.dumps({"model": "gpt-4o", "messages": []}).encode()
        await handle_request(
            client=client,
            provider=provider,
            path="/proxy/openai/v1/chat/completions",
            method="POST",
            headers={
                "content-type": "application/json",
                "x-burnlens-tag-team": "infra",
                "x-burnlens-tag-feature": "summary",
            },
            body_bytes=body,
            query_string="",
            db_path=initialized_db,
            alert_engine=None,
        )
        await _flush_tasks()

        rows = await get_recent_requests(initialized_db)
        assert rows[0]["tags"] == {"team": "infra", "feature": "summary"}

    async def test_query_string_appended_to_upstream_path(self, initialized_db: str):
        transport = MockAsyncTransport(_openai_response())
        client = httpx.AsyncClient(transport=transport)
        provider = get_provider_for_path("/proxy/openai/v1/chat/completions")

        body = json.dumps({"model": "gpt-4o", "messages": []}).encode()
        await handle_request(
            client=client,
            provider=provider,
            path="/proxy/openai/v1/chat/completions",
            method="POST",
            headers={"content-type": "application/json"},
            body_bytes=body,
            query_string="timeout=30",
            db_path=initialized_db,
            alert_engine=None,
        )

        assert "timeout=30" in str(transport.captured_request.url)

    async def test_burnlens_tag_stripped_forwarding_no_op_if_empty(self, initialized_db: str):
        """Forwarding works correctly even when there are no BurnLens headers."""
        transport = MockAsyncTransport(_openai_response())
        client = httpx.AsyncClient(transport=transport)
        provider = get_provider_for_path("/proxy/openai/v1/chat/completions")

        body = json.dumps({"model": "gpt-4o", "messages": []}).encode()
        status, _, _, _ = await handle_request(
            client=client,
            provider=provider,
            path="/proxy/openai/v1/chat/completions",
            method="POST",
            headers={"content-type": "application/json"},
            body_bytes=body,
            query_string="",
            db_path=initialized_db,
            alert_engine=None,
        )
        await _flush_tasks()
        assert status == 200

    async def test_non_200_status_returned(self, initialized_db: str):
        transport = MockAsyncTransport({"error": "unauthorized"}, status_code=401)
        client = httpx.AsyncClient(transport=transport)
        provider = get_provider_for_path("/proxy/openai/v1/chat/completions")

        body = json.dumps({"model": "gpt-4o", "messages": []}).encode()
        status, _, _, _ = await handle_request(
            client=client,
            provider=provider,
            path="/proxy/openai/v1/chat/completions",
            method="POST",
            headers={"content-type": "application/json"},
            body_bytes=body,
            query_string="",
            db_path=initialized_db,
            alert_engine=None,
        )
        await _flush_tasks()
        assert status == 401


# ---------------------------------------------------------------------------
# Interceptor helper unit tests (increases interceptor.py coverage)
# ---------------------------------------------------------------------------


class TestInterceptorHelpers:
    def test_extract_model_from_openai_body(self):
        from burnlens.proxy.interceptor import _extract_model

        body = json.dumps({"model": "gpt-4o-mini", "messages": []}).encode()
        assert _extract_model(body, "openai") == "gpt-4o-mini"

    def test_extract_model_missing_returns_unknown(self):
        from burnlens.proxy.interceptor import _extract_model

        body = json.dumps({"messages": []}).encode()
        assert _extract_model(body, "openai") == "unknown"

    def test_extract_model_invalid_json_returns_unknown(self):
        from burnlens.proxy.interceptor import _extract_model

        assert _extract_model(b"not-json", "openai") == "unknown"

    def test_extract_model_from_google_path(self):
        from burnlens.proxy.interceptor import _extract_model_from_path

        model = _extract_model_from_path(
            "/v1beta/models/gemini-1.5-pro:generateContent", "google"
        )
        assert model == "gemini-1.5-pro"

    def test_extract_model_from_google_path_strips_method_suffix(self):
        from burnlens.proxy.interceptor import _extract_model_from_path

        model = _extract_model_from_path(
            "/v1beta/models/gemini-2.0-flash:streamGenerateContent", "google"
        )
        assert model == "gemini-2.0-flash"

    def test_extract_model_from_non_google_path_returns_none(self):
        from burnlens.proxy.interceptor import _extract_model_from_path

        assert _extract_model_from_path("/v1/chat/completions", "openai") is None

    def test_extract_model_from_google_path_no_models_segment_returns_none(self):
        from burnlens.proxy.interceptor import _extract_model_from_path

        assert _extract_model_from_path("/v1beta/generateContent", "google") is None

    def test_hash_system_prompt_list_content(self):
        from burnlens.proxy.interceptor import _hash_system_prompt

        body = json.dumps({
            "messages": [
                {"role": "system", "content": [
                    {"type": "text", "text": "You are "},
                    {"type": "text", "text": "helpful."},
                ]}
            ]
        }).encode()
        h = _hash_system_prompt(body)
        assert h is not None
        assert len(h) == 64

    def test_extract_usage_for_provider_anthropic(self):
        from burnlens.proxy.interceptor import _extract_usage_for_provider

        resp = {"usage": {"input_tokens": 200, "output_tokens": 80}}
        u = _extract_usage_for_provider("anthropic", resp)
        assert u.input_tokens == 200
        assert u.output_tokens == 80

    def test_extract_usage_for_provider_google(self):
        from burnlens.proxy.interceptor import _extract_usage_for_provider

        resp = {"usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 20}}
        u = _extract_usage_for_provider("google", resp)
        assert u.input_tokens == 50
        assert u.output_tokens == 20

    def test_extract_usage_for_provider_unknown_returns_zeros(self):
        from burnlens.proxy.interceptor import _extract_usage_for_provider

        u = _extract_usage_for_provider("unknown_provider", {"usage": {"tokens": 10}})
        assert u.input_tokens == 0
        assert u.output_tokens == 0


# ---------------------------------------------------------------------------
# Config loading (covers config.py)
# ---------------------------------------------------------------------------


class TestConfigLoading:
    def test_load_config_defaults(self):
        from burnlens.config import load_config

        cfg = load_config(None)
        assert cfg.port == 8420
        assert cfg.host == "127.0.0.1"
        assert cfg.alerts.terminal is True
        assert cfg.alerts.budget_limit_usd is None

    def test_load_config_from_yaml(self, tmp_path):
        import yaml
        from burnlens.config import load_config

        config_file = tmp_path / "burnlens.yaml"
        config_file.write_text(yaml.dump({
            "port": 9000,
            "host": "0.0.0.0",
            "alerts": {
                "terminal": False,
                "budget_limit_usd": 50.0,
                "budget": {
                    "daily_usd": 5.0,
                    "weekly_usd": 30.0,
                    "monthly_usd": 100.0,
                },
            },
        }))

        cfg = load_config(str(config_file))
        assert cfg.port == 9000
        assert cfg.host == "0.0.0.0"
        assert cfg.alerts.terminal is False
        assert abs(cfg.alerts.budget_limit_usd - 50.0) < 1e-9
        assert abs(cfg.alerts.budget.daily_usd - 5.0) < 1e-9
        assert abs(cfg.alerts.budget.weekly_usd - 30.0) < 1e-9
        assert abs(cfg.alerts.budget.monthly_usd - 100.0) < 1e-9

    def test_load_config_nonexistent_path_returns_defaults(self, tmp_path):
        from burnlens.config import load_config

        cfg = load_config(str(tmp_path / "nonexistent.yaml"))
        assert cfg.port == 8420

    def test_load_config_empty_yaml_returns_defaults(self, tmp_path):
        from burnlens.config import load_config

        config_file = tmp_path / "burnlens.yaml"
        config_file.write_text("")
        cfg = load_config(str(config_file))
        assert cfg.port == 8420

    def test_load_config_partial_keys(self, tmp_path):
        import yaml
        from burnlens.config import load_config

        config_file = tmp_path / "burnlens.yaml"
        config_file.write_text(yaml.dump({"port": 9999}))
        cfg = load_config(str(config_file))
        assert cfg.port == 9999
        assert cfg.host == "127.0.0.1"  # default preserved
