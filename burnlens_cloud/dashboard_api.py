import logging
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from dateutil import tz

from .auth import verify_token, TokenPayload
from .config import settings
from .database import execute_query
from .models import (
    StatsSummary,
    CostByModel,
    CostByTag,
    CostTimeline,
    RequestRecordResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["dashboard"])

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


@router.get("/summary", response_model=StatsSummary)
async def get_summary(
    token: TokenPayload = Depends(verify_token),
    period: str = Query("7d", description="Period: 7d, 30d, 90d, etc."),
):
    """Get cost summary for workspace (viewer+ can access)."""
    await require_role("viewer", token)

    days = int(period[:-1]) if period.endswith("d") else 7
    days = clamp_days_by_plan(days, token.plan)

    cutoff = await parse_period(f"{days}d")

    result = await execute_query(
        """
        SELECT
            COALESCE(SUM(cost_usd), 0) as total_cost,
            COUNT(*) as request_count,
            COUNT(DISTINCT model) as model_count,
            COALESCE(AVG(cost_usd), 0) as avg_cost
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
    )


@router.get("/costs/by-model", response_model=List[CostByModel])
async def get_costs_by_model(
    token: TokenPayload = Depends(verify_token),
    period: str = Query("7d", description="Period: 7d, 30d, 90d, etc."),
):
    """Get costs broken down by model (viewer+ can access)."""
    await require_role("viewer", token)

    days = int(period[:-1]) if period.endswith("d") else 7
    days = clamp_days_by_plan(days, token.plan)

    cutoff = await parse_period(f"{days}d")

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


@router.get("/costs/by-tag", response_model=List[CostByTag])
async def get_costs_by_tag(
    token: TokenPayload = Depends(verify_token),
    tag_type: str = Query("team", description="Tag type: team, feature, customer"),
    period: str = Query("7d", description="Period: 7d, 30d, 90d, etc."),
):
    """Get costs broken down by tag (team, feature, customer) (viewer+ can access)."""
    await require_role("viewer", token)

    days = int(period[:-1]) if period.endswith("d") else 7
    days = clamp_days_by_plan(days, token.plan)

    cutoff = await parse_period(f"{days}d")

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


@router.get("/costs/timeline", response_model=List[CostTimeline])
async def get_costs_timeline(
    token: TokenPayload = Depends(verify_token),
    period: str = Query("7d", description="Period: 7d, 30d, 90d, etc."),
    granularity: str = Query("daily", description="Granularity: daily, hourly"),
):
    """Get cost timeline (viewer+ can access)."""
    await require_role("viewer", token)

    days = int(period[:-1]) if period.endswith("d") else 7
    days = clamp_days_by_plan(days, token.plan)

    cutoff = await parse_period(f"{days}d")

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
    period: str = Query("7d", description="Period: 7d, 30d, 90d, etc."),
):
    """Get recent requests (viewer+ can access)."""
    await require_role("viewer", token)

    days = int(period[:-1]) if period.endswith("d") else 7
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


@router.get("/waste")
async def get_waste_alerts(token: TokenPayload = Depends(verify_token)):
    """Get waste detection findings (stub for MVP)."""
    return {
        "findings": [
            {
                "detector": "duplicate_prompts",
                "severity": "medium",
                "title": "Duplicate system prompts",
                "description": "Same system prompt sent 5 times",
                "estimated_waste_usd": 0.15,
                "affected_count": 5,
            }
        ]
    }


@router.get("/budget")
async def get_budget(token: TokenPayload = Depends(verify_token)):
    """Get budget status (stub for MVP)."""
    return {
        "budget_usd": None,
        "spent_usd": 0.0,
        "remaining_usd": None,
        "forecast_usd": None,
        "pct_used": 0.0,
        "is_over_budget": False,
        "is_on_pace_to_exceed": False,
        "period_days": 30,
        "elapsed_days": 0,
    }


@router.get("/customers", response_model=List[dict])
async def get_customers(token: TokenPayload = Depends(verify_token)):
    """Get cost by customer (from tags)."""
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
