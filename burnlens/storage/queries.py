"""Aggregation queries for the BurnLens dashboard and CLI."""
from __future__ import annotations

import json
from typing import Any

import aiosqlite

from burnlens.storage.models import AggregatedUsage


async def get_usage_by_model(
    db_path: str,
    since: str | None = None,
) -> list[AggregatedUsage]:
    """Return per-model cost/usage aggregated over all time (or since ISO timestamp)."""
    where = "WHERE timestamp >= ?" if since else ""
    params: tuple[Any, ...] = (since,) if since else ()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"""
            SELECT
                model, provider,
                COUNT(*) AS request_count,
                SUM(input_tokens)  AS total_input_tokens,
                SUM(output_tokens) AS total_output_tokens,
                SUM(cost_usd)      AS total_cost_usd
            FROM requests
            {where}
            GROUP BY model, provider
            ORDER BY total_cost_usd DESC
            """,
            params,
        )
        rows = await cursor.fetchall()

    return [
        AggregatedUsage(
            model=row["model"],
            provider=row["provider"],
            request_count=row["request_count"],
            total_input_tokens=row["total_input_tokens"],
            total_output_tokens=row["total_output_tokens"],
            total_cost_usd=row["total_cost_usd"],
        )
        for row in rows
    ]


async def get_recent_requests(
    db_path: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return the most recent N requests as plain dicts."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM requests
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()

    result = []
    for row in rows:
        d = dict(row)
        d["tags"] = json.loads(d.get("tags") or "{}")
        result.append(d)
    return result


async def get_total_cost(db_path: str, since: str | None = None) -> float:
    """Return total cost in USD (optionally since an ISO timestamp)."""
    where = "WHERE timestamp >= ?" if since else ""
    params: tuple[Any, ...] = (since,) if since else ()

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            f"SELECT COALESCE(SUM(cost_usd), 0.0) FROM requests {where}",
            params,
        )
        row = await cursor.fetchone()

    return float(row[0]) if row else 0.0
