"""Tests for upstream retry on transient provider failures."""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from burnlens.config import BurnLensConfig, RetryConfig
from burnlens.proxy.interceptor import handle_request
from burnlens.providers.openai import openai_provider
from burnlens.storage.database import init_db

_URL = "https://api.openai.com/v1/chat/completions"
_BODY = json.dumps({"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}).encode()
_OK = {
    "id": "chatcmpl-1",
    "model": "gpt-4o",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
}


def _config(db_path: str, **retry) -> BurnLensConfig:
    # backoff_base_seconds=0 keeps the test fast.
    return BurnLensConfig(db_path=db_path, retry=RetryConfig(backoff_base_seconds=0.0, **retry))


async def _call(client, config, db_path):
    return await handle_request(
        client=client,
        provider=openai_provider,
        path="/proxy/openai/v1/chat/completions",
        method="POST",
        headers={"Authorization": "Bearer sk-x", "Content-Type": "application/json"},
        body_bytes=_BODY,
        query_string="",
        db_path=db_path,
        config=config,
    )


@pytest.mark.asyncio
@respx.mock
async def test_retries_then_succeeds(tmp_path):
    """A 503 followed by a 200 is retried and returns the success."""
    db_path = str(tmp_path / "r.db")
    await init_db(db_path)
    route = respx.post(_URL).mock(side_effect=[
        httpx.Response(503, text="overloaded"),
        httpx.Response(200, json=_OK),
    ])
    async with httpx.AsyncClient() as client:
        status, _, body, _ = await _call(client, _config(db_path), db_path)
    assert status == 200
    assert route.call_count == 2
    assert json.loads(body)["choices"][0]["message"]["content"] == "hello"


@pytest.mark.asyncio
@respx.mock
async def test_retries_exhausted_returns_last(tmp_path):
    """Persistent 503 exhausts max_retries and returns the final 503."""
    db_path = str(tmp_path / "r.db")
    await init_db(db_path)
    route = respx.post(_URL).mock(return_value=httpx.Response(503, text="down"))
    async with httpx.AsyncClient() as client:
        status, _, _, _ = await _call(client, _config(db_path, max_retries=2), db_path)
    assert status == 503
    assert route.call_count == 3  # 1 initial + 2 retries


@pytest.mark.asyncio
@respx.mock
async def test_non_retryable_status_not_retried(tmp_path):
    """A 400 is not in the retry set — forwarded immediately, no retry."""
    db_path = str(tmp_path / "r.db")
    await init_db(db_path)
    route = respx.post(_URL).mock(return_value=httpx.Response(400, json={"error": "bad"}))
    async with httpx.AsyncClient() as client:
        status, _, _, _ = await _call(client, _config(db_path), db_path)
    assert status == 400
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_retry_disabled(tmp_path):
    """With retry disabled, a 503 is returned on the first attempt."""
    db_path = str(tmp_path / "r.db")
    await init_db(db_path)
    route = respx.post(_URL).mock(return_value=httpx.Response(503))
    async with httpx.AsyncClient() as client:
        status, _, _, _ = await _call(client, _config(db_path, enabled=False), db_path)
    assert status == 503
    assert route.call_count == 1
