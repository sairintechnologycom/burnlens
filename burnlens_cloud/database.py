import asyncpg
import logging
from .config import settings

logger = logging.getLogger(__name__)

# Global database pool
pool: asyncpg.Pool = None


async def init_db():
    """Initialize database connection pool and create tables."""
    global pool

    # Create connection pool
    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=2,
        max_size=20,
        command_timeout=60,
    )

    # Create tables
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS workspaces (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name TEXT NOT NULL,
                owner_email TEXT NOT NULL,
                stripe_customer_id TEXT,
                plan TEXT NOT NULL DEFAULT 'free',
                api_key TEXT UNIQUE NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                active BOOLEAN NOT NULL DEFAULT true
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS request_records (
                id BIGSERIAL PRIMARY KEY,
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                ts TIMESTAMPTZ NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INT NOT NULL DEFAULT 0,
                output_tokens INT NOT NULL DEFAULT 0,
                reasoning_tokens INT NOT NULL DEFAULT 0,
                cache_read_tokens INT NOT NULL DEFAULT 0,
                cache_write_tokens INT NOT NULL DEFAULT 0,
                cost_usd NUMERIC(12, 8) NOT NULL DEFAULT 0,
                duration_ms INT NOT NULL DEFAULT 0,
                status_code INT NOT NULL DEFAULT 200,
                tags JSONB NOT NULL DEFAULT '{}',
                system_prompt_hash TEXT,
                received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        # Create indexes
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_request_records_workspace_ts
            ON request_records(workspace_id, ts DESC)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_request_records_workspace_team
            ON request_records USING GIN(workspace_id, (tags -> 'team'))
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_request_records_workspace_customer
            ON request_records USING GIN(workspace_id, (tags -> 'customer'))
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_request_records_workspace_feature
            ON request_records USING GIN(workspace_id, (tags -> 'feature'))
        """)

        # Teams support tables
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email TEXT UNIQUE NOT NULL,
                name TEXT,
                google_id TEXT UNIQUE,
                github_id TEXT UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_login TIMESTAMPTZ
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_github_id ON users(github_id)
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS workspace_members (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL DEFAULT 'viewer',
                invited_by UUID REFERENCES users(id) ON DELETE SET NULL,
                joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                active BOOLEAN NOT NULL DEFAULT true
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_workspace_members_workspace_user
            ON workspace_members(workspace_id, user_id)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_workspace_members_user
            ON workspace_members(user_id)
        """)

        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_members_unique
            ON workspace_members(workspace_id, user_id) WHERE active = true
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS invitations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                email TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'viewer',
                token TEXT UNIQUE NOT NULL,
                invited_by UUID REFERENCES users(id) ON DELETE SET NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                accepted_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_invitations_token ON invitations(token)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_invitations_workspace ON invitations(workspace_id)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_invitations_email ON invitations(email)
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS workspace_activity (
                id BIGSERIAL PRIMARY KEY,
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                user_id UUID REFERENCES users(id) ON DELETE SET NULL,
                action TEXT NOT NULL,
                detail JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_workspace_activity_workspace_ts
            ON workspace_activity(workspace_id, created_at DESC)
        """)

        logger.info("Database tables created/verified")


async def close_db():
    """Close database connection pool."""
    global pool
    if pool:
        await pool.close()
        logger.info("Database pool closed")


async def get_db():
    """Get a connection from the pool."""
    if not pool:
        raise RuntimeError("Database pool not initialized")
    return await pool.acquire()


async def execute_query(query: str, *args):
    """Execute a query and return results."""
    async with await get_db() as conn:
        return await conn.fetch(query, *args)


async def execute_insert(query: str, *args):
    """Execute an insert query and return the number of rows affected."""
    async with await get_db() as conn:
        return await conn.execute(query, *args)


async def execute_bulk_insert(query: str, args_list: list):
    """Execute bulk insert using executemany."""
    async with await get_db() as conn:
        return await conn.executemany(query, args_list)
