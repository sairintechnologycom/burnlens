"""Preserve cloud source-event identity without modifying existing meanings."""
from __future__ import annotations

from ...config import settings


async def upgrade_postgres(conn) -> None:
    await conn.execute(
        f"""
        ALTER TABLE request_records
            ADD COLUMN IF NOT EXISTS source_event_id TEXT,
            ADD COLUMN IF NOT EXISTS trace_id TEXT,
            ADD COLUMN IF NOT EXISTS provider_request_id TEXT
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ingest_event_identities (
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            source_event_id TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            request_record_id BIGINT REFERENCES request_records(id) ON DELETE SET NULL,
            first_received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (workspace_id, source_event_id)
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stream_ingest_outbox (
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            source_event_id TEXT NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            delivered_at TIMESTAMPTZ,
            attempts INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (workspace_id, source_event_id),
            FOREIGN KEY (workspace_id, source_event_id)
                REFERENCES ingest_event_identities(workspace_id, source_event_id)
                ON DELETE CASCADE
        )
        """
    )
    # Concurrent creation avoids a table-wide write lock on the hot cost table.
    duplicates = await conn.fetch(
        """
        SELECT workspace_id, source_event_id, COUNT(*) AS count
        FROM request_records
        WHERE source_event_id IS NOT NULL
        GROUP BY workspace_id, source_event_id
        HAVING COUNT(*) > 1
        LIMIT 20
        """
    )
    if duplicates:
        raise RuntimeError(
            "Cannot create unique source-event index; historical duplicates exist. "
            "Export and remediate them manually before retrying."
        )
    await conn.execute(
        """
        CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS
            idx_request_records_workspace_source_event
        ON request_records(workspace_id, source_event_id)
        WHERE source_event_id IS NOT NULL
        """
    )
    await conn.execute(
        """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stream_ingest_outbox_pending
        ON stream_ingest_outbox(workspace_id, created_at)
        WHERE delivered_at IS NULL
        """
    )


def upgrade_clickhouse(client) -> None:
    # Applied explicitly after Postgres. Kafka-engine tables cannot ALTER ADD
    # COLUMN, so identity traffic gets an additive queue/topic instead of
    # mutating the legacy queue consumed by older deployments.
    client.command("ALTER TABLE request_records_raw ADD COLUMN IF NOT EXISTS source_event_id String DEFAULT ''")
    client.command(
        f"""
        CREATE TABLE IF NOT EXISTS request_records_identity_queue (
            workspace_id UUID,
            ts String,
            provider String,
            model String,
            input_tokens UInt32,
            output_tokens UInt32,
            reasoning_tokens UInt32,
            cache_read_tokens UInt32,
            cache_write_tokens UInt32,
            cost_usd Decimal(18, 8),
            duration_ms UInt32,
            status_code UInt16,
            tag_feature String,
            tag_team String,
            tag_customer String,
            tag_key_label String,
            system_prompt_hash String,
            source_event_id String
        ) ENGINE = Kafka
        SETTINGS kafka_broker_list = '{settings.kafka_bootstrap_servers}',
                 kafka_topic_list = '{settings.kafka_identity_topic}',
                 kafka_group_name = 'clickhouse-identity-consumer',
                 kafka_format = 'JSONEachRow',
                 kafka_num_consumers = 1
        """
    )
    client.command(
        """
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_request_records_identity_consumer
        TO request_records_raw AS
        SELECT
            generateUUIDv4() AS id, workspace_id,
            parseDateTime64BestEffortOrZero(ts) AS ts, provider, model,
            input_tokens, output_tokens, reasoning_tokens, cache_read_tokens,
            cache_write_tokens, cost_usd, duration_ms, status_code,
            tag_feature, tag_team, tag_customer, tag_key_label,
            system_prompt_hash, source_event_id, now() AS received_at
        FROM request_records_identity_queue
        """
    )
