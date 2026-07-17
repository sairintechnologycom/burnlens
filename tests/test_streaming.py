"""Tests for SSE streaming usage extraction (burnlens/proxy/streaming.py)."""
from __future__ import annotations

import json

from burnlens.cost.calculator import TokenUsage
from burnlens.providers import get
from burnlens.proxy.streaming import (
    extract_usage_from_stream,
    split_sse_events,
)


# ---------------------------------------------------------------------------
# Usage-event gating — now owned by provider.should_buffer_chunk() and reached
# through split_sse_events(buffer, provider). The module-level
# should_buffer_chunk() duplicate was deleted: it was never called by the proxy,
# so it tested nothing the pipeline actually ran.
# ---------------------------------------------------------------------------

class TestUsageEventGating:
    def _kept(self, chunk: str, provider_name: str) -> bool:
        return bool(split_sse_events(chunk, get(provider_name)))

    def test_openai_usage_chunk(self):
        chunk = 'data: {"id":"chatcmpl-1","usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n'
        assert self._kept(chunk, "openai") is True

    def test_google_usage_chunk(self):
        chunk = '{"usageMetadata":{"promptTokenCount":10}}\n'
        assert self._kept(chunk, "google") is True

    def test_anthropic_message_start(self):
        chunk = 'data: {"type":"message_start","message":{"usage":{"input_tokens":20}}}\n\n'
        assert self._kept(chunk, "anthropic") is True

    def test_anthropic_message_delta(self):
        chunk = 'data: {"type":"message_delta","usage":{"output_tokens":30}}\n\n'
        assert self._kept(chunk, "anthropic") is True

    def test_plain_content_chunk_not_buffered(self):
        chunk = 'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}\n\n'
        assert self._kept(chunk, "anthropic") is False

    def test_done_chunk_not_buffered(self):
        assert self._kept("data: [DONE]\n\n", "openai") is False

    def test_legacy_fallback_without_provider_still_gates(self):
        """No provider in hand → the USAGE_EVENT_INDICATORS union, which
        over-matches rather than dropping usage."""
        chunk = 'data: {"usage":{"prompt_tokens":10}}\n\n'
        assert bool(split_sse_events(chunk)) is True
        assert bool(split_sse_events('data: {"delta":{"text":"hi"}}\n\n')) is False


# ---------------------------------------------------------------------------
# OpenAI streaming extraction
# ---------------------------------------------------------------------------

class TestOpenAIStreamExtraction:
    def _sse(self, data: dict) -> str:
        return f"data: {json.dumps(data)}\n\n"

    def test_usage_in_final_chunk(self):
        chunks = [
            self._sse({"choices": [{"delta": {"content": "Hello"}}]}),
            self._sse({
                "choices": [],
                "usage": {
                    "prompt_tokens": 15,
                    "completion_tokens": 8,
                    "completion_tokens_details": {"reasoning_tokens": 2},
                    "prompt_tokens_details": {"cached_tokens": 5},
                },
            }),
            "data: [DONE]\n\n",
        ]
        usage = extract_usage_from_stream("openai", chunks)
        assert usage.input_tokens == 15
        # completion_tokens (8) includes the 2 reasoning tokens; output is the
        # disjoint remainder so reasoning isn't billed twice.
        assert usage.output_tokens == 6
        assert usage.reasoning_tokens == 2
        assert usage.cache_read_tokens == 5

    def test_no_usage_returns_zeros(self):
        chunks = [
            self._sse({"choices": [{"delta": {"content": "Hi"}}]}),
            "data: [DONE]\n\n",
        ]
        usage = extract_usage_from_stream("openai", chunks)
        assert usage == TokenUsage()

    def test_done_sentinel_skipped(self):
        chunks = ["data: [DONE]\n\n"]
        usage = extract_usage_from_stream("openai", chunks)
        assert usage == TokenUsage()

    def test_malformed_json_skipped(self):
        chunks = ["data: {bad json}\n\n", self._sse({"usage": {"prompt_tokens": 5, "completion_tokens": 3}})]
        usage = extract_usage_from_stream("openai", chunks)
        assert usage.input_tokens == 5
        assert usage.output_tokens == 3


# ---------------------------------------------------------------------------
# Anthropic streaming extraction
# ---------------------------------------------------------------------------

class TestAnthropicStreamExtraction:
    def _sse(self, data: dict) -> str:
        return f"data: {json.dumps(data)}\n\n"

    def test_input_tokens_from_message_start(self):
        chunk = self._sse({
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "usage": {"input_tokens": 25, "output_tokens": 1},
            },
        })
        usage = extract_usage_from_stream("anthropic", [chunk])
        assert usage.input_tokens == 25

    def test_output_tokens_from_message_delta(self):
        chunks = [
            self._sse({
                "type": "message_start",
                "message": {"usage": {"input_tokens": 25, "output_tokens": 1}},
            }),
            self._sse({
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 42},
            }),
        ]
        usage = extract_usage_from_stream("anthropic", chunks)
        assert usage.input_tokens == 25
        assert usage.output_tokens == 42

    def test_cache_tokens_from_message_start(self):
        chunk = self._sse({
            "type": "message_start",
            "message": {
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 0,
                    "cache_read_input_tokens": 80,
                    "cache_creation_input_tokens": 20,
                },
            },
        })
        usage = extract_usage_from_stream("anthropic", [chunk])
        assert usage.cache_read_tokens == 80
        assert usage.cache_write_tokens == 20

    def test_content_delta_chunks_ignored(self):
        """Content chunks that don't match message_start/delta are skipped."""
        chunks = [
            self._sse({"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}),
            self._sse({"type": "content_block_delta", "index": 0, "delta": {"text": "hello"}}),
            self._sse({"type": "content_block_stop", "index": 0}),
        ]
        usage = extract_usage_from_stream("anthropic", chunks)
        assert usage == TokenUsage()

    def test_no_chunks_returns_zeros(self):
        assert extract_usage_from_stream("anthropic", []) == TokenUsage()


# ---------------------------------------------------------------------------
# Google streaming extraction
# ---------------------------------------------------------------------------

class TestGoogleStreamExtraction:
    def test_usage_from_json_line(self):
        chunk = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "hi"}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
        }) + "\n"
        usage = extract_usage_from_stream("google", [chunk])
        assert usage.input_tokens == 10
        assert usage.output_tokens == 5

    def test_last_chunk_wins(self):
        """Google sends cumulative totals — last chunk should be used."""
        chunk1 = json.dumps({"usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2}}) + "\n"
        chunk2 = json.dumps({"usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 8}}) + "\n"
        usage = extract_usage_from_stream("google", [chunk1, chunk2])
        assert usage.input_tokens == 10
        assert usage.output_tokens == 8

    def test_no_usage_metadata_returns_zeros(self):
        chunk = json.dumps({"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}) + "\n"
        usage = extract_usage_from_stream("google", [chunk])
        assert usage == TokenUsage()


# ---------------------------------------------------------------------------
# Unknown provider
# ---------------------------------------------------------------------------

class TestUnknownProvider:
    def test_unknown_provider_returns_zeros(self):
        usage = extract_usage_from_stream("unknown_provider", ['data: {"usage": {"tokens": 5}}\n\n'])
        assert usage == TokenUsage()


# ---------------------------------------------------------------------------
# Regression: the usage gate must consult the PROVIDER, not a hardcoded list.
# Until v1.8.3 split_sse_events matched a fixed USAGE_EVENT_INDICATORS tuple, so
# any provider whose usage key wasn't in that union had its usage silently
# dropped and its requests cost $0. Provider.should_buffer_chunk existed and was
# never called.
# ---------------------------------------------------------------------------


class TestGateConsultsProvider:
    def test_provider_specific_key_not_in_legacy_union_is_kept(self):
        from burnlens.providers.base import Provider, ProviderConfig
        from burnlens.cost.calculator import TokenUsage as _TU
        from burnlens.proxy.streaming import USAGE_EVENT_INDICATORS

        class _OddProvider(Provider):
            config = ProviderConfig(
                name="odd", proxy_path="/proxy/odd", upstream_url="https://x",
                auth_header="Authorization", streaming_format="sse-openai",
                pricing_key="odd",
            )
            def resolve_upstream_url(self, request_path, headers): return "https://x"
            def extract_model(self, request_body, request_path): return "m"
            def extract_usage(self, response_body): return _TU()
            def extract_usage_from_stream_chunk(self, chunk, accumulator): return None
            def should_buffer_chunk(self, chunk): return b"tokenTally" in chunk

        event = 'data: {"tokenTally":{"in":10,"out":5}}\n\n'
        # Precondition: the legacy hardcoded union cannot see this event.
        assert not any(i in event for i in USAGE_EVENT_INDICATORS)
        assert split_sse_events(event) == []          # legacy path drops it -> $0
        assert split_sse_events(event, _OddProvider())  # provider path keeps it

    def test_provider_gate_is_actually_invoked(self):
        """Guard the wiring itself: if split_sse_events stops consulting the
        provider, this fails even when the fallback would coincidentally match."""
        calls: list[bytes] = []
        provider = get("openai")

        class _Spy:
            config = provider.config
            def should_buffer_chunk(self, chunk):
                calls.append(chunk)
                return provider.should_buffer_chunk(chunk)

        split_sse_events('data: {"usage":{"prompt_tokens":1}}\n\n', _Spy())
        assert calls, "split_sse_events did not consult provider.should_buffer_chunk"
