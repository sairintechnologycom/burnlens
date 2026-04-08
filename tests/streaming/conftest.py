"""
tests/streaming/conftest.py

Fixtures and SSE factories grounded in the real interceptor.py implementation.

Key facts from interceptor.py:
  - _stream_generator() yields ALL raw chunks to client (no filtering at yield)
  - should_buffer_chunk() gates what accumulates in usage_chunk_data list
  - _log_streaming_usage() fires in asyncio.create_task() AFTER stream finally block
  - duration captured in finally: duration_ref[0] = int((time.monotonic() - start_ms) * 1000)
  - _extract_tags() pulls x-burnlens-tag-* into dict before forwarding
  - _clean_request_headers() strips _BURNLENS_HEADER_PREFIX + hop-by-hop headers
  - handle_request() returns (status, headers, body_or_None, stream_or_None)
"""

import asyncio
import json
import sqlite3
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from burnlens.storage.database import init_db


# ---------------------------------------------------------------------------
# SSE wire format factories — match what OpenAI actually sends
# ---------------------------------------------------------------------------

def sse_content_chunk(text: str, model: str = "gpt-4o-mini", finish: bool = False) -> bytes:
    payload = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [{
            "index": 0,
            "delta": {"content": text} if not finish else {},
            "finish_reason": "stop" if finish else None,
        }],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


def sse_usage_chunk(
    prompt: int,
    completion: int,
    model: str = "gpt-4o-mini",
    reasoning: int = 0,
    cache_read: int = 0,
) -> bytes:
    """
    stream_options usage chunk — this is what should_buffer_chunk() targets.
    Has empty choices[] and top-level usage field.
    """
    payload = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "completion_tokens_details": {"reasoning_tokens": reasoning},
            "prompt_tokens_details": {"cached_tokens": cache_read},
        },
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


SSE_DONE = b"data: [DONE]\n\n"


def build_openai_stream(
    words: list[str],
    model: str = "gpt-4o-mini",
    prompt_tokens: int = 100,
    completion_tokens: int = 20,
    reasoning_tokens: int = 0,
    cache_read_tokens: int = 0,
    include_usage: bool = True,
) -> bytes:
    """Full OpenAI SSE body: content chunks + finish chunk + usage chunk + [DONE]."""
    parts = b""
    for word in words:
        parts += sse_content_chunk(word, model=model)
    parts += sse_content_chunk("", model=model, finish=True)
    if include_usage:
        parts += sse_usage_chunk(
            prompt_tokens, completion_tokens,
            model=model,
            reasoning=reasoning_tokens,
            cache_read=cache_read_tokens,
        )
    parts += SSE_DONE
    return parts


def build_anthropic_stream(
    text: str = "Hello world",
    model: str = "claude-3-5-sonnet-20241022",
    input_tokens: int = 80,
    output_tokens: int = 15,
) -> bytes:
    parts = []
    parts.append(
        b'event: message_start\ndata: ' +
        json.dumps({"type": "message_start", "message": {
            "id": "msg_test", "model": model,
            "usage": {"input_tokens": input_tokens, "output_tokens": 0},
        }}).encode() + b'\n\n'
    )
    for word in text.split():
        parts.append(
            b'event: content_block_delta\ndata: ' +
            json.dumps({"type": "content_block_delta", "index": 0,
                        "delta": {"type": "text_delta", "text": word + " "}}).encode() + b'\n\n'
        )
    parts.append(
        b'event: message_delta\ndata: ' +
        json.dumps({"type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"output_tokens": output_tokens}}).encode() + b'\n\n'
    )
    parts.append(b'event: message_stop\ndata: {"type":"message_stop"}\n\n')
    return b"".join(parts)


# ---------------------------------------------------------------------------
# Request factories — match handle_request() signature
# ---------------------------------------------------------------------------

def make_headers(
    provider: str = "openai",
    tag_feature: str = "chat",
    tag_team: str = "backend",
    tag_customer: str | None = None,
    extra: dict | None = None,
) -> dict[str, str]:
    base = {
        "content-type": "application/json",
        "x-burnlens-tag-feature": tag_feature,
        "x-burnlens-tag-team": tag_team,
    }
    if provider == "openai":
        base["authorization"] = "Bearer sk-test"
    elif provider == "anthropic":
        base["x-api-key"] = "sk-ant-test"
        base["anthropic-version"] = "2023-06-01"
    if tag_customer:
        base["x-burnlens-tag-customer"] = tag_customer
    if extra:
        base.update(extra)
    return base


def make_body(
    model: str = "gpt-4o-mini",
    stream: bool = True,
    include_usage_option: bool = True,
) -> bytes:
    body: dict = {
        "model": model,
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": stream,
    }
    if stream and include_usage_option:
        body["stream_options"] = {"include_usage": True}
    return json.dumps(body).encode()


# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    asyncio.run(init_db(path))
    return path


@pytest.fixture
def db_conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def fetch_rows(db_path: str) -> list[dict]:
    """Read all request rows and flatten the tags JSON into top-level keys."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM requests ORDER BY id"
    ).fetchall()]
    conn.close()
    for row in rows:
        tags: dict = json.loads(row.get("tags") or "{}")
        row["tag_feature"] = tags.get("feature")
        row["tag_team"] = tags.get("team")
        row["tag_customer"] = tags.get("customer")
    return rows


# ---------------------------------------------------------------------------
# httpx.AsyncClient factory with capturable mock transport
# ---------------------------------------------------------------------------

class CapturingTransport(httpx.MockTransport):
    """MockTransport that records what was forwarded upstream."""
    def __init__(self, handler):
        super().__init__(handler)
        self.captured_requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.captured_requests.append(request)
        return super().handle_request(request)


def make_client(
    words: list[str] = None,
    prompt_tokens: int = 100,
    completion_tokens: int = 20,
    model: str = "gpt-4o-mini",
    status: int = 200,
    base_url: str = "https://api.openai.com",
    capture: bool = False,
) -> tuple[httpx.AsyncClient, CapturingTransport | None]:
    """
    Build an httpx.AsyncClient with mock SSE transport.
    Returns (client, transport_or_None).
    """
    body = build_openai_stream(
        words or ["Hello", " world"],
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )

    def handler(req: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, json={"error": {"type": "api_error"}})
        return httpx.Response(200, content=body,
                              headers={"content-type": "text/event-stream"})

    transport = CapturingTransport(handler) if capture else httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url=base_url, timeout=10.0)
    return client, (transport if capture else None)


# ---------------------------------------------------------------------------
# Stream drain helpers — critical for fire-and-forget timing
# ---------------------------------------------------------------------------

async def drain(stream: AsyncIterator[bytes]) -> list[bytes]:
    """Drain an async stream, return all chunks."""
    return [chunk async for chunk in stream]


async def drain_and_settle(stream: AsyncIterator[bytes], settle: float = 0.15) -> list[bytes]:
    """
    Drain stream then sleep to let asyncio.create_task() background tasks flush.
    The interceptor fires _log_streaming_usage via create_task() in the finally
    block — we need the event loop to run before asserting DB state.
    """
    chunks = await drain(stream)
    await asyncio.sleep(settle)
    return chunks
