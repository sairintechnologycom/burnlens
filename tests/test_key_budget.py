"""CODE-2: per-API-key daily cap enforcement (slice 4)."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite
import httpx
import pytest

from burnlens.config import ApiKeyBudgetsConfig, KeyBudgetEntry
from burnlens.key_budget import (
    SpendCache,
    enforce_daily_cap,
    next_midnight_in_tz,
    resolve_timezone,
    spend_cache as global_spend_cache,
    today_window_utc,
)
from burnlens.keys import register_key
from burnlens.proxy.interceptor import handle_request
from burnlens.proxy.providers import get_provider_for_path
from burnlens.storage.database import (
    get_spend_by_key_label_today,
    insert_request,
)
from burnlens.storage.models import RequestRecord


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


class _MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.captured: httpx.Request | None = None
        self._payload = payload
        self._status = status

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.captured = request
        return httpx.Response(
            status_code=self._status,
            content=json.dumps(self._payload).encode(),
            headers={"content-type": "application/json"},
        )


def _openai_payload(input_tokens: int = 10, output_tokens: int = 5) -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "gpt-4o",
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens},
    }


async def _flush() -> None:
    for _ in range(10):
        await asyncio.sleep(0.02)


@pytest.fixture(autouse=True)
def _reset_global_cache() -> None:
    """Clear the module-level cache between tests."""
    global_spend_cache.clear()
    yield
    global_spend_cache.clear()


def _budgets_for(label: str, daily: float, tz: str = "UTC") -> ApiKeyBudgetsConfig:
    return ApiKeyBudgetsConfig(
        keys={label: KeyBudgetEntry(daily_usd=daily)},
        reset_timezone=tz,
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_resolve_timezone_invalid_falls_back_to_utc(caplog: Any) -> None:
    tz = resolve_timezone("Bogus/NotAZone")
    # Should still be a tzinfo we can use, and equivalent to UTC.
    now = datetime.now(timezone.utc)
    assert now.astimezone(tz).utcoffset() == timedelta(0)


def test_resolve_timezone_valid_iana() -> None:
    tz = resolve_timezone("Asia/Kolkata")
    # Asia/Kolkata is UTC+05:30, no DST.
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    local = now.astimezone(tz)
    assert local.utcoffset() == timedelta(hours=5, minutes=30)


def test_today_window_aligns_to_local_midnight() -> None:
    tz = resolve_timezone("Asia/Kolkata")
    # 2026-04-28 19:00 UTC == 2026-04-29 00:30 IST
    fake_now = datetime(2026, 4, 28, 19, 0, tzinfo=timezone.utc)
    start_utc, end_utc = today_window_utc(tz, now=fake_now)
    # Local midnight that day: 2026-04-29 00:00 IST → 2026-04-28 18:30 UTC
    assert start_utc == datetime(2026, 4, 28, 18, 30, tzinfo=timezone.utc)
    assert end_utc == start_utc + timedelta(days=1)


def test_next_midnight_returns_end_of_window() -> None:
    tz = resolve_timezone("UTC")
    now = datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)
    nm = next_midnight_in_tz(tz, now=now)
    assert nm == datetime(2026, 4, 29, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# get_spend_by_key_label_today
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spend_query_only_counts_today_in_tz(initialized_db: str) -> None:
    tz = resolve_timezone("UTC")
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=2)

    # One row from 2 days ago, one from now — only the recent row should count.
    await insert_request(
        initialized_db,
        RequestRecord(
            provider="openai",
            model="gpt-4o",
            request_path="/v1/chat",
            timestamp=yesterday,
            input_tokens=0,
            output_tokens=0,
            reasoning_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=0,
            cost_usd=10.0,
            duration_ms=0,
            status_code=200,
            tags={"key_label": "k"},
        ),
    )
    await insert_request(
        initialized_db,
        RequestRecord(
            provider="openai",
            model="gpt-4o",
            request_path="/v1/chat",
            timestamp=now,
            input_tokens=0,
            output_tokens=0,
            reasoning_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=0,
            cost_usd=2.5,
            duration_ms=0,
            status_code=200,
            tags={"key_label": "k"},
        ),
    )

    spent = await get_spend_by_key_label_today(initialized_db, "k", tz)
    assert spent == pytest.approx(2.5)


@pytest.mark.asyncio
async def test_spend_query_returns_zero_for_unknown_label(initialized_db: str) -> None:
    tz = resolve_timezone("UTC")
    spent = await get_spend_by_key_label_today(initialized_db, "ghost", tz)
    assert spent == 0.0


# ---------------------------------------------------------------------------
# SpendCache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spend_cache_hits_db_once_within_ttl(initialized_db: str) -> None:
    """Within 30s the cache must reuse the cached value, not re-query."""
    tz = resolve_timezone("UTC")
    cache = SpendCache(ttl_seconds=30.0)

    await insert_request(
        initialized_db,
        RequestRecord(
            provider="openai",
            model="gpt-4o",
            request_path="/v1/chat",
            timestamp=datetime.now(timezone.utc),
            input_tokens=0, output_tokens=0, reasoning_tokens=0,
            cache_read_tokens=0, cache_write_tokens=0,
            cost_usd=1.0, duration_ms=0, status_code=200,
            tags={"key_label": "cached"},
        ),
    )

    first = await cache.get_today_spend("cached", initialized_db, tz)

    # Add another row — without invalidate, cache should still report old value
    await insert_request(
        initialized_db,
        RequestRecord(
            provider="openai",
            model="gpt-4o",
            request_path="/v1/chat",
            timestamp=datetime.now(timezone.utc),
            input_tokens=0, output_tokens=0, reasoning_tokens=0,
            cache_read_tokens=0, cache_write_tokens=0,
            cost_usd=99.0, duration_ms=0, status_code=200,
            tags={"key_label": "cached"},
        ),
    )

    second = await cache.get_today_spend("cached", initialized_db, tz)
    assert first == second == pytest.approx(1.0)

    cache.invalidate("cached")
    third = await cache.get_today_spend("cached", initialized_db, tz)
    assert third == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# enforce_daily_cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enforce_returns_none_for_unregistered_label(
    initialized_db: str,
) -> None:
    budgets = _budgets_for("registered", daily=1.0)
    assert await enforce_daily_cap(None, initialized_db, budgets) is None


@pytest.mark.asyncio
async def test_enforce_returns_none_when_cap_not_configured(
    initialized_db: str,
) -> None:
    budgets = ApiKeyBudgetsConfig()  # no caps anywhere
    assert await enforce_daily_cap("anything", initialized_db, budgets) is None


@pytest.mark.asyncio
async def test_enforce_blocks_at_or_above_cap(initialized_db: str) -> None:
    cache = SpendCache()
    budgets = _budgets_for("blocked", daily=0.10)

    await insert_request(
        initialized_db,
        RequestRecord(
            provider="openai",
            model="gpt-4o",
            request_path="/v1/chat",
            timestamp=datetime.now(timezone.utc),
            input_tokens=0, output_tokens=0, reasoning_tokens=0,
            cache_read_tokens=0, cache_write_tokens=0,
            cost_usd=0.10, duration_ms=0, status_code=200,
            tags={"key_label": "blocked"},
        ),
    )

    breach = await enforce_daily_cap("blocked", initialized_db, budgets, cache=cache)
    assert breach is not None
    spent, cap, resets_at = breach
    assert spent == pytest.approx(0.10)
    assert cap == pytest.approx(0.10)
    assert resets_at > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_default_cap_applies_when_label_lacks_override(
    initialized_db: str,
) -> None:
    budgets = ApiKeyBudgetsConfig(
        default=KeyBudgetEntry(daily_usd=0.05),
    )
    await insert_request(
        initialized_db,
        RequestRecord(
            provider="openai",
            model="gpt-4o",
            request_path="/v1/chat",
            timestamp=datetime.now(timezone.utc),
            input_tokens=0, output_tokens=0, reasoning_tokens=0,
            cache_read_tokens=0, cache_write_tokens=0,
            cost_usd=0.06, duration_ms=0, status_code=200,
            tags={"key_label": "fallback"},
        ),
    )
    breach = await enforce_daily_cap("fallback", initialized_db, budgets)
    assert breach is not None
    assert breach[1] == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# Interceptor end-to-end: 429 short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interceptor_returns_429_when_cap_exceeded(
    initialized_db: str,
) -> None:
    raw_key = "sk-blocked-test"
    label = "blocked-key"
    await register_key(initialized_db, label, "openai", raw_key)

    # Pre-load yesterday's-no, today's spend at the cap.
    await insert_request(
        initialized_db,
        RequestRecord(
            provider="openai",
            model="gpt-4o",
            request_path="/v1/chat",
            timestamp=datetime.now(timezone.utc),
            input_tokens=0, output_tokens=0, reasoning_tokens=0,
            cache_read_tokens=0, cache_write_tokens=0,
            cost_usd=5.00, duration_ms=0, status_code=200,
            tags={"key_label": label},
        ),
    )

    transport = _MockTransport(_openai_payload())
    client = httpx.AsyncClient(transport=transport)
    provider = get_provider_for_path("/proxy/openai/v1/chat/completions")
    body = json.dumps({"model": "gpt-4o", "messages": []}).encode()

    status, headers, body_out, stream = await handle_request(
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
        api_key_budgets=_budgets_for(label, daily=5.00),
    )

    assert status == 429
    assert stream is None
    assert transport.captured is None, "must NOT forward upstream"
    payload = json.loads(body_out)
    assert payload["error"] == "daily_budget_exceeded"
    assert payload["key"] == label
    assert payload["spent_today"] == pytest.approx(5.00)
    assert payload["daily_limit"] == pytest.approx(5.00)
    assert "resets_at" in payload


@pytest.mark.asyncio
async def test_interceptor_passes_when_under_cap(initialized_db: str) -> None:
    raw_key = "sk-allowed"
    label = "allowed-key"
    await register_key(initialized_db, label, "openai", raw_key)

    transport = _MockTransport(_openai_payload())
    client = httpx.AsyncClient(transport=transport)
    provider = get_provider_for_path("/proxy/openai/v1/chat/completions")
    body = json.dumps({"model": "gpt-4o", "messages": []}).encode()

    status, _, body_out, _ = await handle_request(
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
        api_key_budgets=_budgets_for(label, daily=100.00),
    )
    await _flush()

    assert status == 200
    assert transport.captured is not None


@pytest.mark.asyncio
async def test_interceptor_does_not_block_unregistered_keys(
    initialized_db: str,
) -> None:
    """Unregistered keys are always allowed through, even with strict caps set."""
    transport = _MockTransport(_openai_payload())
    client = httpx.AsyncClient(transport=transport)
    provider = get_provider_for_path("/proxy/openai/v1/chat/completions")
    body = json.dumps({"model": "gpt-4o", "messages": []}).encode()

    # Tight cap on a label that exists but isn't bound to this raw key.
    budgets = _budgets_for("someone-else", daily=0.001)

    status, _, _, _ = await handle_request(
        client=client,
        provider=provider,
        path="/proxy/openai/v1/chat/completions",
        method="POST",
        headers={
            "content-type": "application/json",
            "authorization": "Bearer sk-unregistered",
        },
        body_bytes=body,
        query_string="",
        db_path=initialized_db,
        api_key_budgets=budgets,
    )
    await _flush()
    assert status == 200


@pytest.mark.asyncio
async def test_successful_log_invalidates_cache(initialized_db: str) -> None:
    """After a request gets logged, the cached spend for that label is gone."""
    raw_key = "sk-cache-test"
    label = "cache-test"
    await register_key(initialized_db, label, "openai", raw_key)

    transport = _MockTransport(_openai_payload())
    client = httpx.AsyncClient(transport=transport)
    provider = get_provider_for_path("/proxy/openai/v1/chat/completions")
    body = json.dumps({"model": "gpt-4o", "messages": []}).encode()

    # Prime the cache with a non-blocking lookup.
    await global_spend_cache.get_today_spend(label, initialized_db, resolve_timezone("UTC"))
    assert label in global_spend_cache._data

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
        api_key_budgets=_budgets_for(label, daily=100.00),
    )
    await _flush()

    assert label not in global_spend_cache._data
