"""GET /api/* dashboard endpoints — all scoped to workspace_id."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from . import config
from .auth import get_current_workspace

logger = logging.getLogger(__name__)

router = APIRouter()


def _effective_days(requested: int, plan: str) -> int:
    max_days = config.PLAN_HISTORY_DAYS.get(plan, 7)
    return min(requested, max_days)


def _cutoff(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


# ---------- GET /api/stats ---------------------------------------------------

@router.get("/api/stats")
async def get_stats(
    days: int = Query(7, ge=1),
    ws: dict = Depends(get_current_workspace),
):
    eff = _effective_days(days, ws["plan"])
    cut = _cutoff(eff)

    from .database import pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                COALESCE(SUM(cost_usd), 0)   AS total_cost,
                COUNT(*)                      AS total_requests,
                COALESCE(AVG(cost_usd), 0)    AS avg_cost
            FROM requests
            WHERE workspace_id = $1 AND ts >= $2
            """,
            ws["id"],
            cut,
        )

    return {
        "total_cost": float(row["total_cost"]),
        "total_requests": int(row["total_requests"]),
        "avg_cost_per_request": float(row["avg_cost"]),
        "period_start": cut.isoformat(),
        "period_end": datetime.now(timezone.utc).isoformat(),
    }


# ---------- GET /api/cost-by-model -------------------------------------------

@router.get("/api/cost-by-model")
async def cost_by_model(
    days: int = Query(7, ge=1),
    ws: dict = Depends(get_current_workspace),
):
    eff = _effective_days(days, ws["plan"])
    cut = _cutoff(eff)

    from .database import pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT model, COALESCE(SUM(cost_usd), 0) AS cost
            FROM requests
            WHERE workspace_id = $1 AND ts >= $2
            GROUP BY model ORDER BY cost DESC
            """,
            ws["id"],
            cut,
        )

    return {r["model"]: float(r["cost"]) for r in rows}


# ---------- GET /api/cost-by-feature -----------------------------------------

@router.get("/api/cost-by-feature")
async def cost_by_feature(
    days: int = Query(7, ge=1),
    ws: dict = Depends(get_current_workspace),
):
    eff = _effective_days(days, ws["plan"])
    cut = _cutoff(eff)

    from .database import pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT tag_feature, COALESCE(SUM(cost_usd), 0) AS cost
            FROM requests
            WHERE workspace_id = $1 AND ts >= $2 AND tag_feature IS NOT NULL
            GROUP BY tag_feature ORDER BY cost DESC
            """,
            ws["id"],
            cut,
        )

    return {r["tag_feature"]: float(r["cost"]) for r in rows}


# ---------- GET /api/cost-by-team --------------------------------------------

@router.get("/api/cost-by-team")
async def cost_by_team(
    days: int = Query(7, ge=1),
    ws: dict = Depends(get_current_workspace),
):
    eff = _effective_days(days, ws["plan"])
    cut = _cutoff(eff)

    from .database import pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT tag_team, COALESCE(SUM(cost_usd), 0) AS cost
            FROM requests
            WHERE workspace_id = $1 AND ts >= $2 AND tag_team IS NOT NULL
            GROUP BY tag_team ORDER BY cost DESC
            """,
            ws["id"],
            cut,
        )

    return {r["tag_team"]: float(r["cost"]) for r in rows}


# ---------- GET /api/cost-by-customer ----------------------------------------

@router.get("/api/cost-by-customer")
async def cost_by_customer(
    days: int = Query(7, ge=1),
    ws: dict = Depends(get_current_workspace),
):
    eff = _effective_days(days, ws["plan"])
    cut = _cutoff(eff)

    from .database import pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT tag_customer, COALESCE(SUM(cost_usd), 0) AS cost
            FROM requests
            WHERE workspace_id = $1 AND ts >= $2 AND tag_customer IS NOT NULL
            GROUP BY tag_customer ORDER BY cost DESC
            """,
            ws["id"],
            cut,
        )

    return {r["tag_customer"]: float(r["cost"]) for r in rows}


# ---------- GET /api/cost-timeline -------------------------------------------

@router.get("/api/cost-timeline")
async def cost_timeline(
    days: int = Query(7, ge=1),
    ws: dict = Depends(get_current_workspace),
):
    eff = _effective_days(days, ws["plan"])
    cut = _cutoff(eff)
    now = datetime.now(timezone.utc)

    from .database import pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DATE(ts AT TIME ZONE 'UTC') AS day,
                   COALESCE(SUM(cost_usd), 0)  AS cost
            FROM requests
            WHERE workspace_id = $1 AND ts >= $2
            GROUP BY day ORDER BY day
            """,
            ws["id"],
            cut,
        )

    # Build a dict of existing data
    data = {str(r["day"]): float(r["cost"]) for r in rows}

    # Zero-fill missing days
    result = []
    d = cut.date()
    end = now.date()
    while d <= end:
        ds = str(d)
        result.append({"date": ds, "cost": data.get(ds, 0.0)})
        d += timedelta(days=1)

    return result


# ---------- GET /api/requests ------------------------------------------------

@router.get("/api/requests")
async def list_requests(
    days: int = Query(7, ge=1),
    limit: int = Query(100, ge=1, le=500),
    ws: dict = Depends(get_current_workspace),
):
    eff = _effective_days(days, ws["plan"])
    cut = _cutoff(eff)

    from .database import pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT ts, provider, model, tag_feature, tag_team, tag_customer,
                   input_tokens, output_tokens, cost_usd, latency_ms, status_code
            FROM requests
            WHERE workspace_id = $1 AND ts >= $2
            ORDER BY ts DESC
            LIMIT $3
            """,
            ws["id"],
            cut,
            limit,
        )

    return [
        {
            "ts": r["ts"].isoformat(),
            "provider": r["provider"],
            "model": r["model"],
            "tag_feature": r["tag_feature"],
            "tag_team": r["tag_team"],
            "tag_customer": r["tag_customer"],
            "input_tokens": r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "cost_usd": float(r["cost_usd"]),
            "latency_ms": r["latency_ms"],
            "status_code": r["status_code"],
        }
        for r in rows
    ]
