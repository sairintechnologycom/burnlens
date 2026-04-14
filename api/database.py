"""asyncpg pool, init_db(), get_db() for BurnLens Cloud."""
from __future__ import annotations

import logging

import asyncpg

from . import config

logger = logging.getLogger(__name__)

pool: asyncpg.Pool | None = None


async def init_db() -> None:
    """Initialize connection pool and create tables."""
    global pool
    pool = await asyncpg.create_pool(
        config.DATABASE_URL,
        min_size=2,
        max_size=20,
        command_timeout=60,
    )

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS workspaces (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name            TEXT NOT NULL,
                owner_email     TEXT NOT NULL UNIQUE,
                plan            TEXT NOT NULL DEFAULT 'free',
                api_key         TEXT NOT NULL UNIQUE,
                stripe_customer_id TEXT,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                active          BOOLEAN NOT NULL DEFAULT true
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id              BIGSERIAL PRIMARY KEY,
                workspace_id    UUID NOT NULL REFERENCES workspaces(id),
                ts              TIMESTAMPTZ NOT NULL,
                provider        TEXT NOT NULL,
                model           TEXT NOT NULL,
                input_tokens    INTEGER NOT NULL DEFAULT 0,
                output_tokens   INTEGER NOT NULL DEFAULT 0,
                reasoning_tokens INTEGER NOT NULL DEFAULT 0,
                cache_read_tokens INTEGER NOT NULL DEFAULT 0,
                cache_write_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd        NUMERIC(12,8) NOT NULL DEFAULT 0,
                latency_ms      INTEGER NOT NULL DEFAULT 0,
                status_code     INTEGER,
                tag_feature     TEXT,
                tag_team        TEXT,
                tag_customer    TEXT,
                system_prompt_hash TEXT,
                received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_requests_workspace_ts
                ON requests(workspace_id, ts DESC)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_requests_workspace_team
                ON requests(workspace_id, tag_team)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_requests_workspace_feature
                ON requests(workspace_id, tag_feature)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_requests_workspace_customer
                ON requests(workspace_id, tag_customer)
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS waitlist (
                id          BIGSERIAL PRIMARY KEY,
                email       TEXT NOT NULL UNIQUE,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

    logger.info("Database tables created/verified")


async def close_db() -> None:
    """Close the connection pool."""
    global pool
    if pool:
        await pool.close()
        logger.info("Database pool closed")


async def get_db() -> asyncpg.Connection:
    """Acquire a connection from the pool."""
    if not pool:
        raise RuntimeError("Database pool not initialized")
    return await pool.acquire()
