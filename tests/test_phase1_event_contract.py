"""Tests for Phase 1: Canonical Event Contract & Attribution Model."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import httpx
import pytest

from burnlens.cost.pricing import get_pricing_version
from burnlens.git_context import read_git_context
from burnlens.proxy.interceptor import (
    _extract_trace_id,
    _resolve_canonical_metadata,
    _extract_request_id,
    _extract_request_id_from_chunks,
    handle_request,
)
from burnlens.storage.database import (
    init_db,
    insert_request,
    migrate_add_canonical_event_fields,
)
from burnlens.storage.models import (
    GenAICostEvent,
    RequestRecord,
    TokenUsageEvent,
)


def test_event_dataclasses():
    """Verify that the TokenUsageEvent and GenAICostEvent dataclasses can be instantiated."""
    usage = TokenUsageEvent(
        input_tokens=10,
        output_tokens=20,
        reasoning_tokens=5,
        cache_read_tokens=2,
        cache_write_tokens=3,
    )
    assert usage.input_tokens == 10
    assert usage.output_tokens == 20
    assert usage.reasoning_tokens == 5
    assert usage.cache_read_tokens == 2
    assert usage.cache_write_tokens == 3

    evt = GenAICostEvent(
        event_id="evt-123",
        request_id="req-456",
        trace_id="trace-789",
        workspace_id="ws-abc",
        org_id="org-def",
        team="billing",
        feature="summarizer",
        customer_hash="cust-hash",
        app_id="app-1",
        env="production",
        repo="burnlens",
        branch="main",
        commit_sha="hash123",
        timestamp=datetime.now(timezone.utc),
        provider="openai",
        model="gpt-4o",
        usage=usage,
        cost_usd=0.05,
        duration_ms=450.0,
        status_code=200,
        pricing_version="2025-01-01",
    )
    assert evt.event_id == "evt-123"
    assert evt.usage.input_tokens == 10
    assert evt.pricing_version == "2025-01-01"


def test_request_record_mapping():
    """Test to_event and from_event mapping logic on RequestRecord."""
    record = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        timestamp=datetime.now(timezone.utc),
        input_tokens=100,
        output_tokens=200,
        reasoning_tokens=50,
        cache_read_tokens=10,
        cache_write_tokens=20,
        cost_usd=0.003,
        duration_ms=500.0,
        status_code=200,
        tags={"customer": "acme-corp", "team": "devs"},
        event_id="event-uuid",
        trace_id="trace-id-123",
        workspace_id="ws-id-456",
        org_id="org-id-789",
        pricing_version="2025-01-01",
    )

    event = record.to_event()
    assert isinstance(event, GenAICostEvent)
    assert event.event_id == "event-uuid"
    assert event.trace_id == "trace-id-123"
    assert event.workspace_id == "ws-id-456"
    assert event.org_id == "org-id-789"
    assert event.team == "devs"
    assert event.pricing_version == "2025-01-01"
    
    # Verify customer hash is generated deterministically
    expected_hash = hashlib.sha256(b"acme-corp").hexdigest()
    assert event.customer_hash == expected_hash

    # Verify converting back
    record2 = RequestRecord.from_event(event)
    assert record2.provider == "openai"
    assert record2.model == "gpt-4o"
    assert record2.input_tokens == 100
    assert record2.event_id == "event-uuid"
    assert record2.trace_id == "trace-id-123"
    assert record2.customer_hash == expected_hash
    assert record2.pricing_version == "2025-01-01"


def test_pricing_version():
    """Verify get_pricing_version successfully retrieves versions from files."""
    assert get_pricing_version("openai") == "2025-01-01"
    assert get_pricing_version("anthropic") == "2026-05-03"
    assert get_pricing_version("google") == "2025-01-01"
    assert get_pricing_version("nonexistent") is None


def test_git_context_commit_sha():
    """Verify that read_git_context extracts commit SHA."""
    mock_run = MagicMock()
    # Mock show-toplevel, HEAD branch, user email, rev-parse HEAD
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="/Users/bhushan/Documents/Projects/burnlens"),
        MagicMock(returncode=0, stdout="main"),
        MagicMock(returncode=0, stdout="test@example.com"),
        MagicMock(returncode=0, stdout="abcdef0123456789abcdef0123456789abcdef01"),
    ]

    with patch("subprocess.run", mock_run):
        ctx = read_git_context(os.getcwd())
        assert ctx["repo"] == "burnlens"
        assert ctx["branch"] == "main"
        assert ctx["dev"] == "test@example.com"
        assert ctx["commit_sha"] == "abcdef0123456789abcdef0123456789abcdef01"


def test_trace_id_extraction():
    """Test standard and fallback trace ID extraction."""
    # OTel traceparent
    headers = {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
    assert _extract_trace_id(headers, {}) == "4bf92f3577b34da6a3ce929d0e0e4736"

    # Fallback header
    headers = {"x-trace-id": "trace-uuid-123"}
    assert _extract_trace_id(headers, {}) == "trace-uuid-123"

    # Fallback tag
    assert _extract_trace_id({}, {"trace_id": "tag-trace-456"}) == "tag-trace-456"
    assert _extract_trace_id({}, {"trace-id": "tag-trace-456"}) is None  # standard tags format uses underscores


def test_resolve_canonical_metadata():
    """Verify resolve_canonical_metadata resolves fields from headers, tags, or env."""
    headers = {
        "x-burnlens-workspace-id": "ws-123",
        "x-burnlens-org-id": "org-456",
        "x-burnlens-app-id": "app-789",
        "x-burnlens-env": "staging",
        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    }
    tags = {
        "team": "security",
        "feature": "detection",
        "customer": "acme",
    }
    
    meta = _resolve_canonical_metadata(headers, tags)
    assert meta["workspace_id"] == "ws-123"
    assert meta["org_id"] == "org-456"
    assert meta["app_id"] == "app-789"
    assert meta["env"] == "staging"
    assert meta["team"] == "security"
    assert meta["feature"] == "detection"
    assert meta["customer_hash"] == hashlib.sha256(b"acme").hexdigest()
    assert meta["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_request_id_extraction():
    """Verify extraction of request_id from headers or response body."""
    # Body id
    body = b'{"id": "chatcmpl-12345", "model": "gpt-4o"}'
    assert _extract_request_id("openai", {"x-request-id": "hdr-id-999"}, body) == "chatcmpl-12345"

    # Header id
    assert _extract_request_id("openai", {"x-request-id": "hdr-id-999"}, None) == "hdr-id-999"
    assert _extract_request_id("openai", {"request-id": "hdr-id-888"}, None) == "hdr-id-888"

    # From SSE chunks
    chunks = [
        "data: {\"id\": \"chatcmpl-stream-1\", \"object\": \"chat.completion.chunk\"}\n\n",
        "data: [DONE]\n\n"
    ]
    assert _extract_request_id_from_chunks(chunks) == "chatcmpl-stream-1"


@pytest.mark.asyncio
async def test_database_migrations_and_insert(tmp_db):
    """Verify that columns are successfully migrated and can be written and read."""
    # 1. Initialize a legacy database with the old schema (including pre-Phase 1 migrations)
    async with aiosqlite.connect(tmp_db) as db:
        await db.execute(
            """
            CREATE TABLE requests (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp           TEXT    NOT NULL,
                provider            TEXT    NOT NULL,
                model               TEXT    NOT NULL,
                request_path        TEXT    NOT NULL DEFAULT '',
                input_tokens        INTEGER NOT NULL DEFAULT 0,
                output_tokens       INTEGER NOT NULL DEFAULT 0,
                reasoning_tokens    INTEGER NOT NULL DEFAULT 0,
                cache_read_tokens   INTEGER NOT NULL DEFAULT 0,
                cache_write_tokens  INTEGER NOT NULL DEFAULT 0,
                cost_usd            REAL    NOT NULL DEFAULT 0.0,
                duration_ms         INTEGER NOT NULL DEFAULT 0,
                status_code         INTEGER NOT NULL DEFAULT 200,
                tags                TEXT    NOT NULL DEFAULT '{}',
                system_prompt_hash  TEXT,
                source              TEXT NOT NULL DEFAULT 'proxy',
                request_id          TEXT,
                routed_model        TEXT,
                downgrade_reason    TEXT,
                budget_remaining_usd REAL,
                budget_remaining_pct REAL,
                tag_repo            TEXT,
                tag_dev             TEXT,
                tag_pr              TEXT,
                tag_branch          TEXT,
                tag_key_label       TEXT
            )
            """
        )
        await db.commit()

    # 2. Run the migration
    await migrate_add_canonical_event_fields(tmp_db)

    # 3. Check schema columns
    async with aiosqlite.connect(tmp_db) as db:
        cursor = await db.execute("PRAGMA table_info(requests)")
        cols = {row[1] for row in await cursor.fetchall()}
        assert "event_id" in cols
        assert "trace_id" in cols
        assert "workspace_id" in cols
        assert "org_id" in cols
        assert "customer_hash" in cols
        assert "pricing_version" in cols

    # 4. Insert RequestRecord
    record = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1",
        timestamp=datetime.now(timezone.utc),
        event_id="evt-xxx",
        trace_id="trace-xxx",
        workspace_id="ws-xxx",
        org_id="org-xxx",
        customer_hash="cust-hash-xxx",
        pricing_version="2025-01-01",
    )
    row_id = await insert_request(tmp_db, record)
    assert row_id > 0

    # 5. Query and verify
    async with aiosqlite.connect(tmp_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM requests WHERE id = ?", (row_id,))
        row = dict(await cursor.fetchone())
        assert row["event_id"] == "evt-xxx"
        assert row["trace_id"] == "trace-xxx"
        assert row["workspace_id"] == "ws-xxx"
        assert row["org_id"] == "org-xxx"
        assert row["customer_hash"] == "cust-hash-xxx"
        assert row["pricing_version"] == "2025-01-01"


@pytest.mark.asyncio
async def test_proxy_integration_non_streaming(initialized_db):
    """End-to-end unit test: verify proxy handles request, extracts metadata, and inserts database fields."""
    from burnlens.providers.openai import OpenAIProvider
    from burnlens.alerts.engine import AlertEngine

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.headers = {"x-request-id": "openai-req-id-111"}
    mock_response.content = b'{"id": "chatcmpl-res-111", "usage": {"prompt_tokens": 10, "completion_tokens": 20}}'
    mock_response.json.return_value = json.loads(mock_response.content.decode())
    
    mock_client.request = AsyncMock(return_value=mock_response)

    headers = {
        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        "x-burnlens-workspace-id": "ws-test-999",
        "x-burnlens-org-id": "org-test-999",
        "x-burnlens-tag-customer": "customer-acme",
        "x-burnlens-tag-team": "qa",
    }
    body = b'{"model": "gpt-4o", "messages": [{"role": "user", "content": "hello"}]}'

    status_code, resp_headers, resp_body, _ = await handle_request(
        client=mock_client,
        provider=OpenAIProvider(),
        path="/proxy/openai/v1/chat/completions",
        method="POST",
        headers=headers,
        body_bytes=body,
        query_string="",
        db_path=initialized_db,
        alert_engine=None,
    )

    assert status_code == 200
    assert resp_body == mock_response.content

    # Yield to let background _log_record complete
    await asyncio.sleep(0.1)

    # Query DB and verify all fields were saved
    async with aiosqlite.connect(initialized_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM requests ORDER BY id DESC LIMIT 1")
        row = dict(await cursor.fetchone())
        
        assert row["provider"] == "openai"
        assert row["model"] == "gpt-4o"
        assert row["request_id"] == "chatcmpl-res-111"
        assert row["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert row["workspace_id"] == "ws-test-999"
        assert row["org_id"] == "org-test-999"
        assert row["team"] == "qa"
        assert row["customer_hash"] == hashlib.sha256(b"customer-acme").hexdigest()
        assert row["pricing_version"] == "2025-01-01"
        assert row["event_id"] is not None
