"""Cloud-compatible API routes for the local proxy.

The Next.js frontend uses cloud-style paths (/api/v1/usage/...) with `days`
query params.  The local dashboard routes use different paths (/api/...) with
`period` string params and return slightly different shapes.

This module provides thin adapter routes that re-use the existing local query
functions but expose the same paths and response shapes as the cloud backend,
so the frontend works identically in both modes.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request

from burnlens.storage.queries import (
    get_daily_cost,
    get_recent_requests,
    get_total_cost,
    get_usage_by_model,
    get_usage_by_tag,
)
from burnlens.storage.database import get_spend_by_team_this_month, get_top_customers_by_cost
from burnlens.analysis.waste import run_all_detectors
from burnlens.analysis.recommender import analyse_model_fit
from burnlens.storage.queries import get_requests_for_analysis

logger = logging.getLogger(__name__)

usage_router = APIRouter(tags=["cloud-compat-usage"])
requests_router = APIRouter(tags=["cloud-compat-requests"])

_DEFAULT_DB = str(Path.home() / ".burnlens" / "burnlens.db")


def _db_path(request: Request) -> str:
    return getattr(request.app.state, "db_path", _DEFAULT_DB)


def _since_iso(days: int) -> str:
    """Convert days integer to ISO timestamp string for local queries."""
    from datetime import datetime, timedelta, timezone
    since = datetime.now(timezone.utc) - timedelta(days=days)
    return since.isoformat(timespec="seconds").replace("+00:00", "")


# ------------------------------------------------------------------ /api/v1/usage/summary

@usage_router.get("/summary")
async def usage_summary(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
) -> dict:
    """Cloud-compatible usage summary."""
    db = _db_path(request)
    since = _since_iso(days)

    total_cost = await get_total_cost(db, since=since)
    models = await get_usage_by_model(db, since=since)
    total_requests = sum(m.request_count for m in models)
    total_tokens = sum(m.total_input_tokens + m.total_output_tokens for m in models)

    by_provider: dict[str, dict] = {}
    for m in models:
        p = m.provider or "unknown"
        if p not in by_provider:
            by_provider[p] = {"provider": p, "total_cost": 0.0, "api_calls": 0}
        by_provider[p]["total_cost"] += m.total_cost_usd
        by_provider[p]["api_calls"] += m.request_count

    by_model = [
        {
            "provider": m.provider or "unknown",
            "model": m.model,
            "total_cost": round(m.total_cost_usd, 6),
            "api_calls": m.request_count,
        }
        for m in models
    ]

    return {
        "total_cost": round(total_cost, 6),
        "total_tokens": total_tokens,
        "total_calls": total_requests,
        "total_requests": total_requests,
        "by_provider": list(by_provider.values()),
        "by_model": by_model,
    }


# -------------------------------------------------------------- /api/v1/usage/timeseries

@usage_router.get("/timeseries")
async def usage_timeseries(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    granularity: str = Query(default="day"),
) -> list[dict]:
    """Cloud-compatible daily cost timeseries."""
    db = _db_path(request)
    rows = await get_daily_cost(db, days=days)
    return [
        {
            "date": r["day"],
            "provider": "all",
            "cost": round(r["total_cost_usd"] or 0.0, 6),
            "tokens": 0,
            "calls": r["request_count"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------- /api/v1/usage/by-model

@usage_router.get("/by-model")
async def usage_by_model(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
) -> list[dict]:
    """Cloud-compatible model breakdown."""
    db = _db_path(request)
    since = _since_iso(days)
    rows = await get_usage_by_model(db, since=since)
    return [
        {
            "provider": r.provider or "unknown",
            "model": r.model,
            "total_cost": round(r.total_cost_usd, 6),
            "input_tokens": r.total_input_tokens,
            "output_tokens": r.total_output_tokens,
            "api_calls": r.request_count,
            "avg_latency_ms": None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------- /api/v1/usage/by-team

@usage_router.get("/by-team")
async def usage_by_team(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
) -> list[dict]:
    """Cloud-compatible team breakdown."""
    db = _db_path(request)
    spend = await get_spend_by_team_this_month(db)
    return [
        {"team": team, "total_cost": round(cost, 6), "api_calls": 0}
        for team, cost in spend.items()
    ]


# ------------------------------------------------------------- /api/v1/usage/by-customer

@usage_router.get("/by-customer")
async def usage_by_customer(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
) -> list[dict]:
    """Cloud-compatible customer breakdown."""
    db = _db_path(request)
    rows = await get_top_customers_by_cost(db)
    return [
        {
            "customer": r["customer"],
            "total_cost": round(r["total_cost"], 6),
            "api_calls": r["request_count"],
        }
        for r in rows
    ]


# -------------------------------------------------------------------- /api/v1/requests

@requests_router.get("/requests")
async def recent_requests(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=50, le=500),
) -> list[dict]:
    """Cloud-compatible recent requests."""
    db = _db_path(request)
    rows = await get_recent_requests(db, limit=limit)
    return [
        {
            "timestamp": r.get("timestamp", ""),
            "model": r.get("model", ""),
            "provider": r.get("provider", ""),
            "feature": (r.get("tags") or {}).get("feature"),
            "team": (r.get("tags") or {}).get("team"),
            "cost": r.get("cost_usd", 0.0),
            "latency_ms": r.get("duration_ms"),
            "input_tokens": r.get("input_tokens", 0),
            "output_tokens": r.get("output_tokens", 0),
        }
        for r in rows
    ]


# ------------------------------------------------------------ /api/v1/waste-alerts

@requests_router.get("/waste-alerts")
async def waste_alerts(request: Request) -> list[dict]:
    """Cloud-compatible waste alerts."""
    db = _db_path(request)
    requests_data = await get_requests_for_analysis(db, limit=1000)
    findings = run_all_detectors(requests_data)
    return [
        {
            "id": f"{f.detector}_{i}",
            "detector": f.detector,
            "severity": f.severity,
            "title": f.title,
            "description": f.description,
            "estimated_waste_usd": round(f.estimated_waste_usd, 6),
            "monthly_savings": round(f.estimated_waste_usd, 2),
            "affected_count": f.affected_count,
        }
        for i, f in enumerate(findings)
    ]


# --------------------------------------------------------- /api/v1/recommendations

@requests_router.get("/recommendations")
async def recommendations(request: Request) -> list[dict]:
    """Cloud-compatible recommendations."""
    db = _db_path(request)
    recs = await analyse_model_fit(db, days=30)
    return [
        {
            "current_model": r.current_model,
            "suggested_model": r.suggested_model,
            "feature_tag": r.feature_tag,
            "request_count": r.request_count,
            "avg_output_tokens": r.avg_output_tokens,
            "current_cost": round(r.current_cost, 6),
            "projected_cost": round(r.projected_cost, 6),
            "projected_saving": round(r.projected_saving, 6),
            "saving_pct": r.saving_pct,
            "confidence": r.confidence,
            "reason": r.reason,
        }
        for r in recs
    ]
