"""Cloud source-event identity contract tests (Workstream 0A)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/burnlens_test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests")
os.environ.setdefault("ENVIRONMENT", "test")

WS_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
WS_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _app():
    from burnlens_cloud.ingest import router

    app = FastAPI()
    app.include_router(router)
    return app


def _client():
    return AsyncClient(transport=ASGITransport(app=_app()), base_url="http://testserver")


def _record(event_id: str | None = None, *, cost: float = 0.002) -> dict:
    payload = {
        "timestamp": "2026-08-04T10:30:00Z",
        "provider": "openai",
        "model": "gpt-4o",
        "input_tokens": 100,
        "output_tokens": 50,
        "cost_usd": cost,
        "duration_ms": 500,
        "status_code": 200,
        "tags": {"feature": "chat"},
    }
    if event_id is not None:
        payload["event_id"] = event_id
    return payload


async def _workspace_query(_sql, *_args):
    return [{"otel_endpoint": None, "otel_api_key_encrypted": None, "otel_enabled": False}]


@pytest.mark.asyncio
async def test_existing_payload_without_event_id_keeps_response_contract(monkeypatch):
    from burnlens_cloud import ingest
    from burnlens_cloud.config import settings

    monkeypatch.setattr(settings, "event_identity_enabled", True)
    bulk = AsyncMock()
    with patch.object(ingest, "get_workspace_by_api_key", AsyncMock(return_value=(WS_A, "free"))), \
         patch.object(ingest, "_check_quota_or_raise", AsyncMock()), \
         patch.object(ingest, "execute_query", AsyncMock(side_effect=_workspace_query)), \
         patch.object(ingest, "execute_bulk_insert", bulk), \
         patch.object(ingest, "_record_usage_and_maybe_notify", AsyncMock()), \
         patch.object(ingest, "resolve_limits", AsyncMock(return_value=None)):
        async with _client() as client:
            response = await client.post("/v1/ingest", headers={"X-API-Key": "key"}, json={"records": [_record()]})

    assert response.status_code == 200
    assert response.json() == {"accepted": 1, "rejected": 0}
    assert bulk.await_count == 1


@pytest.mark.asyncio
async def test_event_id_persists_once_and_retry_is_idempotent(monkeypatch):
    from burnlens_cloud import ingest
    from burnlens_cloud.config import settings
    from burnlens_cloud.ingest_identity import ExistingEventClassification, PersistedEventRecords

    monkeypatch.setattr(settings, "event_identity_enabled", True)
    record = _record("evt-1")
    duplicate = ExistingEventClassification(new_records=[], duplicate_count=1, conflict_count=0)
    with patch.object(ingest, "get_workspace_by_api_key", AsyncMock(return_value=(WS_A, "free"))), \
         patch.object(ingest, "_check_quota_or_raise", AsyncMock()), \
         patch.object(ingest, "execute_query", AsyncMock(side_effect=_workspace_query)), \
         patch.object(ingest, "classify_existing_events", AsyncMock(side_effect=[ExistingEventClassification([object()], 0, 0), duplicate])), \
         patch.object(ingest, "persist_event_records", AsyncMock()) as persist, \
         patch.object(ingest, "_record_usage_and_maybe_notify", AsyncMock()), \
         patch.object(ingest, "resolve_limits", AsyncMock(return_value=None)):
        # Use real parsed records in the persist result so token accounting can run.
        from burnlens_cloud.models import RequestRecordBase
        parsed = RequestRecordBase(**record)
        persist.side_effect = [PersistedEventRecords([parsed], 0, 0), PersistedEventRecords([], 0, 0)]
        async with _client() as client:
            first = await client.post("/v1/ingest", headers={"X-API-Key": "key"}, json={"records": [record]})
            second = await client.post("/v1/ingest", headers={"X-API-Key": "key"}, json={"records": [record]})

    assert first.json()["accepted"] == 1
    assert second.json() == {"accepted": 0, "rejected": 0}
    assert persist.await_count == 2


@pytest.mark.asyncio
async def test_conflicting_duplicate_is_rejected_without_overwrite(monkeypatch):
    from burnlens_cloud import ingest
    from burnlens_cloud.config import settings
    from burnlens_cloud.ingest_identity import ExistingEventClassification, PersistedEventRecords

    monkeypatch.setattr(settings, "event_identity_enabled", True)
    conflict = ExistingEventClassification(new_records=[], duplicate_count=0, conflict_count=1)
    persist = AsyncMock(return_value=PersistedEventRecords([], 0, 0))
    with patch.object(ingest, "get_workspace_by_api_key", AsyncMock(return_value=(WS_A, "free"))), \
         patch.object(ingest, "execute_query", AsyncMock(side_effect=_workspace_query)), \
         patch.object(ingest, "classify_existing_events", AsyncMock(return_value=conflict)), \
         patch.object(ingest, "persist_event_records", persist), \
         patch.object(ingest, "resolve_limits", AsyncMock(return_value=None)):
        async with _client() as client:
            response = await client.post("/v1/ingest", headers={"X-API-Key": "key"}, json={"records": [_record("evt-1", cost=9.99)]})

    assert response.status_code == 200
    assert response.json() == {"accepted": 0, "rejected": 1}
    assert persist.await_count == 1


@pytest.mark.asyncio
async def test_identity_feature_disabled_preserves_old_ingest_path(monkeypatch):
    from burnlens_cloud import ingest
    from burnlens_cloud.config import settings

    monkeypatch.setattr(settings, "event_identity_enabled", False)
    bulk = AsyncMock()
    with patch.object(ingest, "get_workspace_by_api_key", AsyncMock(return_value=(WS_A, "free"))), \
         patch.object(ingest, "_check_quota_or_raise", AsyncMock()), \
         patch.object(ingest, "execute_query", AsyncMock(side_effect=_workspace_query)), \
         patch.object(ingest, "execute_bulk_insert", bulk), \
         patch.object(ingest, "_record_usage_and_maybe_notify", AsyncMock()), \
         patch.object(ingest, "resolve_limits", AsyncMock(return_value=None)):
        async with _client() as client:
            response = await client.post("/v1/ingest", headers={"X-API-Key": "key"}, json={"records": [_record("evt-legacy")]})

    assert response.json() == {"accepted": 1, "rejected": 0}
    assert bulk.await_count == 1


@pytest.mark.asyncio
async def test_retry_after_stream_timeout_reuses_identity_without_second_cost(monkeypatch):
    from burnlens_cloud import ingest
    from burnlens_cloud.config import settings
    from burnlens_cloud.ingest_identity import ExistingEventClassification, PersistedEventRecords
    from burnlens_cloud.models import RequestRecordBase

    monkeypatch.setattr(settings, "event_identity_enabled", True)
    monkeypatch.setattr(settings, "streaming_enabled", True)
    parsed = RequestRecordBase(**_record("evt-timeout"))
    classifications = [
        ExistingEventClassification([parsed], 0, 0),
        ExistingEventClassification([], 1, 0),
    ]
    persisted = [PersistedEventRecords([parsed], 0, 0), PersistedEventRecords([], 1, 0)]
    with patch.object(ingest, "get_workspace_by_api_key", AsyncMock(return_value=(WS_A, "free"))), \
         patch.object(ingest, "_check_quota_or_raise", AsyncMock()), \
         patch.object(ingest, "execute_query", AsyncMock(side_effect=_workspace_query)), \
         patch.object(ingest, "classify_existing_events", AsyncMock(side_effect=classifications)), \
         patch.object(ingest, "persist_event_records", AsyncMock(side_effect=persisted)) as persist, \
         patch.object(ingest, "flush_stream_outbox", AsyncMock(side_effect=[TimeoutError("broker timeout"), 1])) as flush, \
         patch.object(ingest, "_record_usage_and_maybe_notify", AsyncMock()), \
         patch.object(ingest, "resolve_limits", AsyncMock(return_value=None)):
        async with _client() as client:
            first = await client.post("/v1/ingest", headers={"X-API-Key": "key"}, json={"records": [_record("evt-timeout")]})
            second = await client.post("/v1/ingest", headers={"X-API-Key": "key"}, json={"records": [_record("evt-timeout")]})

    assert first.status_code == 500
    assert second.json() == {"accepted": 0, "rejected": 0}
    assert persist.await_count == 2
    assert flush.await_count == 2


def test_source_event_fingerprint_is_stable_and_detects_financial_conflicts():
    from burnlens_cloud.ingest_identity import payload_hash
    from burnlens_cloud.models import RequestRecordBase

    one = RequestRecordBase(**_record("evt-1"))
    same = RequestRecordBase(**_record("evt-1"))
    changed = RequestRecordBase(**_record("evt-1", cost=0.003))
    assert payload_hash(one) == payload_hash(same)
    assert payload_hash(one) != payload_hash(changed)


def test_stream_payload_preserves_source_event_id():
    from burnlens_cloud.ingest_identity import stream_payload
    from burnlens_cloud.models import RequestRecordBase

    payload = stream_payload(RequestRecordBase(**_record("evt-clickhouse")))
    assert payload["source_event_id"] == "evt-clickhouse"


def test_workspace_scoping_is_part_of_the_identity_contract():
    migration = __import__(
        "burnlens_cloud.migrations.versions.20260804_01_event_identity",
        fromlist=["upgrade_postgres"],
    )
    # The migration's primary key is the database-enforced proof that the same
    # source id is valid in two workspaces and cannot collide across them.
    source = migration.upgrade_postgres.__code__.co_consts
    assert any("PRIMARY KEY (workspace_id, source_event_id)" in value for value in source if isinstance(value, str))


def test_clickhouse_migration_preserves_source_event_id():
    migration = __import__(
        "burnlens_cloud.migrations.versions.20260804_01_event_identity",
        fromlist=["upgrade_clickhouse"],
    )
    commands: list[str] = []

    class Client:
        def command(self, sql):
            commands.append(sql)

    migration.upgrade_clickhouse(Client())
    assert any("request_records_raw ADD COLUMN IF NOT EXISTS source_event_id" in sql for sql in commands)
    assert any("request_records_identity_queue" in sql and "source_event_id" in sql for sql in commands)


@pytest.mark.asyncio
async def test_clickhouse_dashboard_query_deduplicates_source_event_identity(monkeypatch):
    from burnlens_cloud import clickhouse

    queries: list[str] = []

    class Result:
        result_rows = [(1, 100, 50, 0.002, 10.0)]

    class Client:
        def query(self, sql, _params):
            queries.append(sql)
            return Result()

    monkeypatch.setattr(clickhouse, "get_clickhouse_client", lambda: Client())
    summary = await clickhouse.get_spend_summary(WS_A, "2026-08-01", "2026-08-04")
    assert summary["total_cost_usd"] == 0.002
    assert "source_event_id" in queries[0]
    assert "__legacy__" in queries[0]
