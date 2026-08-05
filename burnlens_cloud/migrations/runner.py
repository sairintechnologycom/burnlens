"""Small versioned migration runner for BurnLens Cloud's expand-only changes."""
from __future__ import annotations

import argparse
import asyncio
import importlib
import os
from collections.abc import Iterable

import asyncpg


VERSIONS = ("20260804_01_event_identity", "20260804_02_event_identity_operations")


def _database_url() -> str:
    value = os.environ["DATABASE_URL"]
    return value.replace("postgresql+asyncpg://", "postgresql://", 1)


async def upgrade_postgres(versions: Iterable[str] = VERSIONS) -> None:
    conn = await asyncpg.connect(_database_url())
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        applied = {row["version"] for row in await conn.fetch("SELECT version FROM schema_migrations")}
        for version in versions:
            if version in applied:
                continue
            migration = importlib.import_module(f"burnlens_cloud.migrations.versions.{version}")
            await migration.upgrade_postgres(conn)
            await conn.execute("INSERT INTO schema_migrations (version) VALUES ($1)", version)
    finally:
        await conn.close()


async def upgrade_clickhouse(versions: Iterable[str] = VERSIONS) -> None:
    from burnlens_cloud.clickhouse import get_clickhouse_client

    client = get_clickhouse_client()
    for version in versions:
        migration = importlib.import_module(f"burnlens_cloud.migrations.versions.{version}")
        migration.upgrade_clickhouse(client)


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply BurnLens Cloud expand-only migrations")
    parser.add_argument("target", choices=("postgres", "clickhouse", "all"))
    args = parser.parse_args()
    if args.target in ("postgres", "all"):
        asyncio.run(upgrade_postgres())
    if args.target in ("clickhouse", "all"):
        asyncio.run(upgrade_clickhouse())


if __name__ == "__main__":
    main()
