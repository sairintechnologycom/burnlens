"""End-to-end proxy tests: forwarding, token extraction, and logging.

Uses respx to mock upstream providers so no real API calls are needed.
Tests go through the full interceptor pipeline (handle_request → DB).
"""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from burnlens.proxy.interceptor import handle_request
from burnlens.proxy.providers import get_provider_for_path
from burnlens.proxy.streaming import extract_usage_from_stream, split_sse_events
from burnlens.storage.database import init_db
from burnlens.storage.queries import get_recent_requests


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _flush_tasks() -> None:
    """Yield control until background tasks (DB insert, asset upsert) finish."""
    for _ in range(15):
        await asyncio.sleep(0.05)


def _openai_chat_response(
    model: str = "gpt-4o",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello!"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _openai_streaming_chunks(
    prompt_tokens: int = 20,
    completion_tokens: int = 8,
) -> str:
    """Build SSE text for an OpenAI streaming response with usage in the final chunk."""
    chunks = [
        'data: {"id":"chatcmpl-s1","object":"chat.completion.chunk","model":"gpt-4o",'
        '"choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}\n\n',
        'data: {"id":"chatcmpl-s1","object":"chat.completion.chunk","model":"gpt-4o",'
        '"choices":[{"index":0,"delta":{"content":"Hi"},"finish_reason":null}]}\n\n',
        'data: {"id":"chatcmpl-s1","object":"chat.completion.chunk","model":"gpt-4o",'
        '"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n',
        # Final chunk with usage (sent when stream_options.include_usage=true)
        f'data: {{"id":"chatcmpl-s1","object":"chat.completion.chunk","model":"gpt-4o",'
        f'"choices":[],'
        f'"usage":{{"prompt_tokens":{prompt_tokens},"completion_tokens":{completion_tokens},'
        f'"total_tokens":{prompt_tokens + completion_tokens}}}}}\n\n',
        "data: [DONE]\n\n",
    ]
    return "".join(chunks)


def _anthropic_response(input_tokens: int = 12, output_tokens: int = 9) -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-4-5-20251001",
        "content": [{"type": "text", "text": "Hello!"}],
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    }


def _anthropic_streaming_chunks(input_tokens: int = 14, output_tokens: int = 10) -> str:
    """Build SSE text for an Anthropic streaming response.

    Usage is split: message_start carries input_tokens, message_delta carries output_tokens.
    """
    chunks = [
        f'event: message_start\ndata: {{"type":"message_start","message":'
        f'{{"id":"msg_s1","type":"message","role":"assistant","model":"claude-haiku-4-5-20251001",'
        f'"content":[],"stop_reason":null,'
        f'"usage":{{"input_tokens":{input_tokens},"output_tokens":0}}}}}}\n\n',

        'event: content_block_start\ndata: {"type":"content_block_start",'
        '"index":0,"content_block":{"type":"text","text":""}}\n\n',

        'event: content_block_delta\ndata: {"type":"content_block_delta",'
        '"index":0,"delta":{"type":"text_delta","text":"Hello!"}}\n\n',

        'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n',

        f'event: message_delta\ndata: {{"type":"message_delta",'
        f'"delta":{{"stop_reason":"end_turn"}},'
        f'"usage":{{"output_tokens":{output_tokens}}}}}\n\n',

        'event: message_stop\ndata: {"type":"message_stop"}\n\n',
    ]
    return "".join(chunks)


def _google_response(prompt_tokens: int = 25, candidates_tokens: int = 15) -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "Hello!"}],
                    "role": "model",
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": candidates_tokens,
            "totalTokenCount": prompt_tokens + candidates_tokens,
        },
    }


def _request_body(model: str = "gpt-4o", stream: bool = False) -> bytes:
    return json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Hello"}],
        **({"stream": True, "stream_options": {"include_usage": True}} if stream else {}),
    }).encode()


def _anthropic_request_body(
    model: str = "claude-haiku-4-5-20251001", stream: bool = False,
) -> bytes:
    return json.dumps({
        "model": model,
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "Hello"}],
        **({"stream": True} if stream else {}),
    }).encode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "e2e_test.db")


@pytest.fixture
async def initialized_db(db_path: str) -> str:
    """Initialize DB schema and return path."""
    await init_db(db_path)
    return db_path


async def _get_last_row(db_path: str) -> dict:
    """Return the most recently inserted request row."""
    await _flush_tasks()
    rows = await get_recent_requests(db_path, limit=1)
    assert len(rows) >= 1, "Expected at least 1 row in requests table"
    return rows[0]


async def _call_proxy(
    provider_path: str,
    proxy_path: str,
    body: bytes,
    db_path: str,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes | None, object]:
    """Helper: call handle_request with a respx-mocked httpx client."""
    provider = get_provider_for_path(provider_path)
    assert provider is not None, f"No provider for {provider_path}"

    hdrs = {"content-type": "application/json"}
    if headers:
        hdrs.update(headers)

    async with httpx.AsyncClient() as client:
        return await handle_request(
            client=client,
            provider=provider,
            path=proxy_path,
            method="POST",
            headers=hdrs,
            body_bytes=body,
            query_string="",
            db_path=db_path,
        )


async def _drain_stream(stream) -> bytes:
    """Consume an async stream and return concatenated bytes."""
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# 1. OpenAI non-streaming: tokens captured
# ---------------------------------------------------------------------------


class TestOpenAINonStreaming:
    async def test_openai_nonstreaming_tokens_captured(self, initialized_db):
        mock_resp = _openai_chat_response(
            model="gpt-4o-mini", prompt_tokens=15, completion_tokens=10,
        )
        with respx.mock(assert_all_called=False) as router:
            router.post("https://api.openai.com/v1/chat/completions").respond(
                200, json=mock_resp,
            )
            status, _, body, stream = await _call_proxy(
                "/proxy/openai/v1/chat/completions",
                "/proxy/openai/v1/chat/completions",
                _request_body("gpt-4o-mini"),
                initialized_db,
            )
        assert status == 200
        assert stream is None
        assert body is not None

        row = await _get_last_row(initialized_db)
        assert row["provider"] == "openai"
        assert row["model"] == "gpt-4o-mini"
        assert row["input_tokens"] == 15
        assert row["output_tokens"] == 10
        assert row["cost_usd"] > 0


# ---------------------------------------------------------------------------
# 2. OpenAI streaming: tokens captured
# ---------------------------------------------------------------------------


class TestOpenAIStreaming:
    async def test_openai_streaming_tokens_captured(self, initialized_db):
        sse_text = _openai_streaming_chunks(prompt_tokens=20, completion_tokens=8)
        with respx.mock(assert_all_called=False) as router:
            router.post("https://api.openai.com/v1/chat/completions").respond(
                200,
                text=sse_text,
                headers={"content-type": "text/event-stream"},
            )
            status, _, body, stream = await _call_proxy(
                "/proxy/openai/v1/chat/completions",
                "/proxy/openai/v1/chat/completions",
                _request_body("gpt-4o", stream=True),
                initialized_db,
            )
        assert status == 200
        assert stream is not None
        # Must drain the stream to trigger usage extraction
        await _drain_stream(stream)

        row = await _get_last_row(initialized_db)
        assert row["provider"] == "openai"
        assert row["input_tokens"] == 20
        assert row["output_tokens"] == 8
        assert row["cost_usd"] > 0


# ---------------------------------------------------------------------------
# 3. Anthropic non-streaming: tokens captured
# ---------------------------------------------------------------------------


class TestAnthropicNonStreaming:
    async def test_anthropic_nonstreaming_tokens_captured(self, initialized_db):
        mock_resp = _anthropic_response(input_tokens=12, output_tokens=9)
        with respx.mock(assert_all_called=False) as router:
            router.post("https://api.anthropic.com/v1/messages").respond(
                200, json=mock_resp,
            )
            status, _, body, stream = await _call_proxy(
                "/proxy/anthropic/v1/messages",
                "/proxy/anthropic/v1/messages",
                _anthropic_request_body(),
                initialized_db,
                headers={
                    "x-api-key": "sk-ant-test",
                    "anthropic-version": "2023-06-01",
                },
            )
        assert status == 200

        row = await _get_last_row(initialized_db)
        assert row["provider"] == "anthropic"
        assert row["input_tokens"] == 12
        assert row["output_tokens"] == 9
        assert row["cost_usd"] > 0


# ---------------------------------------------------------------------------
# 4. Anthropic streaming: tokens captured (known bug I-1 — xfail)
# ---------------------------------------------------------------------------


class TestAnthropicStreaming:
    async def test_anthropic_streaming_tokens_captured(self, initialized_db):
        sse_text = _anthropic_streaming_chunks(input_tokens=14, output_tokens=10)
        with respx.mock(assert_all_called=False) as router:
            router.post("https://api.anthropic.com/v1/messages").respond(
                200,
                text=sse_text,
                headers={"content-type": "text/event-stream"},
            )
            status, _, body, stream = await _call_proxy(
                "/proxy/anthropic/v1/messages",
                "/proxy/anthropic/v1/messages",
                _anthropic_request_body(stream=True),
                initialized_db,
                headers={
                    "x-api-key": "sk-ant-test",
                    "anthropic-version": "2023-06-01",
                },
            )
        assert status == 200
        assert stream is not None
        await _drain_stream(stream)

        row = await _get_last_row(initialized_db)
        assert row["provider"] == "anthropic"
        assert row["input_tokens"] == 14
        assert row["output_tokens"] == 10
        assert row["cost_usd"] > 0


# ---------------------------------------------------------------------------
# 5. Google: tokens captured
# ---------------------------------------------------------------------------


class TestGoogleTokens:
    async def test_google_tokens_captured(self, initialized_db):
        mock_resp = _google_response(prompt_tokens=25, candidates_tokens=15)
        with respx.mock(assert_all_called=False) as router:
            router.post(
                url__regex=r"https://generativelanguage\.googleapis\.com/.*"
            ).respond(200, json=mock_resp)

            body = json.dumps({
                "contents": [{"parts": [{"text": "Hello"}]}],
            }).encode()
            status, _, resp_body, stream = await _call_proxy(
                "/proxy/google/v1beta/models/gemini-1.5-flash:generateContent",
                "/proxy/google/v1beta/models/gemini-1.5-flash:generateContent",
                body,
                initialized_db,
            )
        assert status == 200

        row = await _get_last_row(initialized_db)
        assert row["provider"] == "google"
        assert row["model"] == "gemini-1.5-flash"
        assert row["input_tokens"] == 25
        assert row["output_tokens"] == 15
        assert row["cost_usd"] > 0


# ---------------------------------------------------------------------------
# 6. Tags stripped from upstream, logged to DB
# ---------------------------------------------------------------------------


class TestTagStripping:
    async def test_tags_stripped_from_upstream_request(self, initialized_db):
        mock_resp = _openai_chat_response()
        with respx.mock(assert_all_called=False) as router:
            route = router.post("https://api.openai.com/v1/chat/completions").respond(
                200, json=mock_resp,
            )
            status, _, _, _ = await _call_proxy(
                "/proxy/openai/v1/chat/completions",
                "/proxy/openai/v1/chat/completions",
                _request_body("gpt-4o"),
                initialized_db,
                headers={
                    "authorization": "Bearer sk-test",
                    "X-BurnLens-Tag-Feature": "chat",
                    "X-BurnLens-Tag-Team": "backend",
                },
            )
        assert status == 200

        # Verify upstream did NOT receive BurnLens tag headers
        assert len(route.calls) == 1
        forwarded_headers = dict(route.calls[0].request.headers)
        for key in forwarded_headers:
            assert not key.lower().startswith("x-burnlens-"), (
                f"BurnLens header {key!r} leaked to upstream"
            )
        # Auth header should be forwarded
        assert "authorization" in {k.lower() for k in forwarded_headers}

        # Verify DB row has the tags
        row = await _get_last_row(initialized_db)
        tags = row["tags"]
        assert isinstance(tags, dict)
        # Tag keys are the suffix after X-BurnLens-Tag- (lowered by _extract_tags)
        assert tags.get("Feature") == "chat" or tags.get("feature") == "chat"
        assert tags.get("Team") == "backend" or tags.get("team") == "backend"


# ---------------------------------------------------------------------------
# 7. Response body unmodified
# ---------------------------------------------------------------------------


class TestResponseUnmodified:
    async def test_response_body_unmodified(self, initialized_db):
        mock_resp = _openai_chat_response(prompt_tokens=50, completion_tokens=25)
        expected_bytes = json.dumps(mock_resp).encode()

        with respx.mock(assert_all_called=False) as router:
            router.post("https://api.openai.com/v1/chat/completions").respond(
                200,
                content=expected_bytes,
                headers={"content-type": "application/json"},
            )
            status, _, resp_body, stream = await _call_proxy(
                "/proxy/openai/v1/chat/completions",
                "/proxy/openai/v1/chat/completions",
                _request_body("gpt-4o"),
                initialized_db,
            )
        assert status == 200
        assert stream is None
        # The proxy must return the identical body byte-for-byte
        assert resp_body == expected_bytes


# ---------------------------------------------------------------------------
# 8. Proxy latency overhead < 20ms
# ---------------------------------------------------------------------------


class TestProxyLatency:
    async def test_proxy_latency_under_20ms_overhead(self, initialized_db):
        mock_resp = _openai_chat_response()
        body = _request_body("gpt-4o")
        provider = get_provider_for_path("/proxy/openai/v1/chat/completions")

        # Warm-up call
        with respx.mock(assert_all_called=False) as router:
            router.post("https://api.openai.com/v1/chat/completions").respond(
                200, json=mock_resp,
            )
            async with httpx.AsyncClient() as client:
                await handle_request(
                    client=client, provider=provider,
                    path="/proxy/openai/v1/chat/completions",
                    method="POST",
                    headers={"content-type": "application/json"},
                    body_bytes=body, query_string="",
                    db_path=initialized_db,
                )
        await _flush_tasks()

        # Timed calls (average of 5)
        durations = []
        for _ in range(5):
            with respx.mock(assert_all_called=False) as router:
                router.post("https://api.openai.com/v1/chat/completions").respond(
                    200, json=mock_resp,
                )
                async with httpx.AsyncClient() as client:
                    start = time.monotonic()
                    await handle_request(
                        client=client, provider=provider,
                        path="/proxy/openai/v1/chat/completions",
                        method="POST",
                        headers={"content-type": "application/json"},
                        body_bytes=body, query_string="",
                        db_path=initialized_db,
                    )
                    elapsed_ms = (time.monotonic() - start) * 1000
                    durations.append(elapsed_ms)
        await _flush_tasks()

        avg_ms = sum(durations) / len(durations)
        # With mocked upstream (near-zero latency), total overhead should be < 20ms
        assert avg_ms < 20, f"Avg proxy overhead {avg_ms:.1f}ms exceeds 20ms limit"


# ---------------------------------------------------------------------------
# 9. Fail open on logging error
# ---------------------------------------------------------------------------


class TestFailOpen:
    async def test_fail_open_on_logging_error(self, initialized_db):
        mock_resp = _openai_chat_response()

        with respx.mock(assert_all_called=False) as router:
            router.post("https://api.openai.com/v1/chat/completions").respond(
                200, json=mock_resp,
            )
            # Patch insert_request to raise — proxy must still return the response
            with patch(
                "burnlens.proxy.interceptor.insert_request",
                new_callable=AsyncMock,
                side_effect=Exception("DB write failed"),
            ):
                status, _, resp_body, _ = await _call_proxy(
                    "/proxy/openai/v1/chat/completions",
                    "/proxy/openai/v1/chat/completions",
                    _request_body("gpt-4o"),
                    initialized_db,
                )
        assert status == 200
        assert json.loads(resp_body)["model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# 10. Unknown model: cost_usd=0, no crash
# ---------------------------------------------------------------------------


class TestUnknownModel:
    async def test_unknown_model_logs_cost_zero_no_crash(self, initialized_db):
        mock_resp = _openai_chat_response(
            model="gpt-99-ultra", prompt_tokens=50, completion_tokens=20,
        )
        with respx.mock(assert_all_called=False) as router:
            router.post("https://api.openai.com/v1/chat/completions").respond(
                200, json=mock_resp,
            )
            status, _, _, _ = await _call_proxy(
                "/proxy/openai/v1/chat/completions",
                "/proxy/openai/v1/chat/completions",
                _request_body("gpt-99-ultra"),
                initialized_db,
            )
        assert status == 200

        row = await _get_last_row(initialized_db)
        assert row["model"] == "gpt-99-ultra"
        assert row["input_tokens"] == 50
        assert row["output_tokens"] == 20
        assert row["cost_usd"] == 0.0


# ---------------------------------------------------------------------------
# 11. Chunk fragmentation regression tests
# ---------------------------------------------------------------------------


class TestSplitSseEvents:
    """Unit tests for the SSE event reassembly logic."""

    def test_single_complete_event(self):
        buf = 'data: {"usage":{"prompt_tokens":10}}\n\n'
        events = split_sse_events(buf)
        assert len(events) == 1
        assert '"usage"' in events[0]

    def test_multiple_events_filters_usage_only(self):
        buf = (
            'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n'
            'data: {"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n'
            "data: [DONE]\n\n"
        )
        events = split_sse_events(buf)
        assert len(events) == 1
        assert "prompt_tokens" in events[0]

    def test_anthropic_two_usage_events(self):
        buf = _anthropic_streaming_chunks(input_tokens=14, output_tokens=10)
        events = split_sse_events(buf)
        # Should capture message_start (input) and message_delta (output)
        assert len(events) >= 2
        texts = " ".join(events)
        assert "message_start" in texts
        assert "message_delta" in texts

    def test_empty_buffer(self):
        assert split_sse_events("") == []
        assert split_sse_events("\n\n\n") == []


class _FragmentedStream(httpx.AsyncByteStream):
    """An async byte stream that yields pre-fragmented chunks."""

    def __init__(self, fragments: list[bytes]):
        self._fragments = fragments

    async def __aiter__(self):
        for frag in self._fragments:
            yield frag

    async def aclose(self) -> None:
        pass


def _make_fragmented_transport(
    sse_full: str, fragment_size: int = 40,
) -> httpx.AsyncBaseTransport:
    """Build a transport that fragments SSE text into small TCP-like chunks."""
    fragments = [
        sse_full[i : i + fragment_size].encode()
        for i in range(0, len(sse_full), fragment_size)
    ]

    class _Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=_FragmentedStream(list(fragments)),
            )

    return _Transport()


class TestAnthropicFragmented:
    """Regression: Anthropic SSE events split across TCP chunks."""

    async def test_anthropic_streaming_fragmented_chunks(self, initialized_db):
        """Simulate real-world chunk fragmentation where SSE events are split
        across multiple TCP chunks, including mid-JSON splits."""
        sse_full = _anthropic_streaming_chunks(input_tokens=14, output_tokens=10)
        transport = _make_fragmented_transport(sse_full, fragment_size=40)

        provider = get_provider_for_path("/proxy/anthropic/v1/messages")
        async with httpx.AsyncClient(transport=transport) as client:
            status, _, body, stream = await handle_request(
                client=client,
                provider=provider,
                path="/proxy/anthropic/v1/messages",
                method="POST",
                headers={
                    "content-type": "application/json",
                    "x-api-key": "sk-ant-test",
                    "anthropic-version": "2023-06-01",
                },
                body_bytes=_anthropic_request_body(stream=True),
                query_string="",
                db_path=initialized_db,
            )

        assert status == 200
        assert stream is not None
        await _drain_stream(stream)

        row = await _get_last_row(initialized_db)
        assert row["provider"] == "anthropic"
        assert row["input_tokens"] == 14, f"Expected 14, got {row['input_tokens']}"
        assert row["output_tokens"] == 10, f"Expected 10, got {row['output_tokens']}"
        assert row["cost_usd"] > 0


class TestOpenAIFragmented:
    """Regression: OpenAI SSE usage chunk split across TCP boundaries."""

    async def test_openai_streaming_fragmented_chunks(self, initialized_db):
        sse_full = _openai_streaming_chunks(prompt_tokens=20, completion_tokens=8)
        transport = _make_fragmented_transport(sse_full, fragment_size=35)

        provider = get_provider_for_path("/proxy/openai/v1/chat/completions")
        async with httpx.AsyncClient(transport=transport) as client:
            status, _, body, stream = await handle_request(
                client=client,
                provider=provider,
                path="/proxy/openai/v1/chat/completions",
                method="POST",
                headers={"content-type": "application/json"},
                body_bytes=_request_body("gpt-4o", stream=True),
                query_string="",
                db_path=initialized_db,
            )

        assert status == 200
        assert stream is not None
        await _drain_stream(stream)

        row = await _get_last_row(initialized_db)
        assert row["provider"] == "openai"
        assert row["input_tokens"] == 20, f"Expected 20, got {row['input_tokens']}"
        assert row["output_tokens"] == 8, f"Expected 8, got {row['output_tokens']}"
        assert row["cost_usd"] > 0


class TestGoogleFragmented:
    """Regression: Google SSE usageMetadata split across TCP chunks."""

    async def test_google_streaming_fragmented_chunks(self, initialized_db):
        sse_full = (
            'data: {"candidates":[{"content":{"parts":[{"text":"Hi"}]}}]}\n\n'
            'data: {"candidates":[{"content":{"parts":[{"text":"!"}]}}],'
            '"usageMetadata":{"promptTokenCount":25,"candidatesTokenCount":15,'
            '"totalTokenCount":40}}\n\n'
        )
        transport = _make_fragmented_transport(sse_full, fragment_size=30)

        provider = get_provider_for_path(
            "/proxy/google/v1beta/models/gemini-1.5-flash:streamGenerateContent"
        )
        body = json.dumps({"contents": [{"parts": [{"text": "Hello"}]}]}).encode()
        async with httpx.AsyncClient(transport=transport) as client:
            status, _, resp_body, stream = await handle_request(
                client=client,
                provider=provider,
                path="/proxy/google/v1beta/models/gemini-1.5-flash:streamGenerateContent",
                method="POST",
                headers={"content-type": "application/json"},
                body_bytes=body,
                query_string="",
                db_path=initialized_db,
            )

        assert status == 200
        assert stream is not None
        await _drain_stream(stream)

        row = await _get_last_row(initialized_db)
        assert row["provider"] == "google"
        assert row["input_tokens"] == 25, f"Expected 25, got {row['input_tokens']}"
        assert row["output_tokens"] == 15, f"Expected 15, got {row['output_tokens']}"
        assert row["cost_usd"] > 0
