"""CODE-2: interceptor resolves API-key label and stamps it on the row."""
from __future__ import annotations

import asyncio
import json

import aiosqlite
import httpx
import pytest

from burnlens.keys import register_key
from burnlens.proxy.interceptor import _extract_api_key_hash, handle_request
from burnlens.proxy.providers import get_provider_for_path


# ---------------------------------------------------------------------------
# Reuse the fixtures from test_proxy.py via plain copies (kept tiny).
# ---------------------------------------------------------------------------


class _MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, payload: dict) -> None:
        self.captured: httpx.Request | None = None
        self._payload = payload

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.captured = request
        return httpx.Response(
            status_code=200,
            content=json.dumps(self._payload).encode(),
            headers={"content-type": "application/json"},
        )


def _openai_payload() -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "gpt-4o",
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


async def _flush() -> None:
    for _ in range(10):
        await asyncio.sleep(0.02)


# ---------------------------------------------------------------------------
# _extract_api_key_hash header coverage
# ---------------------------------------------------------------------------


def test_extract_api_key_hash_handles_x_goog_api_key() -> None:
    """Google SDK uses x-goog-api-key — must be hashed too."""
    digest = _extract_api_key_hash({"x-goog-api-key": "AIza-google-key"})
    assert digest is not None
    assert len(digest) == 64


def test_extract_api_key_hash_returns_none_when_no_auth() -> None:
    assert _extract_api_key_hash({"content-type": "application/json"}) is None


def test_extract_api_key_hash_prefers_authorization_over_x_api_key() -> None:
    digest = _extract_api_key_hash(
        {"authorization": "Bearer first", "x-api-key": "second"}
    )
    import hashlib
    assert digest == hashlib.sha256(b"first").hexdigest()


# ---------------------------------------------------------------------------
# handle_request → tag_key_label persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registered_key_stamps_label_on_request_row(
    initialized_db: str,
) -> None:
    raw_key = "sk-cursor-real-secret"
    await register_key(initialized_db, "cursor-main", "openai", raw_key)

    transport = _MockTransport(_openai_payload())
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
            "authorization": f"Bearer {raw_key}",
        },
        body_bytes=body,
        query_string="",
        db_path=initialized_db,
        alert_engine=None,
    )
    await _flush()

    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute(
            "SELECT tag_key_label FROM requests ORDER BY id DESC LIMIT 1"
        )
        (label,) = await cursor.fetchone()

    assert label == "cursor-main"


@pytest.mark.asyncio
async def test_unregistered_key_leaves_label_null(
    initialized_db: str,
) -> None:
    transport = _MockTransport(_openai_payload())
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
            "authorization": "Bearer sk-not-registered",
        },
        body_bytes=body,
        query_string="",
        db_path=initialized_db,
        alert_engine=None,
    )
    await _flush()

    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute(
            "SELECT tag_key_label FROM requests ORDER BY id DESC LIMIT 1"
        )
        (label,) = await cursor.fetchone()

    assert label is None


@pytest.mark.asyncio
async def test_registered_key_updates_last_used_at(
    initialized_db: str,
) -> None:
    raw_key = "sk-touch-test"
    await register_key(initialized_db, "touched", "openai", raw_key)

    transport = _MockTransport(_openai_payload())
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
            "authorization": f"Bearer {raw_key}",
        },
        body_bytes=body,
        query_string="",
        db_path=initialized_db,
        alert_engine=None,
    )
    await _flush()

    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute(
            "SELECT last_used_at FROM api_keys WHERE label = 'touched'"
        )
        (last_used,) = await cursor.fetchone()

    assert last_used is not None


@pytest.mark.asyncio
async def test_anthropic_x_api_key_resolves_label(
    initialized_db: str,
) -> None:
    raw_key = "sk-ant-anthropic-secret"
    await register_key(initialized_db, "claude-code-personal", "anthropic", raw_key)

    payload = {
        "id": "msg_x",
        "type": "message",
        "model": "claude-3-5-sonnet-20241022",
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 8, "output_tokens": 4},
    }
    transport = _MockTransport(payload)
    client = httpx.AsyncClient(transport=transport)
    provider = get_provider_for_path("/proxy/anthropic/v1/messages")

    body = json.dumps(
        {"model": "claude-3-5-sonnet-20241022", "messages": []}
    ).encode()
    await handle_request(
        client=client,
        provider=provider,
        path="/proxy/anthropic/v1/messages",
        method="POST",
        headers={
            "content-type": "application/json",
            "x-api-key": raw_key,
        },
        body_bytes=body,
        query_string="",
        db_path=initialized_db,
        alert_engine=None,
    )
    await _flush()

    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute(
            "SELECT tag_key_label FROM requests ORDER BY id DESC LIMIT 1"
        )
        (label,) = await cursor.fetchone()

    assert label == "claude-code-personal"


@pytest.mark.asyncio
async def test_request_with_no_auth_header_leaves_label_null(
    initialized_db: str,
) -> None:
    transport = _MockTransport(_openai_payload())
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
    await _flush()

    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute(
            "SELECT tag_key_label FROM requests ORDER BY id DESC LIMIT 1"
        )
        (label,) = await cursor.fetchone()

    assert label is None
