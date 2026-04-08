"""JSON API endpoints for the BurnLens dashboard."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Query, Request

from burnlens.storage.queries import (
    get_daily_cost,
    get_recent_requests,
    get_requests_for_analysis,
    get_total_cost,
    get_usage_by_model,
    get_usage_by_tag,
)
from burnlens.storage.database import get_spend_by_team_this_month
from burnlens.analysis.waste import run_all_detectors
from burnlens.analysis.budget import compute_budget_status

logger = logging.getLogger(__name__)
router = APIRouter()

_DEFAULT_DB = str(Path.home() / ".burnlens" / "burnlens.db")


def _db_path(request: Request) -> str:
    return getattr(request.app.state, "db_path", _DEFAULT_DB)


def _budget_limit(request: Request) -> float | None:
    config = getattr(request.app.state, "config", None)
    if config and config.alerts:
        return config.alerts.budget_limit_usd
    return None


def _parse_period(period: str) -> str | None:
    """Convert period string like '7d', '30d' to ISO timestamp (UTC)."""
    period = period.strip().lower()
    if period.endswith("d"):
        try:
            days = int(period[:-1])
            since = datetime.now(timezone.utc) - timedelta(days=days)
            return since.isoformat(timespec="seconds").replace("+00:00", "")
        except ValueError:
            pass
    return None  # no filter


# ------------------------------------------------------------------ /api/summary

@router.get("/summary")
async def summary(
    request: Request,
    period: str = Query(default="7d"),
) -> dict:
    """Total spend, request count, avg cost, budget %."""
    db = _db_path(request)
    since = _parse_period(period)

    total_cost = await get_total_cost(db, since=since)
    models = await get_usage_by_model(db, since=since)
    total_requests = sum(m.request_count for m in models)
    avg_cost = (total_cost / total_requests) if total_requests else 0.0

    budget_limit = _budget_limit(request)
    budget_pct = (total_cost / budget_limit * 100) if budget_limit else None

    return {
        "total_cost_usd": round(total_cost, 6),
        "total_requests": total_requests,
        "avg_cost_per_request_usd": round(avg_cost, 6),
        "models_used": len(models),
        "budget_limit_usd": budget_limit,
        "budget_pct_used": round(budget_pct, 1) if budget_pct is not None else None,
        "period": period,
    }


# --------------------------------------------------------- /api/costs/by-model

@router.get("/costs/by-model")
async def costs_by_model(
    request: Request,
    period: str = Query(default="7d"),
) -> list:
    """Per-model cost breakdown."""
    db = _db_path(request)
    since = _parse_period(period)
    rows = await get_usage_by_model(db, since=since)
    return [
        {
            "model": r.model,
            "provider": r.provider,
            "request_count": r.request_count,
            "total_input_tokens": r.total_input_tokens,
            "total_output_tokens": r.total_output_tokens,
            "total_cost_usd": round(r.total_cost_usd, 6),
        }
        for r in rows
    ]


# ---------------------------------------------------------- /api/costs/by-tag

@router.get("/costs/by-tag")
async def costs_by_tag(
    request: Request,
    tag: str = Query(default="feature"),
    period: str = Query(default="7d"),
) -> list:
    """Per-tag cost breakdown."""
    db = _db_path(request)
    since = _parse_period(period)
    rows = await get_usage_by_tag(db, tag_key=tag, since=since)
    return [
        {
            "tag": r["tag"],
            "request_count": r["request_count"],
            "total_cost_usd": round(r["total_cost_usd"], 6),
            "total_input_tokens": r["total_input_tokens"],
            "total_output_tokens": r["total_output_tokens"],
        }
        for r in rows
    ]


# ------------------------------------------------------- /api/costs/timeline

@router.get("/costs/timeline")
async def costs_timeline(
    request: Request,
    period: str = Query(default="7d"),
    granularity: str = Query(default="daily"),
) -> list:
    """Cost over time (daily granularity)."""
    db = _db_path(request)
    period = period.strip().lower()
    days = 7
    if period.endswith("d"):
        try:
            days = int(period[:-1])
        except ValueError:
            pass

    rows = await get_daily_cost(db, days=days)
    return [
        {
            "date": r["day"],
            "request_count": r["request_count"],
            "total_cost_usd": round(r["total_cost_usd"] or 0.0, 6),
        }
        for r in rows
    ]


# ------------------------------------------------------------ /api/requests

@router.get("/requests")
async def recent_requests(
    request: Request,
    limit: int = Query(default=50, le=500),
) -> list:
    """Most recent N requests."""
    db = _db_path(request)
    return await get_recent_requests(db, limit=limit)


# --------------------------------------------------------------- /api/waste

@router.get("/waste")
async def waste(request: Request) -> list:
    """Waste findings from all detectors."""
    db = _db_path(request)
    requests_data = await get_requests_for_analysis(db, limit=1000)
    findings = run_all_detectors(requests_data)
    return [
        {
            "detector": f.detector,
            "severity": f.severity,
            "title": f.title,
            "description": f.description,
            "estimated_waste_usd": round(f.estimated_waste_usd, 6),
            "affected_count": f.affected_count,
        }
        for f in findings
    ]


# -------------------------------------------------------------- /api/budget

@router.get("/budget")
async def budget(request: Request) -> dict:
    """Budget status and forecast."""
    db = _db_path(request)
    budget_limit = _budget_limit(request)
    total_cost = await get_total_cost(db)
    status = compute_budget_status(
        spent_usd=total_cost,
        budget_usd=budget_limit,
    )
    return {
        "budget_usd": status.budget_usd,
        "spent_usd": round(status.spent_usd, 6),
        "remaining_usd": round(status.remaining_usd, 6) if status.remaining_usd is not None else None,
        "forecast_usd": round(status.forecast_usd, 6),
        "pct_used": round(status.pct_used, 1) if status.pct_used is not None else None,
        "is_over_budget": status.is_over_budget,
        "is_on_pace_to_exceed": status.is_on_pace_to_exceed,
        "period_days": status.period_days,
        "elapsed_days": status.elapsed_days,
    }


# -------------------------------------------------------- /api/team-budgets

@router.get("/team-budgets")
async def team_budgets(request: Request) -> list:
    """Per-team budget status for the current month."""
    db = _db_path(request)
    config = getattr(request.app.state, "config", None)
    team_limits: dict[str, float] = {}
    if config and config.alerts and config.alerts.budgets:
        team_limits = config.alerts.budgets.teams

    if not team_limits:
        return []

    spend = await get_spend_by_team_this_month(db)
    result = []
    for team, limit in sorted(team_limits.items()):
        spent = spend.get(team, 0.0)
        pct = (spent / limit * 100) if limit > 0 else 0.0
        if pct >= 100:
            status = "CRITICAL"
        elif pct >= 80:
            status = "WARNING"
        else:
            status = "OK"
        result.append({
            "team": team,
            "spent": round(spent, 6),
            "limit": limit,
            "pct_used": round(pct, 1),
            "status": status,
        })
    return result


# -------- legacy compat: /api/models still works (used by old app.js)

@router.get("/models")
async def models_compat(request: Request) -> list:
    """Alias for /costs/by-model (no period filter)."""
    db = _db_path(request)
    rows = await get_usage_by_model(db)
    return [
        {
            "model": r.model,
            "provider": r.provider,
            "request_count": r.request_count,
            "total_input_tokens": r.total_input_tokens,
            "total_output_tokens": r.total_output_tokens,
            "total_cost_usd": round(r.total_cost_usd, 6),
        }
        for r in rows
    ]
