"""GET /api/v1/assets endpoint with server-side sorting and pagination."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from burnlens.config import load_config
from burnlens.storage.queries import get_assets, get_assets_count

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/v1/assets")
async def list_assets_endpoint(
    status: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    risk_tier: str | None = Query(default=None),
    owner_team: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(
        default="first_seen_at",
        description="Sort column. One of: first_seen_at, last_active_at, "
                    "monthly_spend_usd, monthly_requests, model_name, provider, "
                    "owner_team, status, risk_tier",
    ),
    sort_dir: str = Query(default="desc", description="asc or desc"),
) -> dict:
    """List AI assets with filtering, sorting, and pagination."""
    cfg = load_config()
    db_path = cfg.db_path

    assets = await get_assets(
        db_path,
        provider=provider,
        status=status,
        owner_team=owner_team,
        risk_tier=risk_tier,
        search_query=search,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )

    total = await get_assets_count(
        db_path,
        provider=provider,
        status=status,
        owner_team=owner_team,
        risk_tier=risk_tier,
        search_query=search,
    )

    return {
        "assets": [
            {
                "id": a.id,
                "provider": a.provider,
                "model_name": a.model_name,
                "endpoint_url": a.endpoint_url,
                "owner_team": a.owner_team,
                "project": a.project,
                "status": a.status,
                "risk_tier": a.risk_tier,
                "first_seen_at": a.first_seen_at.isoformat(),
                "last_active_at": a.last_active_at.isoformat(),
                "monthly_spend_usd": a.monthly_spend_usd,
                "monthly_requests": a.monthly_requests,
            }
            for a in assets
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
    }
