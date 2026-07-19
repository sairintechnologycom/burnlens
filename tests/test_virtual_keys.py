"""Virtual key gateway: issuance/resolution + proxy enforcement & key swap."""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from burnlens import virtual_keys as vk
from burnlens.config import BurnLensConfig, RetryConfig
from burnlens.proxy.interceptor import handle_request
from burnlens.providers.openai import openai_provider
from burnlens.storage.database import init_db

_URL = "https://api.openai.com/v1/chat/completions"
_OK = {
    "id": "chatcmpl-1",
    "model": "gpt-4o",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
}


def _body(model: str = "gpt-4o") -> bytes:
    return json.dumps({"model": model, "messages": [{"role": "user", "content": "hi"}]}).encode()


async def _call(client, db_path, token, body=None):
    return await handle_request(
        client=client,
        provider=openai_provider,
        path="/proxy/openai/v1/chat/completions",
        method="POST",
        headers={"authorization": f"Bearer {token}", "content-type": "application/json"},
        body_bytes=body if body is not None else _body(),
        query_string="",
        db_path=db_path,
        config=BurnLensConfig(db_path=db_path, retry=RetryConfig(enabled=False)),
    )


# --------------------------------------------------------------- module unit


@pytest.mark.asyncio
async def test_issue_resolve_revoke(tmp_path):
    db = str(tmp_path / "vk.db")
    await init_db(db)
    raw, prefix = await vk.issue_key(db, "k1", "team-a", "openai", "OPENAI_API_KEY",
                                     allowed_models=["gpt-4o"], monthly_budget_usd=100.0)
    assert raw.startswith(vk.VIRTUAL_PREFIX)
    got = await vk.resolve(db, vk.hash_token(raw))
    assert got and got.team == "team-a" and got.allowed_models == ["gpt-4o"]
    assert await vk.revoke_key(db, "k1") is True
    assert await vk.resolve(db, vk.hash_token(raw)) is None  # revoked


@pytest.mark.asyncio
async def test_duplicate_label_rejected(tmp_path):
    db = str(tmp_path / "vk.db")
    await init_db(db)
    await vk.issue_key(db, "dup", "t", "openai", "OPENAI_API_KEY")
    with pytest.raises(vk.VirtualKeyExists):
        await vk.issue_key(db, "dup", "t", "openai", "OPENAI_API_KEY")


# ------------------------------------------------------- proxy enforcement


@pytest.mark.asyncio
@respx.mock
async def test_swap_forwards_real_key_not_virtual(tmp_path, monkeypatch):
    """A valid virtual key is swapped for the real upstream key before forwarding."""
    db = str(tmp_path / "vk.db")
    await init_db(db)
    monkeypatch.setenv("MY_REAL_KEY", "sk-real-upstream")
    raw, _ = await vk.issue_key(db, "k", "team-a", "openai", "MY_REAL_KEY")
    route = respx.post(_URL).mock(return_value=httpx.Response(200, json=_OK))

    async with httpx.AsyncClient() as client:
        status, _, body, _ = await _call(client, db, raw)

    assert status == 200
    sent_auth = route.calls.last.request.headers["authorization"]
    assert sent_auth == "Bearer sk-real-upstream"
    assert raw not in sent_auth  # the bl-sk- token never leaves the proxy


@pytest.mark.asyncio
@respx.mock
async def test_model_not_allowed_returns_403(tmp_path, monkeypatch):
    db = str(tmp_path / "vk.db")
    await init_db(db)
    monkeypatch.setenv("MY_REAL_KEY", "sk-real")
    raw, _ = await vk.issue_key(db, "k", "team-a", "openai", "MY_REAL_KEY",
                                allowed_models=["gpt-4o-mini"])
    route = respx.post(_URL).mock(return_value=httpx.Response(200, json=_OK))

    async with httpx.AsyncClient() as client:
        status, _, body, _ = await _call(client, db, raw, body=_body("gpt-4o"))

    assert status == 403
    assert json.loads(body)["error"] == "model_not_allowed"
    assert route.call_count == 0  # never forwarded


@pytest.mark.asyncio
@respx.mock
async def test_missing_env_fails_closed(tmp_path):
    """If the referenced env var is unset, fail closed (503) — never forward."""
    db = str(tmp_path / "vk.db")
    await init_db(db)
    raw, _ = await vk.issue_key(db, "k", "team-a", "openai", "DEFINITELY_UNSET_ENV")
    route = respx.post(_URL).mock(return_value=httpx.Response(200, json=_OK))

    async with httpx.AsyncClient() as client:
        status, _, body, _ = await _call(client, db, raw)

    assert status == 503
    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_invalid_virtual_key_returns_401(tmp_path):
    db = str(tmp_path / "vk.db")
    await init_db(db)
    route = respx.post(_URL).mock(return_value=httpx.Response(200, json=_OK))

    async with httpx.AsyncClient() as client:
        status, _, body, _ = await _call(client, db, "bl-sk-does-not-exist")

    assert status == 401
    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_non_virtual_token_passes_through(tmp_path):
    """A normal provider key is forwarded unchanged (no swap)."""
    db = str(tmp_path / "vk.db")
    await init_db(db)
    route = respx.post(_URL).mock(return_value=httpx.Response(200, json=_OK))

    async with httpx.AsyncClient() as client:
        status, _, _, _ = await _call(client, db, "sk-client-own-key")

    assert status == 200
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-client-own-key"


@pytest.mark.asyncio
@respx.mock
async def test_team_budget_exceeded_returns_429(tmp_path, monkeypatch):
    """Once the team's month-to-date spend hits the budget, requests are blocked."""
    db = str(tmp_path / "vk.db")
    await init_db(db)
    monkeypatch.setenv("MY_REAL_KEY", "sk-real")
    # Budget below any nonzero request cost, so the first request's spend
    # (recorded under team-a) trips the cap for the second.
    raw, _ = await vk.issue_key(db, "k", "team-a", "openai", "MY_REAL_KEY",
                                monthly_budget_usd=1e-9)
    route = respx.post(_URL).mock(return_value=httpx.Response(200, json=_OK))

    async with httpx.AsyncClient() as client:
        # First request goes through and records spend under team-a.
        s1, _, _, _ = await _call(client, db, raw)
        assert s1 == 200
        # Let the async logging settle so the spend is visible.
        import asyncio
        for _ in range(10):
            await asyncio.sleep(0.05)
        # Second request is blocked by the (tiny) team budget.
        s2, _, body2, _ = await _call(client, db, raw)

    assert s2 == 429
    assert json.loads(body2)["error"] == "team_budget_exceeded"
