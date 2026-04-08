"""Tests for SQLite database layer."""
from __future__ import annotations

import pytest

from burnlens.storage.database import init_db, insert_request
from burnlens.storage.models import RequestRecord
from burnlens.storage.queries import get_recent_requests, get_total_cost, get_usage_by_model


@pytest.mark.asyncio
async def test_init_creates_tables(initialized_db: str):
    """init_db should be idempotent and create the requests table."""
    await init_db(initialized_db)  # second call should not fail


@pytest.mark.asyncio
async def test_insert_and_retrieve(initialized_db: str):
    record = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.00125,
        duration_ms=350,
    )
    row_id = await insert_request(initialized_db, record)
    assert row_id > 0

    rows = await get_recent_requests(initialized_db, limit=10)
    assert len(rows) == 1
    assert rows[0]["model"] == "gpt-4o"
    assert rows[0]["provider"] == "openai"


@pytest.mark.asyncio
async def test_total_cost(initialized_db: str):
    for cost in [0.01, 0.02, 0.03]:
        await insert_request(
            initialized_db,
            RequestRecord(provider="openai", model="gpt-4o", request_path="/v1/chat/completions",
                          cost_usd=cost),
        )
    total = await get_total_cost(initialized_db)
    assert abs(total - 0.06) < 1e-9


@pytest.mark.asyncio
async def test_usage_by_model(initialized_db: str):
    await insert_request(
        initialized_db,
        RequestRecord(provider="openai", model="gpt-4o", request_path="/v1/chat/completions",
                      input_tokens=100, output_tokens=50, cost_usd=0.01),
    )
    await insert_request(
        initialized_db,
        RequestRecord(provider="openai", model="gpt-4o", request_path="/v1/chat/completions",
                      input_tokens=200, output_tokens=80, cost_usd=0.02),
    )
    rows = await get_usage_by_model(initialized_db)
    assert len(rows) == 1
    assert rows[0].model == "gpt-4o"
    assert rows[0].request_count == 2
    assert rows[0].total_input_tokens == 300
    assert abs(rows[0].total_cost_usd - 0.03) < 1e-9


@pytest.mark.asyncio
async def test_tags_roundtrip(initialized_db: str):
    record = RequestRecord(
        provider="anthropic",
        model="claude-3-5-sonnet-20241022",
        request_path="/v1/messages",
        tags={"team": "ml", "env": "prod"},
    )
    await insert_request(initialized_db, record)
    rows = await get_recent_requests(initialized_db)
    assert rows[0]["tags"] == {"team": "ml", "env": "prod"}
