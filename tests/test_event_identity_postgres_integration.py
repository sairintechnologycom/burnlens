"""Opt-in real Postgres verification for the event-identity migration.

Run with ``BURNLENS_TEST_DATABASE_URL=postgresql://...``.  CI/local unit runs
skip it when no isolated Postgres service has been provisioned.
"""
from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import asyncpg
import pytest


DATABASE_URL = os.getenv("BURNLENS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="BURNLENS_TEST_DATABASE_URL is not configured")


@pytest.mark.asyncio
async def test_event_identity_migration_is_repeatable_and_workspace_scoped():
    from burnlens_cloud import database
    from burnlens_cloud.ingest_identity import persist_event_records
    from burnlens_cloud.models import RequestRecordBase
    migration = __import__(
        "burnlens_cloud.migrations.versions.20260804_01_event_identity",
        fromlist=["upgrade_postgres"],
    )

    schema = f"event_identity_{uuid4().hex}"
    admin = await asyncpg.connect(DATABASE_URL)
    pool = None
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        await admin.execute(f'SET search_path TO "{schema}"')
        await admin.execute("CREATE TABLE workspaces (id UUID PRIMARY KEY)")
        await admin.execute(
            """
            CREATE TABLE request_records (
                id BIGSERIAL PRIMARY KEY,
                workspace_id UUID NOT NULL REFERENCES workspaces(id),
                ts TIMESTAMPTZ NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
                input_tokens INT NOT NULL DEFAULT 0, output_tokens INT NOT NULL DEFAULT 0,
                reasoning_tokens INT NOT NULL DEFAULT 0, cache_read_tokens INT NOT NULL DEFAULT 0,
                cache_write_tokens INT NOT NULL DEFAULT 0, cost_usd NUMERIC(12, 8) NOT NULL,
                duration_ms INT NOT NULL DEFAULT 0, status_code INT NOT NULL DEFAULT 200,
                tags JSONB NOT NULL DEFAULT '{}', system_prompt_hash TEXT,
                received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), cache_hit INT NOT NULL DEFAULT 0,
                cache_saved_usd NUMERIC(12, 8) NOT NULL DEFAULT 0
            )
            """
        )
        # A populated legacy schema has no source_event_id, then migration adds it.
        ws_a, ws_b = uuid4(), uuid4()
        await admin.execute("INSERT INTO workspaces (id) VALUES ($1), ($2)", ws_a, ws_b)
        await migration.upgrade_postgres(admin)
        await migration.upgrade_postgres(admin)
        operations = __import__(
            "burnlens_cloud.migrations.versions.20260804_02_event_identity_operations",
            fromlist=["upgrade_postgres"],
        )
        await operations.upgrade_postgres(admin)
        await operations.upgrade_postgres(admin)

        pool = await asyncpg.create_pool(DATABASE_URL, server_settings={"search_path": schema})
        database.pool = pool
        record = RequestRecordBase(
            timestamp="2026-08-04T10:30:00Z", provider="openai", model="gpt-4o",
            input_tokens=100, output_tokens=50, cost_usd=0.002, duration_ms=10,
            event_id="same-external-id",
        )
        first = await persist_event_records(str(ws_a), [record], queue_for_streaming=False)
        replay = await persist_event_records(str(ws_a), [record], queue_for_streaming=False)
        conflict = record.model_copy(update={"cost_usd": 9.99})
        conflicting = await persist_event_records(str(ws_a), [conflict], queue_for_streaming=False)
        other_workspace = await persist_event_records(str(ws_b), [record], queue_for_streaming=False)

        assert len(first.inserted_records) == 1
        assert replay.duplicate_count == 1
        assert conflicting.conflict_count == 1
        assert len(other_workspace.inserted_records) == 1
        count = await admin.fetchval("SELECT COUNT(*) FROM request_records")
        assert count == 2
    finally:
        database.pool = None
        if pool:
            await pool.close()
        await admin.execute("RESET search_path")
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.close()
