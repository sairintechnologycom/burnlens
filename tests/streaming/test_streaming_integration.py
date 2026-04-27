"""
tests/streaming/test_streaming_integration.py

Live integration tests — spin up the full BurnLens ASGI app on a real port,
hit it with a real httpx client, intercept upstream with respx.

This is the definitive test of the fire-and-forget streaming path because:
  - Real TCP sockets + real asyncio event loop tasks
  - Real uvicorn request lifecycle (request → ASGI scope → handle_request)
  - asyncio.create_task() fires in the server's event loop, not the test loop
  - respx intercepts the outbound httpx call via an injected MockRouter transport,
    bypassing the asyncio ContextVar isolation that breaks global respx.mock()

Marker: @pytest.mark.integration
Run with: pytest tests/streaming/test_streaming_integration.py -v -m integration
"""

import asyncio
import json
import socket
import time

import httpx
import pytest
import pytest_asyncio
import respx

from .conftest import (
    build_openai_stream,
    build_anthropic_stream,
    sse_content_chunk,
    sse_usage_chunk,
    SSE_DONE,
    fetch_rows,
)


class _RespxTransport(httpx.AsyncBaseTransport):
    """Thin adapter making a respx.MockRouter usable as an httpx transport."""

    def __init__(self, router: respx.MockRouter) -> None:
        self._router = router

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._router.async_handler(request)

    async def aclose(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Live proxy fixture — real ASGI server with injected respx router
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def live_server(db_path):
    """
    Start the BurnLens ASGI app on a random port.

    Injects a respx.MockRouter as the server's httpx transport so upstream
    calls can be intercepted without relying on global asyncio context patching.

    Yields (base_url, db_path, router) where router is a respx.MockRouter
    that tests use to register per-test mock routes.
    """
    import uvicorn
    from burnlens.server import create_app

    # Build a shared router; assert_all_mocked=False lets unregistered routes
    # raise clearly instead of silently passing through.
    router = respx.MockRouter(assert_all_mocked=True)
    transport = _RespxTransport(router)

    server_client = httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(300.0),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )

    app = create_app(db_path=db_path, http_client=server_client)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)

    task = asyncio.create_task(server.serve())
    for _ in range(100):
        await asyncio.sleep(0.05)
        if server.started:
            break
    else:
        pytest.fail("Live server did not start in time")

    yield f"http://127.0.0.1:{port}", db_path, router

    server.should_exit = True
    await task


# ---------------------------------------------------------------------------
# Helper: stream a request through the live proxy
# ---------------------------------------------------------------------------

async def proxy_stream(
    base_url: str,
    path: str = "/proxy/openai/v1/chat/completions",
    model: str = "gpt-4o-mini",
    tag_feature: str = "chat",
    tag_team: str = "backend",
    extra_headers: dict = None,
) -> list[str]:
    """Stream a request through the live proxy, return all non-empty lines."""
    headers = {
        "authorization": "Bearer sk-test",
        "content-type": "application/json",
        "x-burnlens-tag-feature": tag_feature,
        "x-burnlens-tag-team": tag_team,
    }
    if extra_headers:
        headers.update(extra_headers)

    async with httpx.AsyncClient(base_url=base_url, timeout=15.0) as client:
        async with client.stream(
            "POST", path,
            headers=headers,
            json={
                "model": model,
                "stream": True,
                "stream_options": {"include_usage": True},
                "messages": [{"role": "user", "content": "Hello"}],
            },
        ) as response:
            lines = []
            async for line in response.aiter_lines():
                if line:
                    lines.append(line)
            return lines


def _openai_mock(router: respx.MockRouter, sse_body: bytes) -> None:
    """Register a one-shot POST mock on the router for the OpenAI completions endpoint."""
    router.post("https://api.openai.com/v1/chat/completions").return_value = httpx.Response(
        200, content=sse_body,
        headers={"content-type": "text/event-stream"},
    )


# ---------------------------------------------------------------------------
# 1. Full round-trip: client receives correct SSE lines
# ---------------------------------------------------------------------------

class TestFullRoundTrip:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_content_chunks_arrive_at_client(self, live_server):
        base_url, db_path, mock = live_server
        words = ["The", " answer", " is", " 42"]
        sse_body = build_openai_stream(words, prompt_tokens=80, completion_tokens=10)
        _openai_mock(mock, sse_body)

        lines = await proxy_stream(base_url)

        assert any("The" in l for l in lines)
        assert any("42" in l for l in lines)

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_done_sentinel_forwarded(self, live_server):
        base_url, db_path, mock = live_server
        sse_body = build_openai_stream(["Hi"])
        _openai_mock(mock, sse_body)

        lines = await proxy_stream(base_url)

        assert any("[DONE]" in l for l in lines)

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_response_is_event_stream(self, live_server):
        base_url, db_path, mock = live_server
        sse_body = build_openai_stream(["Hi"])
        _openai_mock(mock, sse_body)

        async with httpx.AsyncClient(base_url=base_url) as client:
            async with client.stream(
                "POST", "/proxy/openai/v1/chat/completions",
                headers={"authorization": "Bearer sk-test",
                         "content-type": "application/json"},
                json={"model": "gpt-4o-mini", "stream": True,
                      "messages": [{"role": "user", "content": "Hi"}]},
            ) as resp:
                assert resp.status_code == 200
                assert "text/event-stream" in resp.headers.get("content-type", "")
                async for _ in resp.aiter_bytes():
                    pass


# ---------------------------------------------------------------------------
# 2. DB row written by background task in server event loop
# ---------------------------------------------------------------------------

class TestServerSideLogging:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_db_row_created_after_stream(self, live_server):
        base_url, db_path, mock = live_server
        sse_body = build_openai_stream(
            ["Hello"], prompt_tokens=120, completion_tokens=30
        )
        _openai_mock(mock, sse_body)

        await proxy_stream(base_url)
        await asyncio.sleep(0.3)  # background create_task in server loop

        rows = fetch_rows(db_path)
        assert len(rows) == 1
        assert rows[0]["input_tokens"] == 120
        assert rows[0]["output_tokens"] == 30

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_cost_usd_non_zero(self, live_server):
        base_url, db_path, mock = live_server
        sse_body = build_openai_stream(
            ["Hi"], prompt_tokens=1000, completion_tokens=500
        )
        _openai_mock(mock, sse_body)

        await proxy_stream(base_url)
        await asyncio.sleep(0.3)

        rows = fetch_rows(db_path)
        assert rows[0]["cost_usd"] > 0.0

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_tags_in_db_row(self, live_server):
        base_url, db_path, mock = live_server
        sse_body = build_openai_stream(["Hi"])
        _openai_mock(mock, sse_body)

        await proxy_stream(base_url, tag_feature="search", tag_team="infra")
        await asyncio.sleep(0.3)

        rows = fetch_rows(db_path)
        assert rows[0]["tag_feature"] == "search"
        assert rows[0]["tag_team"] == "infra"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_burnlens_headers_not_forwarded_upstream(self, live_server):
        """BurnLens headers must be stripped before the upstream call."""
        base_url, db_path, mock = live_server
        captured = {}

        def upstream_handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            return httpx.Response(
                200,
                content=build_openai_stream(["Hi"]),
                headers={"content-type": "text/event-stream"},
            )

        mock.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=upstream_handler
        )
        await proxy_stream(base_url, tag_feature="chat", tag_team="backend")

        for key in captured.get("headers", {}):
            assert not key.lower().startswith("x-burnlens-"), f"Leaked: {key}"


# ---------------------------------------------------------------------------
# 3. Concurrent streams — server-side task isolation
# ---------------------------------------------------------------------------

class TestConcurrentIntegration:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_10_concurrent_streams_all_logged(self, live_server):
        base_url, db_path, mock = live_server
        sse_body = build_openai_stream(["Hi"], prompt_tokens=50, completion_tokens=10)

        # Register the same mock response for all 10 calls (side_effect=repeat)
        mock.post("https://api.openai.com/v1/chat/completions").return_value = httpx.Response(
            200, content=sse_body,
            headers={"content-type": "text/event-stream"},
        )

        await asyncio.gather(*[
            proxy_stream(base_url, tag_feature=f"f{i}") for i in range(10)
        ])
        await asyncio.sleep(0.5)

        rows = fetch_rows(db_path)
        assert len(rows) == 10
        features = {r["tag_feature"] for r in rows}
        assert features == {f"f{i}" for i in range(10)}

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_concurrent_rows_have_independent_costs(self, live_server):
        base_url, db_path, mock = live_server

        cheap_body = build_openai_stream(["x"], prompt_tokens=10, completion_tokens=5)
        expensive_body = build_openai_stream(["x"], prompt_tokens=100000, completion_tokens=50000)

        # Use a side_effect that returns different responses based on call order
        responses = iter([
            httpx.Response(200, content=cheap_body,
                           headers={"content-type": "text/event-stream"}),
            httpx.Response(200, content=expensive_body,
                           headers={"content-type": "text/event-stream"}),
        ])

        mock.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=lambda req: next(responses)
        )

        await asyncio.gather(
            proxy_stream(base_url, tag_feature="cheap"),
            proxy_stream(base_url, tag_feature="expensive"),
        )
        await asyncio.sleep(0.3)

        rows = fetch_rows(db_path)
        costs = sorted(r["cost_usd"] for r in rows)
        assert costs[1] > costs[0]


# ---------------------------------------------------------------------------
# 4. Large stream — 500 chunks, single DB row
# ---------------------------------------------------------------------------

class TestLargeStream:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_500_chunks_single_row(self, live_server):
        base_url, db_path, mock = live_server
        words = [f"w{i} " for i in range(500)]
        sse_body = build_openai_stream(
            words, prompt_tokens=200, completion_tokens=500
        )
        _openai_mock(mock, sse_body)

        await proxy_stream(base_url)
        await asyncio.sleep(0.3)

        rows = fetch_rows(db_path)
        assert len(rows) == 1
        assert rows[0]["output_tokens"] == 500

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_large_stream_completes_within_timeout(self, live_server):
        base_url, db_path, mock = live_server
        words = [f"word{i} " for i in range(500)]
        sse_body = build_openai_stream(words)
        _openai_mock(mock, sse_body)

        start = time.monotonic()
        await proxy_stream(base_url)
        elapsed = time.monotonic() - start

        assert elapsed < 10.0  # should never take 10s for a mock stream


# ---------------------------------------------------------------------------
# 5. Graceful shutdown — in-flight stream completes before exit
# ---------------------------------------------------------------------------

class TestGracefulShutdown:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_inflight_stream_row_written_before_shutdown(self, db_path):
        """
        Signal server shutdown while stream is in flight.
        The finally block + create_task must still fire and write the DB row.
        """
        import uvicorn
        from burnlens.server import create_app

        router = respx.MockRouter(assert_all_mocked=True)
        server_client = httpx.AsyncClient(
            transport=_RespxTransport(router),
            timeout=httpx.Timeout(300.0),
            follow_redirects=True,
        )

        app = create_app(db_path=db_path, http_client=server_client)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        config = uvicorn.Config(app, host="127.0.0.1", port=port,
                                log_level="error")
        server = uvicorn.Server(config)
        serve_task = asyncio.create_task(server.serve())

        for _ in range(100):
            await asyncio.sleep(0.05)
            if server.started:
                break

        sse_body = build_openai_stream(
            ["chunk"] * 5, prompt_tokens=100, completion_tokens=20
        )
        router.post("https://api.openai.com/v1/chat/completions").return_value = httpx.Response(
            200, content=sse_body,
            headers={"content-type": "text/event-stream"},
        )

        # Kick off stream and signal shutdown nearly simultaneously
        stream_coro = proxy_stream(f"http://127.0.0.1:{port}")
        stream_task = asyncio.create_task(stream_coro)

        await asyncio.sleep(0.02)
        server.should_exit = True

        await stream_task
        await serve_task
        await server_client.aclose()
        await asyncio.sleep(0.3)  # background tasks complete

        rows = fetch_rows(db_path)
        assert len(rows) == 1
