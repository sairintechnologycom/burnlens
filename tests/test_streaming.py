"""Tests for SSE streaming usage extraction (burnlens/proxy/streaming.py)."""
from __future__ import annotations

import json

from burnlens.cost.calculator import TokenUsage
from burnlens.proxy.streaming import (
    extract_usage_from_stream,
    should_buffer_chunk,
)


# ---------------------------------------------------------------------------
# should_buffer_chunk
# ---------------------------------------------------------------------------

class TestShouldBufferChunk:
    def test_openai_usage_chunk(self):
        chunk = 'data: {"id":"chatcmpl-1","usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n'
        assert should_buffer_chunk(chunk) is True

    def test_google_usage_chunk(self):
        chunk = '{"usageMetadata":{"promptTokenCount":10}}\n'
        assert should_buffer_chunk(chunk) is True

    def test_anthropic_message_start(self):
        chunk = 'data: {"type":"message_start","message":{"usage":{"input_tokens":20}}}\n\n'
        assert should_buffer_chunk(chunk) is True

    def test_anthropic_message_delta(self):
        chunk = 'data: {"type":"message_delta","usage":{"output_tokens":30}}\n\n'
        assert should_buffer_chunk(chunk) is True

    def test_plain_content_chunk_not_buffered(self):
        chunk = 'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}\n\n'
        assert should_buffer_chunk(chunk) is False

    def test_done_chunk_not_buffered(self):
        assert should_buffer_chunk("data: [DONE]\n\n") is False


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
        assert usage.output_tokens == 8
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
