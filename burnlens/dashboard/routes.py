"""JSON API endpoints for the BurnLens dashboard."""
from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timedelta, timezone
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from burnlens.storage.queries import (
    get_cost_by_pr,
    get_daily_cost,
    get_recent_requests,
    get_requests_for_analysis,
    get_total_cost,
    get_usage_by_model,
    get_usage_by_tag,
)
from burnlens.storage.database import get_spend_by_team_this_month, get_top_customers_by_cost
from burnlens.key_budget import compute_keys_today
from burnlens.analysis.waste import run_all_detectors
from burnlens.analysis.budget import compute_budget_status
from burnlens.analysis.recommender import analyse_model_fit

logger = logging.getLogger(__name__)
router = APIRouter()

_DEFAULT_DB = str(Path.home() / ".burnlens" / "burnlens.db")


def _db_path(request: Request) -> str:
    return getattr(request.app.state, "db_path", _DEFAULT_DB)


def get_db_path() -> str:
    """Return the default DB path (used by standalone helpers without a Request)."""
    return _DEFAULT_DB


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


# ----------------------------------------------------------- /api/cost-by-pr

@router.get("/cost-by-pr")
async def cost_by_pr(
    request: Request,
    days: int = Query(default=7, ge=1, le=365),
    repo: Optional[str] = Query(default=None),
) -> list:
    """Top PRs by cost over the lookback window — drives the dashboard panel."""
    db = _db_path(request)
    rows = await get_cost_by_pr(db, days=days, repo=repo, limit=20)
    return [
        {
            "pr": r.get("pr"),
            "repo": r.get("repo"),
            "dev": r.get("dev"),
            "branch": r.get("branch"),
            "requests": r.get("requests", 0),
            "total_cost_usd": round(r.get("total_cost") or 0.0, 6),
            "last_seen": r.get("last_seen"),
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
    pr: Optional[str] = Query(default=None),
) -> list:
    """Most recent N requests, optionally filtered to one PR."""
    db = _db_path(request)
    return await get_recent_requests(db, limit=limit, pr=pr)


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


# ----------------------------------------------------- /api/customers

@router.get("/customers")
async def customers(request: Request) -> list:
    """Per-customer cost tracking with budget status."""
    db = _db_path(request)
    config = getattr(request.app.state, "config", None)

    cust_budgets = None
    if config and config.alerts and config.alerts.customer_budgets:
        cust_budgets = config.alerts.customer_budgets

    rows = await get_top_customers_by_cost(db)
    result = []
    for r in rows:
        customer = r["customer"]
        limit = None
        if cust_budgets:
            limit = cust_budgets.customers.get(customer, cust_budgets.default)

        pct = (r["total_cost"] / limit * 100) if limit and limit > 0 else None
        if pct is not None:
            if pct >= 100:
                status = "EXCEEDED"
            elif pct >= 80:
                status = "WARNING"
            else:
                status = "OK"
        else:
            status = "NO_LIMIT"

        result.append({
            "customer": customer,
            "request_count": r["request_count"],
            "input_tokens": r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "total_cost": round(r["total_cost"], 6),
            "budget": limit,
            "pct_used": round(pct, 1) if pct is not None else None,
            "status": status,
        })
    return result


# -------------------------------------------------------- /api/keys-today

@router.get("/keys-today")
async def keys_today(request: Request) -> list:
    """Per-API-key daily-cap progress for today (CODE-2 step 8).

    Thin wrapper around :func:`burnlens.key_budget.compute_keys_today` —
    shared with the ``burnlens keys`` CLI so the dashboard and terminal
    always agree.
    """
    db = _db_path(request)
    config = getattr(request.app.state, "config", None)
    api_key_budgets = config.alerts.api_key_budgets if config and config.alerts else None
    return await compute_keys_today(db, api_key_budgets)


# -------------------------------------------------------- /api/recommendations

@router.get("/recommendations")
async def recommendations(request: Request) -> list:
    """Model switch recommendations based on usage patterns."""
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


# -------- legacy compat: /api/models still works (used by old app.js)

@router.get("/export")
async def export_csv(
    request: Request,
    period: str = Query(default="7d"),
) -> StreamingResponse:
    """Export request data as a CSV download."""
    from burnlens.export import CSV_COLUMNS, _row_to_csv_dict
    from burnlens.storage.database import get_requests_for_export

    db = _db_path(request)
    period = period.strip().lower()
    days = 7
    if period.endswith("d"):
        try:
            days = int(period[:-1])
        except ValueError:
            pass

    rows = await get_requests_for_export(db, days=days)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow(_row_to_csv_dict(row))

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=burnlens_export_{days}d.csv"},
    )


# ------------------------------------------------------- /api/routing-stats


async def _compute_savings(
    db: aiosqlite.Connection,
    *,
    date_filter: str | None,
    since: str | None = None,
) -> float:
    """Compute USD saved by downgrading: sum of max(0, original_cost - actual_cost).

    Queries downgraded rows (downgrade_reason IS NOT NULL) for a given day
    (``date_filter``) or since an ISO date (``since``).  For each row it
    re-calculates what the *original* model would have cost using
    ``calculate_cost()``, then subtracts the actual ``cost_usd`` already
    recorded (which used the cheaper routed model).

    Returns 0.0 gracefully when the ``routed_model`` / ``downgrade_reason``
    columns do not yet exist in the DB (pre-migration databases).
    """
    from burnlens.cost.calculator import calculate_cost, TokenUsage

    # Guard: confirm the routing columns exist before querying them.
    try:
        cursor = await db.execute("PRAGMA table_info(requests)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "downgrade_reason" not in columns or "routed_model" not in columns:
            return 0.0
    except Exception:
        return 0.0

    if date_filter is not None:
        where = "downgrade_reason IS NOT NULL AND DATE(timestamp) = ?"
        params: tuple = (date_filter,)
    elif since is not None:
        where = "downgrade_reason IS NOT NULL AND DATE(timestamp) >= ?"
        params = (since,)
    else:
        return 0.0

    try:
        cursor = await db.execute(
            f"""
            SELECT provider, model, routed_model,
                   input_tokens, output_tokens, reasoning_tokens,
                   cache_read_tokens, cache_write_tokens, cost_usd
            FROM requests
            WHERE {where}
            """,
            params,
        )
        rows = await cursor.fetchall()
    except Exception as exc:
        logger.warning("routing-stats savings query failed (non-fatal): %s", exc)
        return 0.0

    total_saved = 0.0
    for row in rows:
        (provider, original_model, routed_model,
         input_tokens, output_tokens, reasoning_tokens,
         cache_read_tokens, cache_write_tokens, cost_usd) = row

        if not original_model or not provider:
            continue

        usage = TokenUsage(
            input_tokens=int(input_tokens or 0),
            output_tokens=int(output_tokens or 0),
            reasoning_tokens=int(reasoning_tokens or 0),
            cache_read_tokens=int(cache_read_tokens or 0),
            cache_write_tokens=int(cache_write_tokens or 0),
        )
        original_cost = calculate_cost(provider, original_model, usage)
        actual_cost = float(cost_usd or 0.0)
        saved = original_cost - actual_cost
        if saved > 0:
            total_saved += saved

    return total_saved


@router.get("/routing-stats")
async def get_routing_stats(request: Request) -> dict:
    """Budget-aware routing statistics: downgrade counts and USD savings.

    Returns:
        downgrades_today: number of requests downgraded today (local date)
        saved_usd_today: USD saved today via downgrades
        downgrades_this_month: number of requests downgraded this calendar month
        saved_usd_this_month: USD saved this calendar month via downgrades

    All counts are 0 when the routing columns (routed_model, downgrade_reason)
    have not yet been added by the database migration — the endpoint never
    raises a 500 due to a missing column.
    """
    db_path = _db_path(request)
    today = date.today().isoformat()
    first_of_month = date.today().replace(day=1).isoformat()

    async with aiosqlite.connect(db_path) as db:
        # Guard: confirm routing columns exist.
        try:
            cursor = await db.execute("PRAGMA table_info(requests)")
            columns = {row[1] for row in await cursor.fetchall()}
            has_routing_cols = "downgrade_reason" in columns
        except Exception:
            has_routing_cols = False

        if not has_routing_cols:
            return {
                "downgrades_today": 0,
                "saved_usd_today": 0.0,
                "downgrades_this_month": 0,
                "saved_usd_this_month": 0.0,
            }

        # Count downgrades today
        cursor = await db.execute(
            "SELECT COUNT(*) FROM requests "
            "WHERE downgrade_reason IS NOT NULL AND DATE(timestamp) = ?",
            (today,),
        )
        downgrades_today = (await cursor.fetchone())[0]

        # Count downgrades this month
        cursor = await db.execute(
            "SELECT COUNT(*) FROM requests "
            "WHERE downgrade_reason IS NOT NULL AND DATE(timestamp) >= ?",
            (first_of_month,),
        )
        downgrades_this_month = (await cursor.fetchone())[0]

        # Compute USD savings
        saved_usd_today = await _compute_savings(db, date_filter=today)
        saved_usd_this_month = await _compute_savings(db, date_filter=None, since=first_of_month)

    return {
        "downgrades_today": downgrades_today,
        "saved_usd_today": round(saved_usd_today, 4),
        "downgrades_this_month": downgrades_this_month,
        "saved_usd_this_month": round(saved_usd_this_month, 4),
    }


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
