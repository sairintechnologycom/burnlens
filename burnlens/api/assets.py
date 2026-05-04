"""Asset management API endpoints."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from burnlens.config import load_config
from burnlens.storage.models import AiAsset
from burnlens.storage.queries import (
    get_asset_by_id,
    get_asset_summary,
    get_assets,
    get_assets_count,
    get_discovery_events,
    update_asset_fields,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _db_path(request: Request) -> str:
    """Use app.state.db_path (tests) or fall back to config (production)."""
    state_path = getattr(request.app.state, "db_path", None)
    return state_path if state_path else load_config().db_path


def _asset_to_dict(a: AiAsset) -> dict[str, Any]:
    return {
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


@router.get("")
async def list_assets_endpoint(
    db_path: str = Depends(_db_path),
    status: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    risk_tier: str | None = Query(default=None),
    owner_team: str | None = Query(default=None),
    search: str | None = Query(default=None),
    date_since: str | None = Query(default=None, description="ISO date filter, e.g. 2026-01-01"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="first_seen_at"),
    sort_dir: str = Query(default="desc"),
) -> dict:
    """List AI assets with filtering, sorting, and pagination."""
    if date_since is not None:
        try:
            date.fromisoformat(date_since)
        except ValueError:
            raise HTTPException(status_code=422, detail="date_since must be an ISO date (YYYY-MM-DD)")
    assets = await get_assets(
        db_path,
        provider=provider,
        status=status,
        owner_team=owner_team,
        risk_tier=risk_tier,
        date_since=date_since,
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
        date_since=date_since,
        search_query=search,
    )
    return {
        "items": [_asset_to_dict(a) for a in assets],
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
    }


@router.get("/summary")
async def assets_summary_endpoint(db_path: str = Depends(_db_path)) -> dict:
    """Return aggregated KPI summary across all assets."""
    return await get_asset_summary(db_path)


@router.get("/{asset_id}")
async def get_asset_detail(asset_id: int, db_path: str = Depends(_db_path)) -> dict:
    """Return a single asset with its discovery events."""
    asset = await get_asset_by_id(db_path, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    events = await get_discovery_events(db_path, asset_id=asset_id)
    return {
        "asset": _asset_to_dict(asset),
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "asset_id": e.asset_id,
                "details": e.details,
                "detected_at": e.detected_at.isoformat(),
            }
            for e in events
        ],
    }


class AssetPatchRequest(BaseModel):
    owner_team: str | None = None
    risk_tier: str | None = None
    status: str | None = None
    tags: dict[str, Any] | None = None


@router.patch("/{asset_id}")
async def patch_asset(
    asset_id: int,
    body: AssetPatchRequest,
    db_path: str = Depends(_db_path),
) -> dict:
    """Update asset fields (owner_team, risk_tier, status, tags)."""
    try:
        asset = await update_asset_fields(
            db_path,
            asset_id=asset_id,
            owner_team=body.owner_team,
            risk_tier=body.risk_tier,
            status=body.status,
            tags=body.tags,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Asset not found")
    return _asset_to_dict(asset)


@router.post("/{asset_id}/approve")
async def approve_asset(asset_id: int, db_path: str = Depends(_db_path)) -> dict:
    """Approve a shadow asset. Returns 409 if already approved."""
    asset = await get_asset_by_id(db_path, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset.status == "approved":
        raise HTTPException(status_code=409, detail="Asset is already approved")
    updated = await update_asset_fields(db_path, asset_id=asset_id, status="approved")
    events = await get_discovery_events(
        db_path, asset_id=asset_id, event_type="model_changed", limit=1
    )
    event_id = events[0].id if events else None
    return {"asset": _asset_to_dict(updated), "event_id": event_id}
