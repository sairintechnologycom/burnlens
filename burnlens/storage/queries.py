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


async def get_usage_by_tag(
    db_path: str,
    tag_key: str = "feature",
    since: str | None = None,
) -> list[dict[str, Any]]:
    """Return per-tag cost/usage for a given tag key."""
    where = "WHERE timestamp >= ?" if since else ""
    params: tuple[Any, ...] = (since,) if since else ()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT tags, cost_usd, input_tokens, output_tokens FROM requests {where}",
            params,
        )
        rows = await cursor.fetchall()

    # Aggregate in Python since SQLite JSON support may be limited
    totals: dict[str, dict[str, Any]] = {}
    for row in rows:
        tags = json.loads(row["tags"] or "{}")
        tag_val = tags.get(tag_key, "(untagged)")
        if tag_val not in totals:
            totals[tag_val] = {
                "tag": tag_val,
                "request_count": 0,
                "total_cost_usd": 0.0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
            }
        totals[tag_val]["request_count"] += 1
        totals[tag_val]["total_cost_usd"] += row["cost_usd"] or 0.0
        totals[tag_val]["total_input_tokens"] += row["input_tokens"] or 0
        totals[tag_val]["total_output_tokens"] += row["output_tokens"] or 0

    return sorted(totals.values(), key=lambda x: x["total_cost_usd"], reverse=True)


async def get_total_request_count(db_path: str, since: str | None = None) -> int:
    """Return total number of requests."""
    where = "WHERE timestamp >= ?" if since else ""
    params: tuple[Any, ...] = (since,) if since else ()

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            f"SELECT COUNT(*) FROM requests {where}",
            params,
        )
        row = await cursor.fetchone()

    return int(row[0]) if row else 0


async def get_daily_cost(
    db_path: str,
    days: int = 7,
) -> list[dict[str, Any]]:
    """Return cost per day for the last N days."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                DATE(timestamp) AS day,
                COUNT(*) AS request_count,
                SUM(cost_usd) AS total_cost_usd
            FROM requests
            WHERE timestamp >= DATE('now', ?)
            GROUP BY DATE(timestamp)
            ORDER BY day ASC
            """,
            (f"-{days} days",),
        )
        rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def get_requests_for_analysis(
    db_path: str,
    since: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Return recent requests with all fields needed for waste analysis."""
    where = "WHERE timestamp >= ?" if since else ""
    params: tuple[Any, ...] = (since,) if since else ()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"""
            SELECT
                id, timestamp, provider, model,
                input_tokens, output_tokens, cost_usd,
                duration_ms, tags, system_prompt_hash
            FROM requests
            {where}
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (*params, limit),
        )
        rows = await cursor.fetchall()

    result = []
    for row in rows:
        d = dict(row)
        d["tags"] = json.loads(d.get("tags") or "{}")
        result.append(d)
    return result
