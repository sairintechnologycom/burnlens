"""Opt-in real PostgreSQL + Redpanda + ClickHouse event-identity certification.

Run only against an isolated topology:
  BURNLENS_CLOUD_TOPOLOGY=1 BURNLENS_TEST_DATABASE_URL=... pytest -q this_file
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import asyncpg
import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("BURNLENS_CLOUD_TOPOLOGY") != "1" or not os.getenv("BURNLENS_TEST_DATABASE_URL"),
    reason="isolated PostgreSQL, Redpanda, and ClickHouse topology is not configured",
)


async def _eventually(check, *, timeout: float = 45) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        if await check():
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("timed out waiting for ClickHouse Kafka consumer")
        await asyncio.sleep(0.5)


@pytest.mark.asyncio
async def test_real_cloud_topology_preserves_identity_and_financial_parity(monkeypatch):
    from burnlens_cloud import clickhouse, database, streaming
    from burnlens_cloud.config import settings
    from burnlens_cloud.ingest_identity import persist_event_records, flush_stream_outbox, stream_payload
    from burnlens_cloud.models import RequestRecordBase
    # This import form keeps the leading numeric migration module explicit.
    migration = __import__("burnlens_cloud.migrations.versions.20260804_01_event_identity", fromlist=["upgrade_postgres"])
    operations = __import__("burnlens_cloud.migrations.versions.20260804_02_event_identity_operations", fromlist=["upgrade_postgres"])
    db_url = os.environ["BURNLENS_TEST_DATABASE_URL"]
    monkeypatch.setattr(settings, "database_url", db_url)
    monkeypatch.setattr(settings, "streaming_enabled", True)
    monkeypatch.setattr(settings, "event_identity_enabled", True)
    monkeypatch.setattr(settings, "kafka_bootstrap_servers", os.getenv("BURNLENS_TEST_KAFKA", "127.0.0.1:19092"))
    monkeypatch.setattr(settings, "kafka_identity_topic", "burnlens-ingest-records-identity")
    monkeypatch.setattr(settings, "clickhouse_host", os.getenv("BURNLENS_TEST_CLICKHOUSE_HOST", "127.0.0.1"))
    monkeypatch.setattr(settings, "clickhouse_port", int(os.getenv("BURNLENS_TEST_CLICKHOUSE_PORT", "18123")))
    monkeypatch.setattr(settings, "clickhouse_user", os.getenv("BURNLENS_TEST_CLICKHOUSE_USER", "burnlens"))
    monkeypatch.setattr(settings, "clickhouse_password", os.getenv("BURNLENS_TEST_CLICKHOUSE_PASSWORD", "burnlens-cert"))
    await database.init_db()
    admin = await asyncpg.connect(db_url.replace("postgresql+asyncpg://", "postgresql://", 1))
    ws_a, ws_b, ws_legacy = uuid4(), uuid4(), uuid4()
    try:
        await migration.upgrade_postgres(admin)
        await operations.upgrade_postgres(admin)
        await admin.execute(
            "INSERT INTO workspaces (id, name, api_key_hash) VALUES ($1, $2, $3), ($4, $5, $6), ($7, $8, $9)",
            ws_a, "cert-a", f"cert-{ws_a}", ws_b, "cert-b", f"cert-{ws_b}",
            ws_legacy, "cert-legacy", f"cert-{ws_legacy}",
        )

        # ClickHouse is inside the Docker network; the real producer is outside it.
        monkeypatch.setattr(settings, "kafka_bootstrap_servers", "burnlens-cert-redpanda:29092")
        await clickhouse.init_clickhouse()
        migration.upgrade_clickhouse(clickhouse.get_clickhouse_client())
        monkeypatch.setattr(settings, "kafka_bootstrap_servers", os.getenv("BURNLENS_TEST_KAFKA", "127.0.0.1:19092"))
        now = datetime.now(timezone.utc).replace(microsecond=0)
        first = RequestRecordBase(timestamp=now, provider="openai", model="gpt-4o", input_tokens=10, output_tokens=5, cost_usd=0.01, duration_ms=20, event_id="cert-same")
        earlier = first.model_copy(update={"timestamp": now - timedelta(hours=1), "model": "gpt-4o-mini", "cost_usd": 0.02, "event_id": "cert-earlier"})
        conflict = first.model_copy(update={"cost_usd": 99.99})

        assert len((await persist_event_records(str(ws_a), [first, earlier], queue_for_streaming=True)).inserted_records) == 2
        assert (await persist_event_records(str(ws_a), [first], queue_for_streaming=True)).duplicate_count == 1
        assert (await persist_event_records(str(ws_a), [conflict], queue_for_streaming=True)).conflict_count == 1
        assert len((await persist_event_records(str(ws_b), [first], queue_for_streaming=True)).inserted_records) == 1
        await flush_stream_outbox(str(ws_a))
        await flush_stream_outbox(str(ws_b))
        # Real duplicate broker delivery, plus two legacy append-only records.
        await streaming.send_records_to_stream(str(ws_a), [stream_payload(first)], topic=settings.kafka_identity_topic)
        legacy = stream_payload(first)
        legacy["source_event_id"] = None
        await streaming.send_records_to_stream(str(ws_legacy), [legacy, legacy])

        async def _consumer_received() -> bool:
            value = clickhouse.get_clickhouse_client().query(
                "SELECT count() FROM request_records_raw WHERE workspace_id = {ws:UUID}", {"ws": str(ws_a)}
            ).result_rows[0][0]
            return value >= 3

        await _eventually(_consumer_received)
        start = (now - timedelta(days=1)).date().isoformat()
        end = (now + timedelta(days=1)).date().isoformat()
        summary_a = await clickhouse.get_spend_summary(str(ws_a), start, end)
        summary_b = await clickhouse.get_spend_summary(str(ws_b), start, end)
        summary_legacy = await clickhouse.get_spend_summary(str(ws_legacy), start, end)
        pg_a = await admin.fetchrow(
            "SELECT count(*) AS count, sum(cost_usd) AS cost FROM request_records WHERE workspace_id = $1", ws_a
        )
        pg_b = await admin.fetchrow(
            "SELECT count(*) AS count, sum(cost_usd) AS cost FROM request_records WHERE workspace_id = $1", ws_b
        )
        assert summary_a["total_requests"] == 2
        assert summary_a["total_cost_usd"] == pytest.approx(0.03)
        assert int(pg_a["count"]) == 2 and float(pg_a["cost"]) == pytest.approx(0.03)
        assert summary_b["total_requests"] == 1 and summary_b["total_cost_usd"] == pytest.approx(0.01)
        assert int(pg_b["count"]) == 1 and float(pg_b["cost"]) == pytest.approx(0.01)
        assert summary_legacy["total_requests"] == 2 and summary_legacy["total_cost_usd"] == pytest.approx(0.02)
        conflict_count = await admin.fetchval("SELECT conflict_count FROM ingest_event_identities WHERE workspace_id = $1 AND source_event_id = 'cert-same'", ws_a)
        assert conflict_count == 1
    finally:
        await streaming.close_streaming_producer()
        await clickhouse.close_clickhouse()
        ids = [ws_a, ws_b, ws_legacy]
        await admin.execute("DELETE FROM stream_ingest_outbox WHERE workspace_id = ANY($1::uuid[])", ids)
        await admin.execute("DELETE FROM ingest_event_identities WHERE workspace_id = ANY($1::uuid[])", ids)
        await admin.execute("DELETE FROM request_records WHERE workspace_id = ANY($1::uuid[])", ids)
        await admin.execute("DELETE FROM workspaces WHERE id = ANY($1::uuid[])", ids)
        await admin.close()
        await database.close_db()
