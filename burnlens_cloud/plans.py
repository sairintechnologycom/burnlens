"""Plan-limit resolver — Python wrapper around the Postgres `resolve_limits()` function.

This is the single entry point downstream phases (7: Paddle webhooks, 9: quota enforcement,
10: feature gating UI) use to read effective per-workspace limits.

Design notes:
- Single Postgres round-trip per call (D-05) via `SELECT * FROM resolve_limits($1)`.
- No in-process cache (D-06) — the round-trip cost is acceptable, and cache invalidation
  across Railway workers after Phase 7 webhook writes would be non-trivial.
- Returns `None` for nonexistent workspaces — callers decide whether to 404 or raise.
- Treats `None` on any scalar field as "unlimited" (D-02).
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from .database import pool
from .models import ResolvedLimits


async def resolve_limits(workspace_id: UUID) -> Optional[ResolvedLimits]:
    """Return the effective limits for a workspace, or None if it does not exist.

    Performs one Postgres round-trip against the `resolve_limits(ws_id UUID)` SQL
    function, which merges any per-workspace overrides over the plan default and
    returns the combined row.

    Args:
        workspace_id: UUID of the workspace.

    Returns:
        `ResolvedLimits` with scalar limits and merged `gated_features`, or `None`
        if no workspace exists with that id.
    """
    if pool is None:
        raise RuntimeError("Database pool not initialized — call init_db() first")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM resolve_limits($1)",
            workspace_id,
        )

    if row is None:
        return None

    # asyncpg returns JSONB as str by default; cast to dict if needed.
    gated = row["gated_features"]
    if isinstance(gated, str):
        import json
        gated = json.loads(gated)

    return ResolvedLimits(
        plan=row["plan"],
        monthly_request_cap=row["monthly_request_cap"],
        seat_count=row["seat_count"],
        retention_days=row["retention_days"],
        api_key_count=row["api_key_count"],
        gated_features=gated or {},
    )
