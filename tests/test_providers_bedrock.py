"""AWS Bedrock provider — registration, region endpoint, model-in-path extraction,
eventstream usage scanning, and streaming detection."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from burnlens.providers import get, get_by_proxy_path
from burnlens.providers.bedrock import REGION_ENV, BedrockProvider
from burnlens.proxy.interceptor import handle_request
from burnlens.storage.queries import get_recent_requests

SONNET = "us.anthropic.claude-sonnet-4-6"


def test_registered():
    provider = get("bedrock")
    assert isinstance(provider, BedrockProvider)
    assert provider.config.proxy_path == "/proxy/bedrock"
    assert provider.config.auth_header == "Authorization"  # bearer token, not SigV4
    assert provider.config.pricing_key == "bedrock"
    assert provider.config.env_var == "AWS_ENDPOINT_URL_BEDROCK_RUNTIME"


def test_proxy_path_routing():
    provider = get_by_proxy_path(f"/proxy/bedrock/model/{SONNET}/converse")
    assert provider is not None and provider.config.name == "bedrock"


def test_upstream_from_region_env(monkeypatch):
    monkeypatch.setenv(REGION_ENV, "us-east-1")
    provider = get("bedrock")
    assert (
        provider.resolve_upstream_url(f"/model/{SONNET}/converse", {})
        == f"https://bedrock-runtime.us-east-1.amazonaws.com/model/{SONNET}/converse"
    )


def test_missing_region_raises(monkeypatch):
    monkeypatch.delenv(REGION_ENV, raising=False)
    with pytest.raises(RuntimeError, match=REGION_ENV):
        _ = get("bedrock").upstream_base


class TestExtractModel:
    def test_model_from_converse_path(self):
        assert get("bedrock").extract_model({}, f"/model/{SONNET}/converse") == SONNET

    def test_percent_encoded_id_decoded(self):
        # SDKs percent-encode the ':' in versioned/inference-profile IDs.
        encoded = "us.anthropic.claude-sonnet-4-5-20250929-v1%3A0"
        assert (
            get("bedrock").extract_model({}, f"/model/{encoded}/invoke")
            == "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        )

    def test_geo_prefix_and_version_suffix_preserved(self):
        """Prefix/suffix are part of the pricing key — normalizing them is how
        v1.7.0 produced a wrong *nonzero* cost. Guard against 'helpful' stripping."""
        for mid in (
            "us.anthropic.claude-sonnet-4-6",
            "eu.anthropic.claude-sonnet-4-6",
            "global.anthropic.claude-sonnet-4-6",
            "anthropic.claude-sonnet-4-5-20250929-v1:0",
        ):
            assert get("bedrock").extract_model({}, f"/model/{mid}/converse") == mid

    def test_query_string_stripped(self):
        assert get("bedrock").extract_model({}, f"/model/{SONNET}/converse?x=1") == SONNET

    def test_body_fallback_when_no_path_segment(self):
        assert get("bedrock").extract_model({"modelId": SONNET}, "/converse") == SONNET

    def test_no_model_returns_none(self):
        assert get("bedrock").extract_model({}, "/converse") is None


class TestIsStreaming:
    def test_converse_stream_is_streaming(self):
        assert get("bedrock").is_streaming({}, f"/model/{SONNET}/converse-stream") is True

    def test_invoke_with_response_stream_is_streaming(self):
        assert (
            get("bedrock").is_streaming({}, f"/model/{SONNET}/invoke-with-response-stream")
            is True
        )

    def test_plain_converse_is_not_streaming(self):
        assert get("bedrock").is_streaming({}, f"/model/{SONNET}/converse") is False

    def test_body_stream_flag_ignored(self):
        """Bedrock signals streaming by operation, not a body flag — a stray
        "stream": true must not flip a non-streaming Converse call."""
        assert get("bedrock").is_streaming({"stream": True}, f"/model/{SONNET}/converse") is False


class TestExtractUsage:
    def test_converse_camelcase(self):
        u = get("bedrock").extract_usage(
            {"usage": {"inputTokens": 100, "outputTokens": 25, "totalTokens": 125}}
        )
        assert u.input_tokens == 100 and u.output_tokens == 25

    def test_converse_cache_tokens(self):
        u = get("bedrock").extract_usage({
            "usage": {
                "inputTokens": 10, "outputTokens": 5,
                "cacheReadInputTokens": 900, "cacheWriteInputTokens": 40,
            }
        })
        assert u.cache_read_tokens == 900 and u.cache_write_tokens == 40

    def test_invoke_model_anthropic_snake_case(self):
        """InvokeModel passes the vendor body through — Anthropic uses snake_case."""
        u = get("bedrock").extract_usage(
            {"usage": {"input_tokens": 70, "output_tokens": 12}}
        )
        assert u.input_tokens == 70 and u.output_tokens == 12


class TestEventStreamUsage:
    """Bedrock streams vnd.amazon.eventstream (binary framing), not SSE."""

    def _frame(self, payload: bytes) -> bytes:
        # Crude stand-in for a real eventstream frame: binary junk around a JSON
        # payload. The extractor must find the JSON without decoding the framing.
        return b"\x00\x00\x01\x2f\x00\x00\x00\x43\x8b\x9d" + payload + b"\xcd\xef\x12\x34"

    def test_usage_scanned_from_binary_frame(self):
        provider = get("bedrock")
        chunk = self._frame(
            b'{"metadata":{"usage":{"inputTokens":47,"outputTokens":20,"totalTokens":67},'
            b'"metrics":{"latencyMs":100.0}}}'
        )
        acc: dict = {}
        provider.extract_usage_from_stream_chunk(chunk, acc)
        assert acc["input_tokens"] == 47 and acc["output_tokens"] == 20

    def test_undecodable_bytes_do_not_raise(self):
        """Frames contain non-UTF8 bytes; the scanner must not choke on them."""
        provider = get("bedrock")
        acc: dict = {}
        provider.extract_usage_from_stream_chunk(b"\xff\xfe\x00\x8b garbage", acc)
        assert acc == {}

    def test_truncated_object_ignored_not_partially_parsed(self):
        """An event split across chunk boundaries must yield nothing rather than
        a half-parsed (wrong) count."""
        provider = get("bedrock")
        acc: dict = {}
        provider.extract_usage_from_stream_chunk(b'{"usage":{"inputTokens":47,"outp', acc)
        assert acc == {}

    def test_split_event_extracted_once_reassembled(self):
        provider = get("bedrock")
        a = b'\x00\x8b{"metadata":{"usage":{"inputTokens":12,'
        b = b'"outputTokens":8}}}\xcd'
        acc: dict = {}
        provider.extract_usage_from_stream_chunk(a + b, acc)  # caller accumulates
        assert acc["input_tokens"] == 12 and acc["output_tokens"] == 8

    def test_brace_inside_string_does_not_unbalance(self):
        provider = get("bedrock")
        chunk = self._frame(
            b'{"text":"a } brace","usage":{"inputTokens":5,"outputTokens":3}}'
        )
        acc: dict = {}
        provider.extract_usage_from_stream_chunk(chunk, acc)
        assert acc["input_tokens"] == 5 and acc["output_tokens"] == 3

    def test_should_buffer_only_usage_chunks(self):
        provider = get("bedrock")
        assert provider.should_buffer_chunk(b'{"usage":{"inputTokens":1}}') is True
        assert provider.should_buffer_chunk(b'{"contentBlockDelta":{"text":"hi"}}') is False


class TestRewritePathForRouting:
    def test_model_segment_rewritten(self):
        assert (
            get("bedrock").rewrite_path_for_routing(
                f"/model/{SONNET}/converse", "us.anthropic.claude-haiku-4-5"
            )
            == "/model/us.anthropic.claude-haiku-4-5/converse"
        )

    def test_operation_suffix_preserved(self):
        assert (
            get("bedrock").rewrite_path_for_routing(
                f"/model/{SONNET}/converse-stream", "us.anthropic.claude-haiku-4-5"
            )
            == "/model/us.anthropic.claude-haiku-4-5/converse-stream"
        )

    def test_non_model_path_unchanged(self):
        assert get("bedrock").rewrite_path_for_routing("/foo/bar", "x") == "/foo/bar"


# ---------------------------------------------------------------------------
# Interceptor path — the v1.8.2 lesson: assert through handle_request, not just
# the provider object.
# ---------------------------------------------------------------------------


class _CannedTransport(httpx.AsyncBaseTransport):
    def __init__(self, payload: dict):
        self._payload = payload
        self.captured: httpx.Request | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.captured = request
        return httpx.Response(
            200,
            content=json.dumps(self._payload).encode(),
            headers={"content-type": "application/json"},
        )


class TestBedrockThroughProxy:
    async def test_model_and_tokens_logged(self, initialized_db, monkeypatch):
        monkeypatch.setenv(REGION_ENV, "us-east-1")
        transport = _CannedTransport({
            "output": {"message": {"role": "assistant", "content": [{"text": "hi"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 1000, "outputTokens": 500, "totalTokens": 1500},
        })
        await handle_request(
            client=httpx.AsyncClient(transport=transport),
            provider=get("bedrock"),
            path=f"/proxy/bedrock/model/{SONNET}/converse",
            method="POST",
            headers={"content-type": "application/json",
                     "authorization": "Bearer test-bedrock-key"},
            body_bytes=json.dumps({"messages": []}).encode(),
            query_string="",
            db_path=initialized_db,
            alert_engine=None,
        )
        for _ in range(10):
            await asyncio.sleep(0.05)

        rows = await get_recent_requests(initialized_db, limit=5)
        assert len(rows) == 1
        assert rows[0]["provider"] == "bedrock"
        assert rows[0]["model"] == SONNET  # full ID incl. geo prefix
        assert rows[0]["input_tokens"] == 1000
        assert rows[0]["output_tokens"] == 500

    async def test_bearer_auth_forwarded_untouched(self, initialized_db, monkeypatch):
        """Bedrock API keys are opaque bearer tokens — the proxy must not alter them."""
        monkeypatch.setenv(REGION_ENV, "us-east-1")
        transport = _CannedTransport({"usage": {"inputTokens": 1, "outputTokens": 1}})
        await handle_request(
            client=httpx.AsyncClient(transport=transport),
            provider=get("bedrock"),
            path=f"/proxy/bedrock/model/{SONNET}/converse",
            method="POST",
            headers={"content-type": "application/json",
                     "authorization": "Bearer secret-token-123"},
            body_bytes=b"{}",
            query_string="",
            db_path=initialized_db,
            alert_engine=None,
        )
        assert transport.captured is not None
        assert transport.captured.headers["authorization"] == "Bearer secret-token-123"
        assert str(transport.captured.url.path) == f"/model/{SONNET}/converse"


def test_env_export_points_sdk_at_proxy():
    """`burnlens start` must repoint boto3's endpoint var, and it must not collide
    with the proxy's own BURNLENS_BEDROCK_REGION."""
    from burnlens.proxy.providers import build_env_exports

    exports = build_env_exports("127.0.0.1", 8000)
    assert exports["AWS_ENDPOINT_URL_BEDROCK_RUNTIME"] == "http://127.0.0.1:8000/proxy/bedrock"
    assert REGION_ENV not in exports
