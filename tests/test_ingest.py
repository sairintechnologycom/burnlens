"""Tests for ingest endpoint."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

import pytest


def _record(**overrides):
    base = {
        "ts": "2026-04-14T10:00:00Z",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "input_tokens": 100,
        "output_tokens": 50,
        "reasoning_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.000045,
        "latency_ms": 320,
        "tag_feature": "chat",
        "tag_team": "backend",
        "tag_customer": "acme",
        "system_prompt_hash": "abc123",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_ingest_valid_batch_accepted(client):
    ac, mock_conn = client
    ws_id = str(uuid4())

    with patch("api.ingest._lookup_workspace", new_callable=AsyncMock) as mock_lk:
        mock_lk.return_value = (ws_id, "cloud")
        mock_conn.executemany = AsyncMock()

        resp = await ac.post("/api/v1/ingest", json={
            "api_key": "bl_live_test",
            "records": [_record(), _record(), _record()],
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] == 3
    assert data["rejected"] == 0


@pytest.mark.asyncio
async def test_ingest_invalid_api_key_401(client):
    ac, mock_conn = client

    with patch("api.ingest._lookup_workspace", new_callable=AsyncMock) as mock_lk:
        mock_lk.return_value = None

        resp = await ac.post("/api/v1/ingest", json={
            "api_key": "bad_key",
            "records": [_record()],
        })

    assert resp.status_code == 401
    assert "invalid_api_key" in resp.text


@pytest.mark.asyncio
async def test_ingest_free_tier_limit_429(client):
    ac, mock_conn = client
    ws_id = str(uuid4())

    with patch("api.ingest._lookup_workspace", new_callable=AsyncMock) as mock_lk:
        mock_lk.return_value = (ws_id, "free")

        # Mock the pool for the free-tier count check
        inner_conn = AsyncMock()
        inner_conn.fetchval = AsyncMock(return_value=10001)

        mock_pool = MagicMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=inner_conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pool.acquire.return_value = ctx

        import api.database as db_mod
        original_pool = db_mod.pool
        db_mod.pool = mock_pool
        try:
            resp = await ac.post("/api/v1/ingest", json={
                "api_key": "bl_live_test",
                "records": [_record()],
            })
        finally:
            db_mod.pool = original_pool

    assert resp.status_code == 429
    assert "free_tier_limit" in resp.text


@pytest.mark.asyncio
async def test_ingest_empty_records_ok(client):
    ac, mock_conn = client

    with patch("api.ingest._lookup_workspace", new_callable=AsyncMock) as mock_lk:
        mock_lk.return_value = (str(uuid4()), "cloud")

        resp = await ac.post("/api/v1/ingest", json={
            "api_key": "bl_live_test",
            "records": [],
        })

    assert resp.status_code == 200
    assert resp.json() == {"accepted": 0, "rejected": 0}


@pytest.mark.asyncio
async def test_ingest_500_records_all_inserted(client):
    ac, mock_conn = client
    ws_id = str(uuid4())

    with patch("api.ingest._lookup_workspace", new_callable=AsyncMock) as mock_lk:
        mock_lk.return_value = (ws_id, "cloud")
        mock_conn.executemany = AsyncMock()

        records = [_record(cost_usd=0.0001 * i) for i in range(500)]
        resp = await ac.post("/api/v1/ingest", json={
            "api_key": "bl_live_test",
            "records": records,
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] == 500
    assert data["rejected"] == 0
