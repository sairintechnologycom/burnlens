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
    get_spend_summary,
    get_spend_by_model,
    get_spend_by_tag,
    get_spend_timeseries,
)
from .models import (
    StatsSummary,
    CostByModel,
    CostByTag,
    CostTimeline,
    RecommendationItem,
    RequestRecordResponse,
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
    tag_type: str = Query("team", pattern="^(team|feature|customer)$", description="Tag type: team, feature, customer"),
    days: int = Query(7, description="Number of days to look back"),
):
    """Get costs broken down by tag (team, feature, customer) (viewer+ can access)."""
    if tag_type == "customer":
        await require_feature("customers_view")(token=token)
    elif tag_type == "team":
        await require_feature("teams_view")(token=token)
    await require_role("viewer", token)

    days = clamp_days_by_plan(days, token.plan)
    cutoff = await parse_period(f"{days}d")

    # Use ClickHouse if streaming is enabled
    if settings.streaming_enabled:
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
        f"""
        SELECT
            tags ->> '{tag_type}' as tag_value,
            COUNT(*) as request_count,
            COALESCE(SUM(cost_usd), 0) as total_cost,
            COALESCE(SUM(input_tokens), 0) as total_input_tokens,
            COALESCE(SUM(output_tokens), 0) as total_output_tokens
        FROM request_records
        WHERE workspace_id = $1 AND ts >= $2 AND tags ->> '{tag_type}' IS NOT NULL
        GROUP BY tag_value
        ORDER BY total_cost DESC
        """,
        str(token.workspace_id),
        cutoff,
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


@router.get("/waste-alerts")
async def get_waste_alerts(token: TokenPayload = Depends(verify_token)):
    """Get waste detection findings (stub for MVP)."""
    return []


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


def _model_overkill_recs(rows: list[dict]) -> List[RecommendationItem]:
    """Apply the OSS recommender's model-overkill rule to aggregated rows.

    Reuses burnlens.analysis.recommender's downgrade map, thresholds, and
    pricing projection so the SaaS and local dashboards give the same advice.
    """
    # ponytail: Rule 1 (model overkill) only — reasoning-overkill and
    # cache-opportunity rules need per-request data; port them if asked.
    from burnlens.analysis.recommender import (
        _CHEAPER_EQUIVALENT,
        _match_overkill_model,
        _project_cost,
    )

    recs: List[RecommendationItem] = []
    for row in rows:
        model = row["model"]
        matched_key = _match_overkill_model(model)
        if matched_key is None:
            continue
        avg_out = float(row["avg_output_tokens"] or 0)
        count = int(row["request_count"])
        if avg_out >= 200 or count <= 20:
            continue
        suggested = _CHEAPER_EQUIVALENT[matched_key]
        avg_in = float(row["avg_input_tokens"] or 0)
        current_cost = float(row["total_cost"] or 0)
        projected = _project_cost(count, avg_in, avg_out, suggested)
        if projected is None:
            continue
        saving = current_cost - projected
        pct = (saving / current_cost * 100) if current_cost > 0 else 0.0
        recs.append(RecommendationItem(
            current_model=model,
            suggested_model=suggested,
            feature_tag=row["feature_tag"],
            request_count=count,
            avg_output_tokens=round(avg_out, 1),
            current_cost=round(current_cost, 6),
            projected_cost=round(projected, 6),
            projected_saving=round(saving, 6),
            saving_pct=round(pct, 1),
            confidence="high" if avg_out < 50 else "medium",
            reason=(
                f"Average output is only {avg_out:.0f} tokens across {count} requests "
                f"— {suggested} can handle short tasks at a fraction of the cost"
            ),
        ))
    recs.sort(key=lambda r: r.projected_saving, reverse=True)
    return recs


@router.get("/recommendations", response_model=List[RecommendationItem])
async def get_recommendations(
    token: TokenPayload = Depends(verify_token),
    days: int = Query(30, description="Number of days to look back"),
):
    """Model-switch recommendations computed from workspace usage."""
    await require_role("viewer", token)
    days = clamp_days_by_plan(days, token.plan)
    cutoff = datetime.now(tz.UTC) - timedelta(days=days)

    rows = await execute_query(
        """
        SELECT
            model,
            COALESCE(tags->>'feature', '(untagged)') AS feature_tag,
            COUNT(*) AS request_count,
            AVG(input_tokens)  AS avg_input_tokens,
            AVG(output_tokens) AS avg_output_tokens,
            SUM(cost_usd)      AS total_cost
        FROM request_records
        WHERE workspace_id = $1 AND ts >= $2
        GROUP BY model, feature_tag
        """,
        str(token.workspace_id),
        cutoff,
    )

    # A recommender failure must not 500 the savings page — degrade to "no
    # recommendations" (the page renders its empty state).
    try:
        return _model_overkill_recs(rows or [])
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
