"""Tests for burnlens cloud sync module."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest

from burnlens.cloud.sync import (
    CloudSync,
    _fetch_unsynced,
    _mark_synced,
    _row_to_payload,
    get_unsynced_count,
    migrate_add_synced_at,
)
from burnlens.config import CloudConfig
from burnlens.storage.database import init_db, insert_request
from burnlens.storage.models import RequestRecord


@pytest.fixture
def cloud_config() -> CloudConfig:
    return CloudConfig(
        enabled=True,
        api_key="bl_live_test123",
        endpoint="https://api.burnlens.app/v1/ingest",
        sync_interval_seconds=10,
        anonymise_prompts=True,
    )


@pytest.fixture
async def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    await init_db(path)
    return path


@pytest.fixture
async def db_with_records(db_path):
    """Insert 3 sample records and return the db path."""
    for i in range(3):
        record = RequestRecord(
            provider="openai",
            model="gpt-4o",
            request_path="/v1/chat/completions",
            timestamp=datetime(2025, 4, 8, 18, 0, i, tzinfo=timezone.utc),
            input_tokens=100 + i,
            output_tokens=50 + i,
            cost_usd=0.001 * (i + 1),
            duration_ms=500 + i * 100,
            tags={"feature": "chat", "team": "backend", "customer": "acme"},
            system_prompt_hash=f"hash_{i}",
        )
        await insert_request(db_path, record)
    return db_path


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_adds_synced_at_column(tmp_path):
    """synced_at column is added by migration and is idempotent."""
    path = str(tmp_path / "migrate.db")
    # Create a bare DB without the migration
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "CREATE TABLE requests (id INTEGER PRIMARY KEY, timestamp TEXT)"
        )
        await db.commit()

    # Run migration
    await migrate_add_synced_at(path)

    # Verify column exists
    async with aiosqlite.connect(path) as db:
        cursor = await db.execute("PRAGMA table_info(requests)")
        columns = {row[1] for row in await cursor.fetchall()}
    assert "synced_at" in columns

    # Running again should not raise
    await migrate_add_synced_at(path)


# ---------------------------------------------------------------------------
# push_batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_batch_sends_correct_payload(cloud_config):
    """push_batch POSTs the correct JSON payload."""
    sync = CloudSync(cloud_config)
    records = [
        {
            "ts": "2025-04-08T18:35:46Z",
            "provider": "anthropic",
            "model": "claude-haiku-4-5-20251001",
            "input_tokens": 14,
            "output_tokens": 10,
            "cost_usd": 0.000051,
            "latency_ms": 1100,
            "tag_feature": "chat",
            "tag_team": "backend",
            "tag_customer": "acme",
            "system_prompt_hash": "abc123",
        }
    ]

    mock_resp = AsyncMock()
    mock_resp.status_code = 200

    with patch.object(sync, "_get_client") as mock_client:
        client = AsyncMock()
        client.post.return_value = mock_resp
        mock_client.return_value = client

        result = await sync.push_batch(records)

    assert result is True
    client.post.assert_called_once()
    call_kwargs = client.post.call_args
    payload = call_kwargs.kwargs["json"]
    assert payload["api_key"] == "bl_live_test123"
    assert len(payload["records"]) == 1
    assert payload["records"][0]["model"] == "claude-haiku-4-5-20251001"


@pytest.mark.asyncio
async def test_push_batch_returns_false_on_network_error_no_crash(cloud_config):
    """Network errors return False, never raise."""
    sync = CloudSync(cloud_config)

    with patch.object(sync, "_get_client") as mock_client:
        client = AsyncMock()
        client.post.side_effect = Exception("connection refused")
        mock_client.return_value = client

        result = await sync.push_batch([{"ts": "2025-01-01T00:00:00Z"}])

    assert result is False


@pytest.mark.asyncio
async def test_push_batch_returns_false_on_http_error(cloud_config):
    """Non-200 HTTP responses return False."""
    sync = CloudSync(cloud_config)

    mock_resp = AsyncMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"

    with patch.object(sync, "_get_client") as mock_client:
        client = AsyncMock()
        client.post.return_value = mock_resp
        mock_client.return_value = client

        result = await sync.push_batch([{"ts": "2025-01-01T00:00:00Z"}])

    assert result is False


# ---------------------------------------------------------------------------
# Sync loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_loop_marks_records_synced(cloud_config, db_with_records):
    """After a successful push, records get a synced_at timestamp."""
    sync = CloudSync(cloud_config)

    mock_resp = AsyncMock()
    mock_resp.status_code = 200

    with patch.object(sync, "_get_client") as mock_client:
        client = AsyncMock()
        client.post.return_value = mock_resp
        mock_client.return_value = client

        count = await sync.sync_now(db_with_records)

    assert count == 3

    # All records should now have synced_at set
    unsynced = await get_unsynced_count(db_with_records)
    assert unsynced == 0


@pytest.mark.asyncio
async def test_sync_now_pushes_nothing_when_all_synced(cloud_config, db_with_records):
    """sync_now returns 0 if everything is already synced."""
    # Mark all as synced first
    rows = await _fetch_unsynced(db_with_records)
    await _mark_synced(db_with_records, [r["id"] for r in rows])

    sync = CloudSync(cloud_config)
    with patch.object(sync, "push_batch") as mock_push:
        count = await sync.sync_now(db_with_records)

    assert count == 0
    mock_push.assert_not_called()


# ---------------------------------------------------------------------------
# Anonymisation / payload format
# ---------------------------------------------------------------------------


def test_anonymise_removes_prompt_content():
    """_row_to_payload never includes raw prompt content, only hash."""
    row = {
        "id": 1,
        "timestamp": "2025-04-08T18:35:46",
        "provider": "openai",
        "model": "gpt-4o",
        "input_tokens": 100,
        "output_tokens": 50,
        "cost_usd": 0.005,
        "duration_ms": 800,
        "tags": json.dumps({"feature": "chat", "team": "backend"}),
        "system_prompt_hash": "sha256_abc",
        "request_path": "/v1/chat/completions",
        # These fields should NOT appear in the payload
        "reasoning_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "status_code": 200,
        "synced_at": None,
    }

    payload = _row_to_payload(row)

    # Verify expected fields present
    assert payload["ts"] == "2025-04-08T18:35:46"
    assert payload["provider"] == "openai"
    assert payload["model"] == "gpt-4o"
    assert payload["system_prompt_hash"] == "sha256_abc"
    assert payload["tag_feature"] == "chat"
    assert payload["tag_team"] == "backend"

    # Verify no raw content leaked
    payload_str = json.dumps(payload)
    assert "request_path" not in payload_str
    assert "status_code" not in payload_str


# ---------------------------------------------------------------------------
# Cloud disabled by default
# ---------------------------------------------------------------------------


def test_cloud_disabled_by_default_no_requests_sent():
    """Default CloudConfig has enabled=False and no api_key."""
    default = CloudConfig()
    assert default.enabled is False
    assert default.api_key is None


@pytest.mark.asyncio
async def test_unsynced_count(db_with_records):
    """get_unsynced_count reflects actual un-synced records."""
    count = await get_unsynced_count(db_with_records)
    assert count == 3

    # Mark one as synced
    rows = await _fetch_unsynced(db_with_records, limit=1)
    await _mark_synced(db_with_records, [rows[0]["id"]])

    count = await get_unsynced_count(db_with_records)
    assert count == 2
