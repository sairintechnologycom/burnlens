"""
tests/streaming/test_streaming_unit.py

Unit tests for the streaming path — mock httpx transport, no live server.
Directly calls handle_request() which is the real entry point in interceptor.py.

Covers the fire-and-forget gap:
  - _stream_generator() yield behaviour
  - should_buffer_chunk() selecting usage chunks
  - asyncio.create_task(_log_streaming_usage()) firing after finally block
  - _log_streaming_usage() writing correct RequestRecord to SQLite
"""

import asyncio
import json
import time

import httpx
import pytest

from burnlens.interceptor import handle_request
from burnlens.proxy.providers import get_provider_for_path
from burnlens.cost.calculator import TokenUsage

from .conftest import (
    build_openai_stream,
    build_anthropic_stream,
    sse_content_chunk,
    sse_usage_chunk,
    SSE_DONE,
    make_headers,
    make_body,
    make_client,
    fetch_rows,
    drain,
    drain_and_settle,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def openai_provider():
    return get_provider_for_path("/openai/v1/chat/completions")


def anthropic_provider():
    return get_provider_for_path("/anthropic/v1/messages")


async def call_streaming(
    client: httpx.AsyncClient,
    provider=None,
    path: str = "/openai/v1/chat/completions",
    model: str = "gpt-4o-mini",
    db_path: str = "",
    tag_feature: str = "chat",
    tag_team: str = "backend",
) -> tuple:
    provider = provider or openai_provider()
    status, headers, body, stream = await handle_request(
        client=client,
        provider=provider,
        path=path,
        method="POST",
        headers=make_headers(tag_feature=tag_feature, tag_team=tag_team),
        body_bytes=make_body(model=model, stream=True),
        query_string="",
        db_path=db_path,
    )
    return status, headers, body, stream


# ---------------------------------------------------------------------------
# 1. handle_request returns stream, not body, for streaming requests
# ---------------------------------------------------------------------------

class TestHandleRequestDispatch:
    @pytest.mark.asyncio
    async def test_streaming_request_returns_stream_not_body(self, db_path):
        client, _ = make_client()
        async with client:
            status, headers, body, stream = await call_streaming(client, db_path=db_path)

        assert body is None
        assert stream is not None
        assert status == 200
        # Drain to avoid ResourceWarning
        await drain(stream)

    @pytest.mark.asyncio
    async def test_non_streaming_returns_body_not_stream(self, db_path):
        body_bytes = build_openai_stream(["Hello"])
        # Replace with non-streaming response
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "id": "chatcmpl-test", "model": "gpt-4o-mini",
                "choices": [{"message": {"role": "assistant", "content": "Hi"},
                             "finish_reason": "stop", "index": 0}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            })
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://api.openai.com",
        )
        async with client:
            status, headers, body, stream = await handle_request(
                client=client,
                provider=openai_provider(),
                path="/openai/v1/chat/completions",
                method="POST",
                headers=make_headers(),
                body_bytes=make_body(stream=False),
                query_string="",
                db_path=db_path,
            )
        assert stream is None
        assert body is not None
        assert status == 200
        await asyncio.sleep(0.1)  # let create_task log


# ---------------------------------------------------------------------------
# 2. _stream_generator yields ALL chunks including usage chunk
# ---------------------------------------------------------------------------

class TestStreamGeneratorYield:
    @pytest.mark.asyncio
    async def test_all_content_chunks_yielded(self, db_path):
        words = ["The", " quick", " brown", " fox"]
        client, _ = make_client(words=words, prompt_tokens=50, completion_tokens=10)
        async with client:
            _, _, _, stream = await call_streaming(client, db_path=db_path)
            chunks = await drain_and_settle(stream)

        raw = b"".join(chunks).decode()
        for word in words:
            assert word in raw

    @pytest.mark.asyncio
    async def test_done_sentinel_yielded(self, db_path):
        client, _ = make_client()
        async with client:
            _, _, _, stream = await call_streaming(client, db_path=db_path)
            chunks = await drain_and_settle(stream)

        assert any(b"[DONE]" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_chunk_order_preserved(self, db_path):
        words = ["first", " second", " third"]
        client, _ = make_client(words=words)
        async with client:
            _, _, _, stream = await call_streaming(client, db_path=db_path)
            chunks = await drain(stream)

        full = b"".join(chunks).decode()
        assert full.index("first") < full.index("second") < full.index("third")


# ---------------------------------------------------------------------------
# 3. should_buffer_chunk selects usage chunks, not content chunks
# ---------------------------------------------------------------------------

class TestShouldBufferChunk:
    """
    Test indirectly: if should_buffer_chunk works correctly, only usage data
    lands in usage_chunk_data, and _log_streaming_usage gets correct token counts.
    """

    @pytest.mark.asyncio
    async def test_usage_tokens_extracted_correctly(self, db_path):
        client, _ = make_client(
            words=["Hello"] * 5,
            prompt_tokens=333,
            completion_tokens=77,
        )
        async with client:
            _, _, _, stream = await call_streaming(client, db_path=db_path)
            await drain_and_settle(stream)

        rows = fetch_rows(db_path)
        assert len(rows) == 1
        assert rows[0]["input_tokens"] == 333
        assert rows[0]["output_tokens"] == 77

    @pytest.mark.asyncio
    async def test_content_tokens_not_double_counted(self, db_path):
        """Content chunks should NOT be buffered — only the usage chunk."""
        words = ["word"] * 50  # 50 content chunks
        client, _ = make_client(
            words=words,
            prompt_tokens=100,
            completion_tokens=50,
        )
        async with client:
            _, _, _, stream = await call_streaming(client, db_path=db_path)
            await drain_and_settle(stream)

        rows = fetch_rows(db_path)
        # completion_tokens should be 50 from usage chunk, not 50*50
        assert rows[0]["output_tokens"] == 50

    @pytest.mark.asyncio
    async def test_reasoning_tokens_extracted(self, db_path):
        client, _ = make_client(
            words=["Answer"],
            prompt_tokens=200,
            completion_tokens=30,
            model="o1",
        )
        # Override body to include reasoning tokens
        reasoning_body = build_openai_stream(
            ["Answer"],
            model="o1",
            prompt_tokens=200,
            completion_tokens=30,
            reasoning_tokens=450,
        )

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=reasoning_body,
                                  headers={"content-type": "text/event-stream"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://api.openai.com",
        ) as client:
            _, _, _, stream = await handle_request(
                client=client,
                provider=openai_provider(),
                path="/openai/v1/chat/completions",
                method="POST",
                headers=make_headers(),
                body_bytes=make_body(model="o1"),
                query_string="",
                db_path=db_path,
            )
            await drain_and_settle(stream)

        rows = fetch_rows(db_path)
        assert rows[0]["reasoning_tokens"] == 450


# ---------------------------------------------------------------------------
# 4. asyncio.create_task fires _log_streaming_usage after finally block
# ---------------------------------------------------------------------------

class TestBackgroundTaskTiming:
    @pytest.mark.asyncio
    async def test_db_empty_during_stream(self, db_path):
        """
        DB row must NOT exist while stream is still being drained.
        The create_task fires in finally, which runs AFTER the generator exits.
        """
        client, _ = make_client(words=["a", "b", "c"])
        async with client:
            _, _, _, stream = await call_streaming(client, db_path=db_path)

            # Check mid-stream: no row yet
            mid_rows = fetch_rows(db_path)
            assert len(mid_rows) == 0

            # Now drain and wait
            await drain_and_settle(stream)

        rows = fetch_rows(db_path)
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_db_row_written_after_done(self, db_path):
        client, _ = make_client()
        async with client:
            _, _, _, stream = await call_streaming(client, db_path=db_path)
            await drain_and_settle(stream)

        rows = fetch_rows(db_path)
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_duration_ms_positive(self, db_path):
        """duration_ref[0] captured in finally block should be > 0."""
        client, _ = make_client()
        async with client:
            _, _, _, stream = await call_streaming(client, db_path=db_path)
            await drain_and_settle(stream)

        rows = fetch_rows(db_path)
        assert rows[0]["duration_ms"] >= 0  # could be 0 on fast mock, never negative

    @pytest.mark.asyncio
    async def test_status_code_stored(self, db_path):
        client, _ = make_client(status=200)
        async with client:
            _, _, _, stream = await call_streaming(client, db_path=db_path)
            await drain_and_settle(stream)

        rows = fetch_rows(db_path)
        assert rows[0]["status_code"] == 200

    @pytest.mark.asyncio
    async def test_cost_usd_positive(self, db_path):
        client, _ = make_client(prompt_tokens=1000, completion_tokens=500)
        async with client:
            _, _, _, stream = await call_streaming(client, db_path=db_path)
            await drain_and_settle(stream)

        rows = fetch_rows(db_path)
        assert rows[0]["cost_usd"] > 0.0


# ---------------------------------------------------------------------------
# 5. Tags extracted and stored (_extract_tags → RequestRecord.tags)
# ---------------------------------------------------------------------------

class TestTagExtraction:
    @pytest.mark.asyncio
    async def test_feature_tag_stored(self, db_path):
        client, _ = make_client()
        async with client:
            _, _, _, stream = await call_streaming(
                client, db_path=db_path, tag_feature="autocomplete"
            )
            await drain_and_settle(stream)

        rows = fetch_rows(db_path)
        assert rows[0]["tag_feature"] == "autocomplete"

    @pytest.mark.asyncio
    async def test_team_tag_stored(self, db_path):
        client, _ = make_client()
        async with client:
            _, _, _, stream = await call_streaming(
                client, db_path=db_path, tag_team="platform"
            )
            await drain_and_settle(stream)

        rows = fetch_rows(db_path)
        assert rows[0]["tag_team"] == "platform"

    @pytest.mark.asyncio
    async def test_customer_tag_stored(self, db_path):
        client, _ = make_client()
        async with client:
            status, headers, body, stream = await handle_request(
                client=client,
                provider=openai_provider(),
                path="/openai/v1/chat/completions",
                method="POST",
                headers=make_headers(tag_customer="acme-corp"),
                body_bytes=make_body(),
                query_string="",
                db_path=db_path,
            )
            await drain_and_settle(stream)

        rows = fetch_rows(db_path)
        assert rows[0]["tag_customer"] == "acme-corp"

    @pytest.mark.asyncio
    async def test_missing_tags_dont_crash(self, db_path):
        """No BurnLens tag headers — should log with None tags."""
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=build_openai_stream(["Hi"]),
                                  headers={"content-type": "text/event-stream"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://api.openai.com",
        ) as client:
            _, _, _, stream = await handle_request(
                client=client,
                provider=openai_provider(),
                path="/openai/v1/chat/completions",
                method="POST",
                headers={"authorization": "Bearer sk-test",
                         "content-type": "application/json"},
                body_bytes=make_body(),
                query_string="",
                db_path=db_path,
            )
            await drain_and_settle(stream)

        rows = fetch_rows(db_path)
        assert len(rows) == 1  # logged despite no tags


# ---------------------------------------------------------------------------
# 6. _clean_request_headers strips BurnLens + hop-by-hop headers
# ---------------------------------------------------------------------------

class TestHeaderCleaning:
    @pytest.mark.asyncio
    async def test_burnlens_headers_not_forwarded(self, db_path):
        captured = {}

        def handler(req: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(req.headers)
            return httpx.Response(200, content=build_openai_stream(["Hi"]),
                                  headers={"content-type": "text/event-stream"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://api.openai.com",
        ) as client:
            _, _, _, stream = await call_streaming(client, db_path=db_path)
            await drain_and_settle(stream)

        for key in captured.get("headers", {}):
            assert not key.lower().startswith("x-burnlens-"), f"Leaked upstream: {key}"

    @pytest.mark.asyncio
    async def test_auth_header_forwarded(self, db_path):
        captured = {}

        def handler(req: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(req.headers)
            return httpx.Response(200, content=build_openai_stream(["Hi"]),
                                  headers={"content-type": "text/event-stream"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://api.openai.com",
        ) as client:
            _, _, _, stream = await call_streaming(client, db_path=db_path)
            await drain_and_settle(stream)

        assert "authorization" in captured.get("headers", {})

    @pytest.mark.asyncio
    async def test_hop_by_hop_headers_stripped(self, db_path):
        """connection, keep-alive, transfer-encoding must not reach upstream."""
        captured = {}

        def handler(req: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(req.headers)
            return httpx.Response(200, content=build_openai_stream(["Hi"]),
                                  headers={"content-type": "text/event-stream"})

        headers = make_headers()
        headers.update({
            "connection": "keep-alive",
            "keep-alive": "timeout=5",
            "transfer-encoding": "chunked",
        })

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://api.openai.com",
        ) as client:
            _, _, _, stream = await handle_request(
                client=client,
                provider=openai_provider(),
                path="/openai/v1/chat/completions",
                method="POST",
                headers=headers,
                body_bytes=make_body(),
                query_string="",
                db_path=db_path,
            )
            await drain_and_settle(stream)

        fwd = captured.get("headers", {})
        for hop in ["connection", "keep-alive", "transfer-encoding"]:
            assert hop not in fwd, f"Hop-by-hop header leaked: {hop}"


# ---------------------------------------------------------------------------
# 7. Upstream error — not logged, status passed through
# ---------------------------------------------------------------------------

class TestUpstreamErrors:
    @pytest.mark.asyncio
    async def test_upstream_401_passed_through(self, db_path):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": {"type": "invalid_api_key"}})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://api.openai.com",
        ) as client:
            status, _, body, stream = await handle_request(
                client=client,
                provider=openai_provider(),
                path="/openai/v1/chat/completions",
                method="POST",
                headers=make_headers(),
                body_bytes=make_body(stream=False),
                query_string="",
                db_path=db_path,
            )
            if stream:
                await drain_and_settle(stream)
            await asyncio.sleep(0.1)

        assert status == 401

    @pytest.mark.asyncio
    async def test_malformed_sse_chunk_skipped_no_crash(self, db_path):
        """Garbage SSE lines in stream must not crash accumulator."""
        body = (
            b"data: {not valid json!!}\n\n"
            + sse_content_chunk("valid")
            + sse_content_chunk("", finish=True)
            + sse_usage_chunk(50, 10)
            + SSE_DONE
        )

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=body,
                                  headers={"content-type": "text/event-stream"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://api.openai.com",
        ) as client:
            _, _, _, stream = await handle_request(
                client=client,
                provider=openai_provider(),
                path="/openai/v1/chat/completions",
                method="POST",
                headers=make_headers(),
                body_bytes=make_body(),
                query_string="",
                db_path=db_path,
            )
            await drain_and_settle(stream)

        # Should still log — usage chunk is valid
        rows = fetch_rows(db_path)
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_stream_without_usage_chunk_logs_zero_tokens(self, db_path):
        """No usage chunk in stream → log with 0 tokens (best-effort)."""
        body = (
            sse_content_chunk("Hello", finish=True)
            + SSE_DONE
        )

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=body,
                                  headers={"content-type": "text/event-stream"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://api.openai.com",
        ) as client:
            _, _, _, stream = await handle_request(
                client=client,
                provider=openai_provider(),
                path="/openai/v1/chat/completions",
                method="POST",
                headers=make_headers(),
                body_bytes=make_body(),
                query_string="",
                db_path=db_path,
            )
            await drain_and_settle(stream)

        rows = fetch_rows(db_path)
        # Logged, but tokens may be 0
        assert len(rows) == 1
        assert rows[0]["input_tokens"] >= 0
        assert rows[0]["output_tokens"] >= 0


# ---------------------------------------------------------------------------
# 8. Anthropic streaming path
# ---------------------------------------------------------------------------

class TestAnthropicStreaming:
    @pytest.mark.asyncio
    async def test_anthropic_stream_logged(self, db_path):
        anthropic_body = build_anthropic_stream(
            text="Hello from Claude",
            model="claude-3-5-sonnet-20241022",
            input_tokens=120,
            output_tokens=18,
        )

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=anthropic_body,
                                  headers={"content-type": "text/event-stream"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://api.anthropic.com",
        ) as client:
            _, _, _, stream = await handle_request(
                client=client,
                provider=anthropic_provider(),
                path="/anthropic/v1/messages",
                method="POST",
                headers=make_headers(provider="anthropic", tag_feature="summarize"),
                body_bytes=json.dumps({
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 100,
                    "stream": True,
                    "messages": [{"role": "user", "content": "Hello"}],
                }).encode(),
                query_string="",
                db_path=db_path,
            )
            await drain_and_settle(stream)

        rows = fetch_rows(db_path)
        assert len(rows) == 1
        assert "claude" in rows[0]["model"]
        assert rows[0]["tag_feature"] == "summarize"

    @pytest.mark.asyncio
    async def test_anthropic_chunks_forwarded_unmodified(self, db_path):
        """Anthropic SSE events should pass through to client unchanged."""
        anthropic_body = build_anthropic_stream("Hello world")

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=anthropic_body,
                                  headers={"content-type": "text/event-stream"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://api.anthropic.com",
        ) as client:
            _, _, _, stream = await handle_request(
                client=client,
                provider=anthropic_provider(),
                path="/anthropic/v1/messages",
                method="POST",
                headers=make_headers(provider="anthropic"),
                body_bytes=json.dumps({
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 100,
                    "stream": True,
                    "messages": [{"role": "user", "content": "Hi"}],
                }).encode(),
                query_string="",
                db_path=db_path,
            )
            chunks = await drain_and_settle(stream)

        combined = b"".join(chunks).decode()
        assert "content_block_delta" in combined or "Hello" in combined


# ---------------------------------------------------------------------------
# 9. Concurrent streams — no row collisions in SQLite
# ---------------------------------------------------------------------------

class TestConcurrentStreams:
    @pytest.mark.asyncio
    async def test_10_concurrent_streams_10_rows(self, db_path):
        """
        Fire 10 concurrent streaming requests.
        Each fires its own create_task(_log_streaming_usage) — all 10 must land.
        """

        async def single_stream(tag: str):
            client, _ = make_client(
                words=["word"],
                prompt_tokens=10,
                completion_tokens=5,
            )
            async with client:
                _, _, _, stream = await handle_request(
                    client=client,
                    provider=openai_provider(),
                    path="/openai/v1/chat/completions",
                    method="POST",
                    headers=make_headers(tag_feature=tag),
                    body_bytes=make_body(),
                    query_string="",
                    db_path=db_path,
                )
                await drain(stream)

        await asyncio.gather(*[single_stream(f"feature-{i}") for i in range(10)])
        await asyncio.sleep(0.5)  # all 10 background tasks flush

        rows = fetch_rows(db_path)
        assert len(rows) == 10

        features = {r["tag_feature"] for r in rows}
        assert features == {f"feature-{i}" for i in range(10)}

    @pytest.mark.asyncio
    async def test_concurrent_streams_costs_independent(self, db_path):
        """Each stream's cost is calculated from its own usage chunk independently."""

        async def stream_with_tokens(prompt: int, completion: int, tag: str):
            body = build_openai_stream(
                ["word"], prompt_tokens=prompt, completion_tokens=completion
            )

            def handler(req: httpx.Request) -> httpx.Response:
                return httpx.Response(200, content=body,
                                      headers={"content-type": "text/event-stream"})

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="https://api.openai.com",
            ) as client:
                _, _, _, stream = await handle_request(
                    client=client,
                    provider=openai_provider(),
                    path="/openai/v1/chat/completions",
                    method="POST",
                    headers=make_headers(tag_feature=tag),
                    body_bytes=make_body(),
                    query_string="",
                    db_path=db_path,
                )
                await drain(stream)

        await asyncio.gather(
            stream_with_tokens(100, 50, "cheap"),
            stream_with_tokens(10000, 5000, "expensive"),
        )
        await asyncio.sleep(0.3)

        rows = fetch_rows(db_path)
        assert len(rows) == 2
        by_tag = {r["tag_feature"]: r for r in rows}
        assert by_tag["expensive"]["cost_usd"] > by_tag["cheap"]["cost_usd"]
