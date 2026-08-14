import logging
from calendar import monthrange
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from dateutil import tz

from .auth import verify_token, TokenPayload, require_feature
from .config import settings
from .database import execute_query
from .plans import resolve_limits
from .clickhouse import (
    CLICKHOUSE_TAG_COLUMNS,
    get_spend_summary,
    get_spend_by_model,
    get_spend_by_tag,
    get_spend_timeseries,
)
from .models import (
    INCLUSIVE_PROMPT_TOKEN_PROVIDERS,
    StatsSummary,
    CostByModel,
    CostByTag,
    CostTimeline,
    RecommendationItem,
    RequestRecordResponse,
    TeamBudgetRow,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["dashboard"])

# Role hierarchy for permission checking
ROLE_HIERARCHY = {"viewer": 0, "admin": 1, "owner": 2}


async def require_role(required_role: str, token: TokenPayload):
    """
    Check if user has required role.
    Raises 403 HTTPException if insufficient permissions.
    """
    if ROLE_HIERARCHY.get(token.role, -1) < ROLE_HIERARCHY.get(required_role, 999):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "insufficient_role",
                "required": required_role,
                "current": token.role,
            },
        )


def clamp_days_by_plan(requested_days: int, plan: str) -> int:
    """Clamp requested history days based on workspace plan."""
    max_days = settings.plan_history_days.get(plan, 7)
    return min(requested_days, max_days)


async def parse_period(period_str: str) -> datetime:
    """Parse period string (e.g. '7d', '30d') to datetime cutoff."""
    # Default to 7 days
    days = 7

    if period_str.endswith("d"):
        try:
            days = int(period_str[:-1])
        except ValueError:
            pass

    now = datetime.now(tz.UTC)
    return now - timedelta(days=days)


@router.get("/usage/summary", response_model=StatsSummary)
async def get_summary(
    token: TokenPayload = Depends(verify_token),
    days: int = Query(7, description="Number of days to look back"),
):
    """Get cost summary for workspace (viewer+ can access)."""
    await require_role("viewer", token)

    days = clamp_days_by_plan(days, token.plan)
    cutoff = await parse_period(f"{days}d")
    
    # Use ClickHouse if streaming is enabled for high-performance analytics
    if settings.streaming_enabled:
        try:
            summary = await get_spend_summary(
                str(token.workspace_id),
                cutoff.date().isoformat(),
                datetime.utcnow().date().isoformat()
            )
            total_requests = summary["total_requests"]
            avg_cost = summary["total_cost_usd"] / total_requests if total_requests > 0 else 0.0
            
            return StatsSummary(
                total_cost_usd=summary["total_cost_usd"],
                total_requests=total_requests,
                avg_cost_per_request_usd=avg_cost,
                models_used=0, # Summary wrapper doesn't currently return distinct models
            )
        except Exception as e:
            logger.warning("ClickHouse summary query failed, falling back to PostgreSQL: %s", e)

    result = await execute_query(
        """
        SELECT
            COALESCE(SUM(cost_usd), 0) as total_cost,
            COUNT(*) as request_count,
            COUNT(DISTINCT model) as model_count,
            COALESCE(AVG(cost_usd), 0) as avg_cost,
            COALESCE(SUM(cache_saved_usd), 0) as cache_saved,
            COALESCE(SUM(cache_hit), 0) as cache_hits
        FROM request_records
        WHERE workspace_id = $1 AND ts >= $2
        """,
        str(token.workspace_id),
        cutoff,
    )

    row = result[0] if result else {}

    return StatsSummary(
        total_cost_usd=float(row.get("total_cost", 0)),
        total_requests=int(row.get("request_count", 0)),
        avg_cost_per_request_usd=float(row.get("avg_cost", 0)),
        models_used=int(row.get("model_count", 0)),
        cache_saved_usd=float(row.get("cache_saved", 0)),
        cache_hits=int(row.get("cache_hits", 0)),
    )


@router.get("/usage/by-model", response_model=List[CostByModel])
async def get_costs_by_model(
    token: TokenPayload = Depends(verify_token),
    days: int = Query(7, description="Number of days to look back"),
):
    """Get costs broken down by model (viewer+ can access)."""
    await require_role("viewer", token)

    days = clamp_days_by_plan(days, token.plan)
    cutoff = await parse_period(f"{days}d")

    # Use ClickHouse if streaming is enabled
    if settings.streaming_enabled:
        try:
            results = await get_spend_by_model(
                str(token.workspace_id),
                cutoff.date().isoformat(),
                datetime.utcnow().date().isoformat()
            )
            return [
                CostByModel(
                    model=row["model"],
                    provider=row["provider"],
                    request_count=row["request_count"],
                    total_input_tokens=row["total_input_tokens"],
                    total_output_tokens=row["total_output_tokens"],
                    total_cost_usd=row["total_cost_usd"],
                )
                for row in results
            ]
        except Exception as e:
            logger.warning("ClickHouse by-model query failed, falling back to PostgreSQL: %s", e)

    result = await execute_query(
        """
        SELECT
            model,
            provider,
            COUNT(*) as request_count,
            COALESCE(SUM(input_tokens), 0) as total_input_tokens,
            COALESCE(SUM(output_tokens), 0) as total_output_tokens,
            COALESCE(SUM(cost_usd), 0) as total_cost
        FROM request_records
        WHERE workspace_id = $1 AND ts >= $2
        GROUP BY model, provider
        ORDER BY total_cost DESC
        """,
        str(token.workspace_id),
        cutoff,
    )

    return [
        CostByModel(
            model=row["model"],
            provider=row["provider"],
            request_count=int(row["request_count"]),
            total_input_tokens=int(row["total_input_tokens"]),
            total_output_tokens=int(row["total_output_tokens"]),
            total_cost_usd=float(row["total_cost"]),
        )
        for row in result
    ]


@router.get("/usage/by-tag", response_model=List[CostByTag])
async def get_costs_by_tag(
    token: TokenPayload = Depends(verify_token),
    tag_type: str = Query(
        "team",
        pattern="^(team|feature|customer|agent_id|workflow_id)$",
        description="Tag type: team, feature, customer, agent_id, workflow_id",
    ),
    days: int = Query(7, description="Number of days to look back"),
):
    """Get costs broken down by tag (viewer+ can access).

    agent_id / workflow_id are the economics-graph attribution dimensions —
    cost per agent and cost per workflow.
    """
    if tag_type == "customer":
        await require_feature("customers_view")(token=token)
    elif tag_type == "team":
        await require_feature("teams_view")(token=token)
    await require_role("viewer", token)

    days = clamp_days_by_plan(days, token.plan)
    cutoff = await parse_period(f"{days}d")

    # Use ClickHouse if streaming is enabled and it has a column for this tag.
    # agent_id / workflow_id live only in the Postgres `tags` JSONB, so they
    # skip straight to the query below rather than failing into the fallback.
    if settings.streaming_enabled and tag_type in CLICKHOUSE_TAG_COLUMNS:
        try:
            results = await get_spend_by_tag(
                str(token.workspace_id),
                tag_type,
                cutoff.date().isoformat(),
                datetime.utcnow().date().isoformat()
            )
            return [
                CostByTag(
                    tag=row["tag"],
                    request_count=row["request_count"],
                    total_cost_usd=row["total_cost_usd"],
                    total_input_tokens=row["total_input_tokens"],
                    total_output_tokens=row["total_output_tokens"],
                )
                for row in results
            ]
        except Exception as e:
            logger.warning("ClickHouse by-tag query failed, falling back to PostgreSQL: %s", e)

    result = await execute_query(
        """
        SELECT
            tags ->> $3 as tag_value,
            COUNT(*) as request_count,
            COALESCE(SUM(cost_usd), 0) as total_cost,
            COALESCE(SUM(input_tokens), 0) as total_input_tokens,
            COALESCE(SUM(output_tokens), 0) as total_output_tokens
        FROM request_records
        WHERE workspace_id = $1 AND ts >= $2 AND tags ->> $3 IS NOT NULL
        GROUP BY tag_value
        ORDER BY total_cost DESC
        """,
        str(token.workspace_id),
        cutoff,
        tag_type,
    )

    return [
        CostByTag(
            tag=row["tag_value"],
            request_count=int(row["request_count"]),
            total_cost_usd=float(row["total_cost"]),
            total_input_tokens=int(row["total_input_tokens"]),
            total_output_tokens=int(row["total_output_tokens"]),
        )
        for row in result
    ]


@router.get(
    "/usage/by-customer",
    response_model=List[CostByTag],
    dependencies=[Depends(require_feature("customers_view"))],
)
async def get_costs_by_customer(
    token: TokenPayload = Depends(verify_token),
    days: int = Query(7, description="Number of days to look back"),
):
    """Get costs broken down by customer tag (requires customers_view feature)."""
    return await get_costs_by_tag(token=token, tag_type="customer", days=days)


@router.get(
    "/usage/by-team",
    response_model=List[CostByTag],
    dependencies=[Depends(require_feature("teams_view"))],
)
async def get_costs_by_team(
    token: TokenPayload = Depends(verify_token),
    days: int = Query(7, description="Number of days to look back"),
):
    """Get costs broken down by team tag (requires teams_view feature)."""
    return await get_costs_by_tag(token=token, tag_type="team", days=days)


@router.get("/usage/by-feature", response_model=List[CostByTag])
async def get_costs_by_feature(
    token: TokenPayload = Depends(verify_token),
    days: int = Query(7, description="Number of days to look back"),
):
    """Get costs broken down by feature tag (viewer+ can access)."""
    return await get_costs_by_tag(token=token, tag_type="feature", days=days)


@router.get("/usage/timeseries", response_model=List[CostTimeline])
async def get_costs_timeline(
    token: TokenPayload = Depends(verify_token),
    days: int = Query(7, description="Number of days to look back"),
    granularity: str = Query("day", description="Granularity: day, hour"),
):
    """Get cost timeline (viewer+ can access)."""
    await require_role("viewer", token)

    days = clamp_days_by_plan(days, token.plan)
    cutoff = await parse_period(f"{days}d")

    # Use ClickHouse if streaming is enabled
    if settings.streaming_enabled:
        try:
            results = await get_spend_timeseries(
                str(token.workspace_id),
                cutoff.date().isoformat(),
                datetime.utcnow().date().isoformat()
            )
            return [
                CostTimeline(
                    date=row["date"],
                    request_count=row["request_count"],
                    total_cost_usd=row["total_cost_usd"],
                )
                for row in results
            ]
        except Exception as e:
            logger.warning("ClickHouse timeseries query failed, falling back to PostgreSQL: %s", e)

    # Group by date (UTC)
    result = await execute_query(
        """
        SELECT
            DATE(ts AT TIME ZONE 'UTC') as date,
            COUNT(*) as request_count,
            COALESCE(SUM(cost_usd), 0) as total_cost
        FROM request_records
        WHERE workspace_id = $1 AND ts >= $2
        GROUP BY DATE(ts AT TIME ZONE 'UTC')
        ORDER BY date ASC
        """,
        str(token.workspace_id),
        cutoff,
    )

    return [
        CostTimeline(
            date=str(row["date"]),
            request_count=int(row["request_count"]),
            total_cost_usd=float(row["total_cost"]),
        )
        for row in result
    ]


@router.get("/requests", response_model=List[RequestRecordResponse])
async def get_requests(
    token: TokenPayload = Depends(verify_token),
    limit: int = Query(50, ge=1, le=500, description="Max 500"),
    days: int = Query(7, description="Number of days to look back"),
):
    """Get recent requests (viewer+ can access)."""
    await require_role("viewer", token)

    days = clamp_days_by_plan(days, token.plan)

    cutoff = await parse_period(f"{days}d")

    result = await execute_query(
        """
        SELECT
            id, workspace_id, ts, provider, model,
            input_tokens, output_tokens, reasoning_tokens,
            cache_read_tokens, cache_write_tokens,
            cost_usd, duration_ms, status_code, tags,
            system_prompt_hash, received_at
        FROM request_records
        WHERE workspace_id = $1 AND ts >= $2
        ORDER BY ts DESC
        LIMIT $3
        """,
        str(token.workspace_id),
        cutoff,
        limit,
    )

    return [
        RequestRecordResponse(
            id=row["id"],
            workspace_id=str(row["workspace_id"]),
            timestamp=row["ts"],
            provider=row["provider"],
            model=row["model"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            reasoning_tokens=row["reasoning_tokens"],
            cache_read_tokens=row["cache_read_tokens"],
            cache_write_tokens=row["cache_write_tokens"],
            cost_usd=float(row["cost_usd"]),
            duration_ms=row["duration_ms"],
            status_code=row["status_code"],
            tags=row["tags"],
            system_prompt_hash=row["system_prompt_hash"],
            received_at=row["received_at"],
        )
        for row in result
    ]


# Run key, same order and reasoning as burnlens/analysis/runs.py: `session`
# first because ~all coding-agent traffic is scan-ingested and carries it, and
# scans can never carry a trace_id (no HTTP request, no traceparent header).
# trace_id is the fallback for OTEL-instrumented proxy users. Rows with neither
# are excluded rather than collapsed into one NULL run.
_RUN_KEY = "COALESCE(tags->>'session', trace_id)"

# The whole prompt, provider-aware. OpenAI/Google fold the cached share into
# input_tokens, so adding it back double-counts; Anthropic reports the two
# disjointly, so they must be summed. Assuming either shape is silently wrong
# for the other — a 12k prompt with 11k cached rendered as 23k before this.
_PROMPT_TOKENS = (
    "CASE WHEN provider IN ("
    + ", ".join(f"'{p}'" for p in INCLUSIVE_PROMPT_TOKEN_PROVIDERS)
    + ") THEN input_tokens ELSE input_tokens + cache_read_tokens END"
    " + cache_write_tokens"
)

# The uncached share. Raw input_tokens cannot be shown next to cached_tokens —
# for OpenAI/Google it IS the whole prompt, so it would read as 60,000 uncached
# beside 55,000 cached on a 60,000-token prompt. prompt = input + cached always.
_UNCACHED_INPUT = (
    "CASE WHEN provider IN ("
    + ", ".join(f"'{p}'" for p in INCLUSIVE_PROMPT_TOKEN_PROVIDERS)
    + ") THEN GREATEST(input_tokens - cache_read_tokens, 0) ELSE input_tokens END"
)

# Both aggregates read the same columns; prompt_tokens is input + cache reads +
# writes. Never surface input_tokens alone in a cost context: coding agents
# cache almost the whole prompt, so a $0.69 step reads as input_tokens=6.
_RUN_AGGREGATE = f"""
    SELECT {_RUN_KEY} AS run_id,
           COUNT(*) AS step_count,
           COALESCE(SUM(cost_usd), 0) AS cost_usd,
           COALESCE(SUM({_PROMPT_TOKENS}), 0) AS prompt_tokens,
           COALESCE(SUM(cache_read_tokens + cache_write_tokens), 0) AS cached_tokens,
           COALESCE(SUM({_UNCACHED_INPUT}), 0) AS input_tokens,
           COALESCE(SUM(output_tokens), 0) AS output_tokens,
           MIN(ts) AS started_at,
           MAX(ts) AS ended_at,
           array_agg(DISTINCT model) AS models,
           MAX(source) AS source,
           bool_or(tags->>'session' IS NOT NULL) AS by_session
      FROM request_records
     WHERE workspace_id = $1 AND ts >= $2 AND {_RUN_KEY} IS NOT NULL
"""


def _run_to_dict(row) -> dict:
    return {
        "run_id": row["run_id"],
        "step_count": int(row["step_count"]),
        "cost_usd": round(float(row["cost_usd"]), 6),
        "prompt_tokens": int(row["prompt_tokens"]),
        "cached_tokens": int(row["cached_tokens"]),
        "input_tokens": int(row["input_tokens"]),
        "output_tokens": int(row["output_tokens"]),
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "models": sorted(m for m in (row["models"] or []) if m),
        "source": row["source"],
        # Which key grouped this run: agent sessions vs OTEL traces.
        "key_kind": "session" if row["by_session"] else "trace",
    }


@router.get("/runs")
async def get_runs(
    token: TokenPayload = Depends(verify_token),
    days: int = Query(7, description="Number of days to look back"),
    limit: int = Query(20, ge=1, le=200),
    order: str = Query("cost", description="'cost' or 'recent'"),
):
    """Agent runs (or OTEL traces) in the window, costliest or most recent first.

    Empty until the workspace's proxy is >= 1.22.0 and has synced: no historical
    row carries a session tag, and there is no backfill. The UI must say so
    rather than rendering a convincing empty state.
    """
    await require_role("viewer", token)
    days = clamp_days_by_plan(days, token.plan)
    cutoff = await parse_period(f"{days}d")

    order_by = "MAX(ts) DESC" if order == "recent" else "SUM(cost_usd) DESC"
    rows = await execute_query(
        f"{_RUN_AGGREGATE} GROUP BY run_id ORDER BY {order_by} LIMIT $3",
        str(token.workspace_id),
        cutoff,
        limit,
    )
    return [_run_to_dict(r) for r in rows]


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    token: TokenPayload = Depends(verify_token),
    days: int = Query(7, description="Number of days to look back"),
):
    """One run and its steps in time order. 404 if the id matches nothing.

    `workspace_id = $1` on both queries is what keeps a guessed run id from
    reading another tenant's steps.
    """
    await require_role("viewer", token)
    days = clamp_days_by_plan(days, token.plan)
    cutoff = await parse_period(f"{days}d")

    rows = await execute_query(
        f"{_RUN_AGGREGATE} AND {_RUN_KEY} = $3 GROUP BY run_id",
        str(token.workspace_id),
        cutoff,
        run_id,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Run not found")

    steps = await execute_query(
        f"""
        SELECT ts, model,
               {_PROMPT_TOKENS} AS prompt_tokens,
               cache_read_tokens + cache_write_tokens AS cached_tokens,
               {_UNCACHED_INPUT} AS input_tokens, output_tokens, cost_usd,
               duration_ms, status_code, parent_span_id
          FROM request_records
         WHERE workspace_id = $1 AND ts >= $2 AND {_RUN_KEY} = $3
         ORDER BY ts
        """,
        # Same window as the aggregate: a run straddling the boundary would
        # otherwise list steps its own totals do not account for.
        str(token.workspace_id),
        cutoff,
        run_id,
    )

    return {
        "run": _run_to_dict(rows[0]),
        "steps": [
            {
                "timestamp": s["ts"],
                "model": s["model"],
                "prompt_tokens": int(s["prompt_tokens"] or 0),
                "cached_tokens": int(s["cached_tokens"] or 0),
                "input_tokens": int(s["input_tokens"] or 0),
                "output_tokens": int(s["output_tokens"] or 0),
                "cost_usd": round(float(s["cost_usd"] or 0), 6),
                "duration_ms": s["duration_ms"],
                "status_code": s["status_code"],
                # Present only for OTEL callers; shown, not used for nesting.
                "parent_span_id": s["parent_span_id"],
            }
            for s in steps
        ],
    }


# GET /waste-alerts lives on findings_api.router (BL-F1). The stub that
# returned [] is gone; do not re-add it here.


def _budget_forecast(
    spent_usd: float,
    elapsed_days_frac: float,
    period_days: int,
    budget_usd: Optional[float],
) -> dict:
    """Pure forecast math for the monthly spend budget. Kept side-effect-free so
    it's unit-testable without a DB or the request cycle.

    `forecast_usd` is a naive linear run-rate: spend-so-far scaled to the full
    month. The pace alarm (`is_on_pace_to_exceed`) is suppressed until a full day
    of data exists, so an hour-1 spike doesn't cry wolf.
    # ponytail: linear run-rate; swap for a trailing-window/EWMA projection only
    # if first-days forecasts prove too noisy in practice.
    """
    if elapsed_days_frac > 0:
        forecast_usd = spent_usd / elapsed_days_frac * period_days
    else:
        forecast_usd = spent_usd

    if budget_usd and budget_usd > 0:
        remaining_usd: Optional[float] = max(0.0, budget_usd - spent_usd)
        pct_used: Optional[float] = round(spent_usd / budget_usd * 100, 1)
        is_over_budget = spent_usd >= budget_usd
        is_on_pace_to_exceed = (
            not is_over_budget
            and elapsed_days_frac >= 1.0
            and forecast_usd > budget_usd
        )
    else:
        remaining_usd = None
        pct_used = None
        is_over_budget = False
        is_on_pace_to_exceed = False

    return {
        "budget_usd": float(budget_usd) if budget_usd else None,
        "spent_usd": round(spent_usd, 2),
        "remaining_usd": round(remaining_usd, 2) if remaining_usd is not None else None,
        "forecast_usd": round(forecast_usd, 2),
        "pct_used": pct_used,
        "is_over_budget": is_over_budget,
        "is_on_pace_to_exceed": is_on_pace_to_exceed,
        "period_days": period_days,
        "elapsed_days": int(elapsed_days_frac),
    }


@router.get("/budget")
async def get_budget(token: TokenPayload = Depends(verify_token)):
    """Monthly spend budget + linear burn-rate forecast for the workspace.

    Spend is summed over the current UTC calendar month, matching the *monthly*
    semantics of `monthly_spend_cap_usd` (the cap `ingest.py` already enforces).
    """
    await require_role("viewer", token)
    workspace_id = str(token.workspace_id)

    now = datetime.now(tz.UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    period_days = monthrange(now.year, now.month)[1]
    elapsed_days_frac = (now - month_start).total_seconds() / 86400.0

    spend_rows = await execute_query(
        """
        SELECT COALESCE(SUM(cost_usd), 0) AS spent
        FROM request_records
        WHERE workspace_id = $1 AND ts >= $2
        """,
        workspace_id,
        month_start,
    )
    spent_usd = float(spend_rows[0]["spent"]) if spend_rows else 0.0

    # A limits-resolution failure must not 500 the budget page — degrade to
    # "no budget set" (the forecast still renders on spend alone).
    budget_usd = None
    try:
        resolved = await resolve_limits(token.workspace_id)
        if resolved and resolved.monthly_spend_cap_usd is not None:
            budget_usd = float(resolved.monthly_spend_cap_usd)
    except Exception:
        logger.warning("resolve_limits failed in get_budget; forecasting without a budget", exc_info=True)

    return _budget_forecast(spent_usd, elapsed_days_frac, period_days, budget_usd)


@router.get("/team-budgets", response_model=List[TeamBudgetRow])
async def get_team_budgets(token: TokenPayload = Depends(verify_token)):
    """Month-to-date spend per team vs the budgets set via PUT /settings/team-budget.

    Teams without a configured budget are omitted. Display/alerting only —
    the workspace-level cap is what ingest enforces.
    """
    await require_role("viewer", token)
    workspace_id = str(token.workspace_id)

    override_rows = await execute_query(
        "SELECT limit_overrides->'team_budgets' AS tb FROM workspaces WHERE id = $1",
        workspace_id,
    )
    budgets = (override_rows[0]["tb"] if override_rows else None) or {}
    if not budgets:
        return []

    month_start = datetime.now(tz.UTC).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    spend_rows = await execute_query(
        """
        SELECT COALESCE(tags->>'team', '(untagged)') AS team,
               COALESCE(SUM(cost_usd), 0) AS spent
        FROM request_records
        WHERE workspace_id = $1 AND ts >= $2
        GROUP BY 1
        """,
        workspace_id,
        month_start,
    )
    spent_by_team = {r["team"]: float(r["spent"]) for r in (spend_rows or [])}

    out: List[TeamBudgetRow] = []
    for team, limit in budgets.items():
        limit_f = float(limit)
        if limit_f <= 0:
            continue
        spent = spent_by_team.get(team, 0.0)
        pct = spent / limit_f * 100
        status = "EXCEEDED" if pct >= 100 else "WARNING" if pct >= 80 else "OK"
        out.append(TeamBudgetRow(
            team=team,
            spent=round(spent, 2),
            limit=limit_f,
            pct_used=round(pct, 1),
            status=status,
        ))
    out.sort(key=lambda r: r.pct_used, reverse=True)
    return out


@router.get("/recommendations", response_model=List[RecommendationItem])
async def get_recommendations(
    token: TokenPayload = Depends(verify_token),
    days: int = Query(30, description="Number of days to look back"),
):
    """Model-switch recommendations from the canonical Python engine."""
    await require_role("viewer", token)
    days = clamp_days_by_plan(days, token.plan)
    cutoff = datetime.now(tz.UTC) - timedelta(days=days)

    from .findings import recommendations_from_records, records_to_detector_dicts

    rows = await execute_query(
        """
        SELECT model, input_tokens, output_tokens, reasoning_tokens,
               cost_usd, tags, ts
          FROM request_records
         WHERE workspace_id = $1 AND ts >= $2
        """,
        str(token.workspace_id),
        cutoff,
    )

    # A recommender failure must not 500 the savings page — degrade to "no
    # recommendations" (the page renders its empty state).
    try:
        return recommendations_from_records(records_to_detector_dicts(rows or []))
    except Exception:
        logger.warning("recommendation computation failed; returning []", exc_info=True)
        return []


@router.get(
    "/customers",
    response_model=List[dict],
    dependencies=[Depends(require_feature("customers_view"))],
)
async def get_customers(token: TokenPayload = Depends(verify_token)):
    """Get cost by customer (from tags) (requires customers_view feature)."""
    # Use ClickHouse if streaming is enabled
    if settings.streaming_enabled:
        try:
            # Look back 30 days for customers list by default
            cutoff = datetime.now(tz.UTC) - timedelta(days=30)
            results = await get_spend_by_tag(
                str(token.workspace_id),
                "customer",
                cutoff.date().isoformat(),
                datetime.utcnow().date().isoformat()
            )
            return [
                {
                    "customer": row["tag"],
                    "request_count": row["request_count"],
                    "input_tokens": row["total_input_tokens"],
                    "output_tokens": row["total_output_tokens"],
                    "total_cost": row["total_cost_usd"],
                }
                for row in results
            ]
        except Exception as e:
            logger.warning("ClickHouse customers query failed, falling back to PostgreSQL: %s", e)

    result = await execute_query(
        """
        SELECT
            tags ->> 'customer' as customer,
            COUNT(*) as request_count,
            COALESCE(SUM(input_tokens), 0) as input_tokens,
            COALESCE(SUM(output_tokens), 0) as output_tokens,
            COALESCE(SUM(cost_usd), 0) as total_cost
        FROM request_records
        WHERE workspace_id = $1 AND tags ->> 'customer' IS NOT NULL
        GROUP BY customer
        ORDER BY total_cost DESC
        """,
        str(token.workspace_id),
    )

    return [
        {
            "customer": row["customer"],
            "request_count": int(row["request_count"]),
            "input_tokens": int(row["input_tokens"]),
            "output_tokens": int(row["output_tokens"]),
            "total_cost": float(row["total_cost"]),
        }
        for row in result
    ]
