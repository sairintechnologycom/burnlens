"""Shared helpers and fixtures for tests/streaming/ unit tests.

Exported names used by test_streaming_unit.py:
    build_openai_stream, build_anthropic_stream,
    sse_content_chunk, sse_usage_chunk, SSE_DONE,
    make_headers, make_body, make_client,
    fetch_rows, drain, drain_and_settle
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from burnlens.proxy.providers import ProviderConfig
from burnlens.storage.database import init_db

# ---------------------------------------------------------------------------
# SSE constants
# ---------------------------------------------------------------------------

SSE_DONE: bytes = b"data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# SSE chunk builders
# ---------------------------------------------------------------------------

def sse_content_chunk(
    text: str,
    model: str = "gpt-4o-mini",
    finish: bool = False,
) -> bytes:
    """Return one OpenAI SSE content chunk."""
    data = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [{
            "index": 0,
            "delta": {} if finish else {"content": text},
            "finish_reason": "stop" if finish else None,
        }],
    }
    return f"data: {json.dumps(data)}\n\n".encode()


def sse_usage_chunk(
    prompt_tokens: int,
    completion_tokens: int,
    model: str = "gpt-4o-mini",
    reasoning_tokens: int = 0,
) -> bytes:
    """Return an OpenAI SSE usage-only chunk (the final usage chunk)."""
    usage: dict = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    if reasoning_tokens:
        usage["completion_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
    data = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [],
        "usage": usage,
    }
    return f"data: {json.dumps(data)}\n\n".encode()


def build_openai_stream(
    words: list[str],
    model: str = "gpt-4o-mini",
    prompt_tokens: int = 100,
    completion_tokens: int = 20,
    reasoning_tokens: int = 0,
) -> bytes:
    """Build a complete OpenAI SSE streaming response body."""
    body = b""
    for word in words:
        body += sse_content_chunk(word, model=model)
    body += sse_content_chunk("", model=model, finish=True)
    body += sse_usage_chunk(
        prompt_tokens, completion_tokens,
        model=model,
        reasoning_tokens=reasoning_tokens,
    )
    body += SSE_DONE
    return body


def build_anthropic_stream(
    text: str = "Hello",
    model: str = "claude-3-5-sonnet-20241022",
    input_tokens: int = 100,
    output_tokens: int = 20,
) -> bytes:
    """Build a complete Anthropic SSE streaming response body."""
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": model,
                "usage": {"input_tokens": input_tokens, "output_tokens": 1},
            },
        },
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": text}},
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": output_tokens},
        },
        {"type": "message_stop"},
    ]
    body = b""
    for event in events:
        event_type = event.get("type", "")
        body += f"event: {event_type}\n".encode()
        body += f"data: {json.dumps(event)}\n\n".encode()
    return body


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def make_headers(
    provider: str = "openai",
    tag_feature: str = "chat",
    tag_team: str = "backend",
    tag_customer: str | None = None,
) -> dict[str, str]:
    """Build a minimal request header dict with BurnLens tag headers."""
    headers: dict[str, str] = {
        "authorization": "Bearer sk-test",
        "content-type": "application/json",
        "x-burnlens-tag-feature": tag_feature,
        "x-burnlens-tag-team": tag_team,
    }
    if tag_customer:
        headers["x-burnlens-tag-customer"] = tag_customer
    if provider == "anthropic":
        headers["x-api-key"] = "sk-ant-test"
    return headers


def make_body(
    model: str = "gpt-4o-mini",
    stream: bool = True,
    messages: list | None = None,
) -> bytes:
    """Build a minimal chat completion request body."""
    if messages is None:
        messages = [{"role": "user", "content": "Hello"}]
    return json.dumps({"model": model, "stream": stream, "messages": messages}).encode()


def make_client(
    words: list[str] | None = None,
    prompt_tokens: int = 100,
    completion_tokens: int = 20,
    model: str = "gpt-4o-mini",
    status: int = 200,
    reasoning_tokens: int = 0,
) -> tuple[httpx.AsyncClient, bytes]:
    """Return an (AsyncClient with mock transport, raw response body) pair."""
    if words is None:
        words = ["Hello", " world"]

    body = build_openai_stream(
        words,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        reasoning_tokens=reasoning_tokens,
    )

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            content=body,
            headers={"content-type": "text/event-stream"},
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.openai.com",
    )
    return client, body


# ---------------------------------------------------------------------------
# DB inspection helpers
# ---------------------------------------------------------------------------

def fetch_rows(db_path: str) -> list[dict]:
    """Synchronously read all rows from `requests` and flatten tag JSON."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM requests ORDER BY id")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    for row in rows:
        tags: dict = json.loads(row.get("tags") or "{}")
        row["tag_feature"] = tags.get("feature")
        row["tag_team"] = tags.get("team")
        row["tag_customer"] = tags.get("customer")

    return rows


# ---------------------------------------------------------------------------
# Stream drain helpers
# ---------------------------------------------------------------------------

async def drain(stream: AsyncIterator[bytes]) -> list[bytes]:
    """Consume all chunks from an async generator."""
    return [chunk async for chunk in stream]


async def drain_and_settle(
    stream: AsyncIterator[bytes],
    settle_s: float = 0.15,
) -> list[bytes]:
    """Drain stream, then yield control so background tasks can flush."""
    chunks = await drain(stream)
    await asyncio.sleep(settle_s)
    return chunks


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_path(tmp_path: Path) -> str:  # type: ignore[override]
    """Fresh initialised SQLite database; yields its path."""
    path = str(tmp_path / "test.db")
    await init_db(path)
    return path


@pytest.fixture(autouse=True)
def _patch_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Add short-prefix providers (/openai, /anthropic) so test paths resolve.

    Production providers use /proxy/openai — tests use /openai for brevity.
    The shorter prefix is prepended so it matches first.
    """
    import burnlens.proxy.providers as pmod

    short_providers = [
        ProviderConfig(
            name="openai",
            proxy_prefix="/openai",
            upstream_base="https://api.openai.com",
            env_var="OPENAI_BASE_URL",
        ),
        ProviderConfig(
            name="anthropic",
            proxy_prefix="/anthropic",
            upstream_base="https://api.anthropic.com",
            env_var="ANTHROPIC_BASE_URL",
        ),
    ]
    monkeypatch.setattr(pmod, "DEFAULT_PROVIDERS", short_providers + pmod.DEFAULT_PROVIDERS)
