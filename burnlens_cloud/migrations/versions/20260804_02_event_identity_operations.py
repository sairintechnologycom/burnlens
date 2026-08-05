"""Operational state for the additive event-identity stream outbox."""
from __future__ import annotations


async def upgrade_postgres(conn) -> None:
    await conn.execute(
        """
        ALTER TABLE stream_ingest_outbox
            ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS failed_attempts INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS last_error TEXT,
            ADD COLUMN IF NOT EXISTS dead_lettered_at TIMESTAMPTZ
        """
    )
    await conn.execute(
        """
        ALTER TABLE ingest_event_identities
            ADD COLUMN IF NOT EXISTS conflict_count INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS last_conflict_at TIMESTAMPTZ
        """
    )
    await conn.execute(
        """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stream_ingest_outbox_dead_letters
        ON stream_ingest_outbox(dead_lettered_at)
        WHERE dead_lettered_at IS NOT NULL
        """
    )


def upgrade_clickhouse(client) -> None:
    # Outbox operational state is PostgreSQL-only; analytical schema is unchanged.
    return None
