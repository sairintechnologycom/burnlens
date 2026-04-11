"""Usage query endpoints — summary, timeseries, breakdowns by model/team/feature."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from burnlens_cloud.api.auth import get_current_org, rate_limit
from burnlens_cloud.db.engine import get_db
from burnlens_cloud.db.models import Organization, RequestLog

router = APIRouter(prefix="/api/v1/usage", tags=["usage"])


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


@router.get("/summary")
async def usage_summary(
    days: int = Query(30, ge=1, le=365),
    org: Organization = Depends(rate_limit),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Aggregate usage summary for the authenticated org."""
    since = _since(days)

    # Totals
    totals = await db.execute(
        select(
            func.coalesce(func.sum(RequestLog.cost_usd), 0).label("total_cost"),
            func.coalesce(
                func.sum(RequestLog.input_tokens + RequestLog.output_tokens), 0
            ).label("total_tokens"),
            func.count().label("total_calls"),
        ).where(
            RequestLog.org_id == org.id,
            RequestLog.timestamp >= since,
        )
    )
    row = totals.one()

    # By provider
    by_provider_q = await db.execute(
        select(
            RequestLog.provider,
            func.sum(RequestLog.cost_usd).label("total_cost"),
            func.count().label("api_calls"),
        )
        .where(RequestLog.org_id == org.id, RequestLog.timestamp >= since)
        .group_by(RequestLog.provider)
        .order_by(func.sum(RequestLog.cost_usd).desc())
    )
    by_provider = [
        {"provider": r.provider, "total_cost": float(r.total_cost), "api_calls": r.api_calls}
        for r in by_provider_q.all()
    ]

    # By model
    by_model_q = await db.execute(
        select(
            RequestLog.provider,
            RequestLog.model,
            func.sum(RequestLog.cost_usd).label("total_cost"),
            func.count().label("api_calls"),
        )
        .where(RequestLog.org_id == org.id, RequestLog.timestamp >= since)
        .group_by(RequestLog.provider, RequestLog.model)
        .order_by(func.sum(RequestLog.cost_usd).desc())
        .limit(20)
    )
    by_model = [
        {
            "provider": r.provider,
            "model": r.model,
            "total_cost": float(r.total_cost),
            "api_calls": r.api_calls,
        }
        for r in by_model_q.all()
    ]

    return {
        "total_cost": float(row.total_cost),
        "total_tokens": int(row.total_tokens),
        "total_calls": int(row.total_calls),
        "total_requests": int(row.total_calls),
        "by_provider": by_provider,
        "by_model": by_model,
    }


@router.get("/timeseries")
async def usage_timeseries(
    days: int = Query(30, ge=1, le=365),
    org: Organization = Depends(rate_limit),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Daily cost timeseries for the authenticated org."""
    since = _since(days)

    rows = await db.execute(
        select(
            func.date_trunc("day", RequestLog.timestamp).label("day"),
            RequestLog.provider,
            func.sum(RequestLog.cost_usd).label("cost"),
            func.sum(RequestLog.input_tokens + RequestLog.output_tokens).label("tokens"),
            func.count().label("calls"),
        )
        .where(RequestLog.org_id == org.id, RequestLog.timestamp >= since)
        .group_by(text("1"), RequestLog.provider)
        .order_by(text("1"))
    )

    return [
        {
            "date": r.day.strftime("%Y-%m-%d"),
            "provider": r.provider,
            "cost": float(r.cost),
            "tokens": int(r.tokens),
            "calls": int(r.calls),
        }
        for r in rows.all()
    ]


@router.get("/by-model")
async def usage_by_model(
    days: int = Query(30, ge=1, le=365),
    org: Organization = Depends(rate_limit),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Cost breakdown by model."""
    since = _since(days)

    rows = await db.execute(
        select(
            RequestLog.provider,
            RequestLog.model,
            func.sum(RequestLog.cost_usd).label("total_cost"),
            func.sum(RequestLog.input_tokens).label("input_tokens"),
            func.sum(RequestLog.output_tokens).label("output_tokens"),
            func.count().label("api_calls"),
            func.avg(RequestLog.duration_ms).label("avg_latency_ms"),
        )
        .where(RequestLog.org_id == org.id, RequestLog.timestamp >= since)
        .group_by(RequestLog.provider, RequestLog.model)
        .order_by(func.sum(RequestLog.cost_usd).desc())
    )

    return [
        {
            "provider": r.provider,
            "model": r.model,
            "total_cost": float(r.total_cost),
            "input_tokens": int(r.input_tokens),
            "output_tokens": int(r.output_tokens),
            "api_calls": int(r.api_calls),
            "avg_latency_ms": float(r.avg_latency_ms) if r.avg_latency_ms else None,
        }
        for r in rows.all()
    ]


@router.get("/by-team")
async def usage_by_team(
    days: int = Query(30, ge=1, le=365),
    org: Organization = Depends(rate_limit),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Cost breakdown by team tag. Requires team tier or above."""
    if org.tier == "free":
        raise HTTPException(
            status_code=402,
            detail="Team breakdown requires a paid plan. Upgrade at /settings.",
        )

    since = _since(days)

    rows = await db.execute(
        select(
            RequestLog.tag_team,
            func.sum(RequestLog.cost_usd).label("total_cost"),
            func.count().label("api_calls"),
        )
        .where(
            RequestLog.org_id == org.id,
            RequestLog.timestamp >= since,
            RequestLog.tag_team.is_not(None),
        )
        .group_by(RequestLog.tag_team)
        .order_by(func.sum(RequestLog.cost_usd).desc())
    )

    return [
        {"team": r.tag_team, "total_cost": float(r.total_cost), "api_calls": int(r.api_calls)}
        for r in rows.all()
    ]


@router.get("/by-feature")
async def usage_by_feature(
    days: int = Query(30, ge=1, le=365),
    org: Organization = Depends(rate_limit),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Cost breakdown by feature tag."""
    since = _since(days)

    rows = await db.execute(
        select(
            RequestLog.tag_feature,
            func.sum(RequestLog.cost_usd).label("total_cost"),
            func.count().label("api_calls"),
        )
        .where(
            RequestLog.org_id == org.id,
            RequestLog.timestamp >= since,
            RequestLog.tag_feature.is_not(None),
        )
        .group_by(RequestLog.tag_feature)
        .order_by(func.sum(RequestLog.cost_usd).desc())
    )

    return [
        {"feature": r.tag_feature, "total_cost": float(r.total_cost), "api_calls": int(r.api_calls)}
        for r in rows.all()
    ]
