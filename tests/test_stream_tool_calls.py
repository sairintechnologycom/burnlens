"""Tool calls are counted on the streaming path, not silently recorded as 0.

Before this, ``tool_calls`` came from ``count_tool_calls()`` — a single parse of
a complete response body — so every *streaming* request stored 0 no matter how
many tools it called. Since agents stream, that meant the column under-counted
exactly the traffic it exists to describe.

The counting reads the *whole* stream buffer, not the usage-gated subset:
``should_buffer_chunk`` keeps only usage-bearing events, and tool events carry no
usage.
"""

import asyncio
import json

import aiosqlite
import httpx
import pytest

from burnlens.providers import get
from burnlens.proxy.interceptor import handle_request
from burnlens.proxy.providers import get_provider_for_path

from .conftest import settle_background_tasks

# One call fragmented across four deltas, plus a second parallel call. Only the
# first delta of each carries id/name; the rest are argument fragments that
# repeat the same index — counting deltas would report 5.
OPENAI_SSE = (
    'data: {"choices":[{"delta":{"content":"thinking"}}]}\n\n'
    'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_a",'
    '"function":{"name":"get_weather","arguments":""}}]}}]}\n\n'
    'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
    '"function":{"arguments":"{\\"city\\":"}}]}}]}\n\n'
    'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
    '"function":{"arguments":"\\"Pune\\"}"}}]}}]}\n\n'
    'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"id":"call_b",'
    '"function":{"name":"get_time","arguments":"{}"}}]}}]}\n\n'
    'data: {"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n'
    "data: [DONE]\n\n"
)

ANTHROPIC_SSE = (
    'event: message_start\n'
    'data: {"type":"message_start","message":{"usage":{"input_tokens":10}}}\n\n'
    'event: content_block_start\n'
    'data: {"type":"content_block_start","index":0,'
    '"content_block":{"type":"text","text":""}}\n\n'
    'event: content_block_start\n'
    'data: {"type":"content_block_start","index":1,'
    '"content_block":{"type":"tool_use","id":"toolu_a","name":"get_weather"}}\n\n'
    'event: content_block_delta\n'
    'data: {"type":"content_block_delta","index":1,'
    '"delta":{"type":"input_json_delta","partial_json":"{\\"city\\""}}\n\n'
    'event: content_block_start\n'
    'data: {"type":"content_block_start","index":2,'
    '"content_block":{"type":"tool_use","id":"toolu_b","name":"get_time"}}\n\n'
    'event: message_delta\n'
    'data: {"type":"message_delta","usage":{"output_tokens":5}}\n\n'
)

GOOGLE_SSE = (
    'data: {"candidates":[{"content":{"parts":[{"text":"one moment"}]}}]}\n\n'
    'data: {"candidates":[{"content":{"parts":['
    '{"functionCall":{"name":"get_weather","args":{"city":"Pune"}}}]}}]}\n\n'
    'data: {"candidates":[{"content":{"parts":['
    '{"functionCall":{"name":"get_time","args":{}}}]}}],'
    '"usageMetadata":{"promptTokenCount":10,"candidatesTokenCount":5}}\n\n'
)


class TestCountingPerWireShape:
    def test_openai_deltas_dedupe_by_index(self):
        assert get("openai").count_tool_calls_in_stream(OPENAI_SSE) == 2

    def test_anthropic_counts_only_tool_use_blocks(self):
        # The text content_block_start must not be counted.
        assert get("anthropic").count_tool_calls_in_stream(ANTHROPIC_SSE) == 2

    def test_google_counts_function_call_parts(self):
        assert get("google").count_tool_calls_in_stream(GOOGLE_SSE) == 2

    @pytest.mark.parametrize(
        "buffer",
        [
            "",
            'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n',
            'data: {"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n',
            "data: [DONE]\n\n",
            'data: {"choices":[{"delta":{"tool_calls":\n\n',  # truncated JSON
            "not an sse stream at all",
        ],
    )
    def test_tool_free_or_malformed_counts_zero(self, buffer):
        assert get("openai").count_tool_calls_in_stream(buffer) == 0


class TestProxiedStream:
    """The whole path: a streaming call with tools lands a non-zero row.

    The unit tests above cover counting alone; this is the only check that the
    count survives the generator's finally block and the background log task —
    the plumbing a later edit is most likely to drop.
    """

    @pytest.mark.asyncio
    async def test_streaming_tool_calls_reach_the_row(self, initialized_db):
        class _Transport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                return httpx.Response(
                    200,
                    content=OPENAI_SSE.encode(),
                    headers={"content-type": "text/event-stream"},
                )

        _, _, _, stream = await handle_request(
            client=httpx.AsyncClient(transport=_Transport()),
            provider=get_provider_for_path("/proxy/openai/v1/chat/completions"),
            path="/proxy/openai/v1/chat/completions",
            method="POST",
            headers={"content-type": "application/json"},
            body_bytes=json.dumps(
                {"model": "gpt-4o", "messages": [], "stream": True}
            ).encode(),
            query_string="",
            db_path=initialized_db,
            alert_engine=None,
        )
        # The counting lives in the generator's finally block, so it only runs
        # once a client drains the stream.
        async for _chunk in stream:
            pass
        await settle_background_tasks()

        async with aiosqlite.connect(initialized_db) as db:
            cursor = await db.execute(
                "SELECT tool_calls FROM requests ORDER BY id DESC LIMIT 1"
            )
            row = await cursor.fetchone()
        assert row == (2,)
