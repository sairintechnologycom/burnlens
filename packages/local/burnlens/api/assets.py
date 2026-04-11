"""FastAPI router for asset management endpoints.

Provides CRUD-style endpoints for listing, filtering, viewing, updating,
approving, and summarising AI assets discovered by BurnLens.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from burnlens.api.schemas import (
    AssetApproveResponse,
    AssetListResponse,
    AssetResponse,
    AssetSummaryResponse,
    AssetUpdateRequest,
    asset_to_response,
    event_to_response,
)
from burnlens.storage.database import insert_discovery_event, update_asset_status
from burnlens.storage.models import DiscoveryEvent
from burnlens.storage.queries import (
    get_asset_by_id,
    get_asset_summary,
    get_assets,
    get_assets_count,
    get_discovery_events,
    update_asset_fields,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["assets"])


# ---------------------------------------------------------------------------
# GET /summary — MUST come before /{asset_id} to avoid path conflict
# ---------------------------------------------------------------------------


@router.get("/summary", response_model=AssetSummaryResponse)
async def get_summary(request: Request) -> AssetSummaryResponse:
    """Return aggregated asset counts for the summary dashboard widget.

    Returns total, by_provider, by_status, by_risk_tier, and new_this_week.
    """
    db_path: str = request.app.state.db_path
    summary = await get_asset_summary(db_path)
    return AssetSummaryResponse(**summary)


# ---------------------------------------------------------------------------
# GET / — list assets with filters and pagination
# ---------------------------------------------------------------------------


@router.get("", response_model=AssetListResponse)
async def list_assets(
    request: Request,
    provider: str | None = None,
    status: str | None = None,
    owner_team: str | None = None,
    risk_tier: str | None = None,
    date_since: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> AssetListResponse:
    """Return a paginated list of AI assets with optional filters.

    Filters are applied only when the corresponding query parameter is provided.
    Supports pagination via limit and offset. date_since is an ISO date string
    (e.g. '2026-01-01') that filters on first_seen_at. search performs an OR
    LIKE search across model_name, provider, owner_team, endpoint_url, and tags.
    """
    db_path: str = request.app.state.db_path

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

    return AssetListResponse(
        items=[asset_to_response(a) for a in assets],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# GET /shadow — list shadow/unregistered AI endpoints
# ---------------------------------------------------------------------------


@router.get("/shadow", response_model=AssetListResponse)
async def list_shadow_assets(
    request: Request,
    date_since: str | None = None,
    date_until: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> AssetListResponse:
    """List shadow/unregistered AI endpoints requiring review.

    Convenience endpoint equivalent to GET /assets?status=shadow with
    additional date_until filter. Supports filtering by detection date range.
    """
    db_path: str = request.app.state.db_path

    assets = await get_assets(
        db_path,
        status="shadow",
        date_since=date_since,
        limit=limit,
        offset=offset,
    )
    total = await get_assets_count(
        db_path,
        status="shadow",
        date_since=date_since,
    )

    # Apply date_until filter in-memory (first_seen_at <= date_until)
    if date_until is not None:
        assets = [a for a in assets if a.first_seen_at.isoformat() <= date_until]
        # Recount after filtering
        total = min(total, len(assets))

    return AssetListResponse(
        items=[asset_to_response(a) for a in assets],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# GET /{asset_id} — single asset detail with recent discovery events
# ---------------------------------------------------------------------------


@router.get("/{asset_id}", response_model=dict)
async def get_asset_detail(request: Request, asset_id: int) -> dict[str, Any]:
    """Return full asset detail including recent discovery events.

    Returns 404 if no asset with the given id exists.
    """
    db_path: str = request.app.state.db_path

    asset = await get_asset_by_id(db_path, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

    events = await get_discovery_events(db_path, asset_id=asset_id, limit=20)

    return {
        "asset": asset_to_response(asset).model_dump(),
        "events": [event_to_response(e).model_dump() for e in events],
    }


# ---------------------------------------------------------------------------
# PATCH /{asset_id} — update asset fields
# ---------------------------------------------------------------------------


@router.patch("/{asset_id}", response_model=AssetResponse)
async def patch_asset(
    request: Request,
    asset_id: int,
    body: AssetUpdateRequest,
) -> AssetResponse:
    """Update specified fields of an AI asset.

    Only non-None fields from the request body are applied. updated_at is
    always refreshed. Returns 404 if no asset with the given id exists.
    """
    db_path: str = request.app.state.db_path

    try:
        updated = await update_asset_fields(
            db_path,
            asset_id,
            owner_team=body.owner_team,
            risk_tier=body.risk_tier,
            tags=body.tags,
            status=body.status,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

    return asset_to_response(updated)


# ---------------------------------------------------------------------------
# POST /{asset_id}/approve — transition shadow → approved
# ---------------------------------------------------------------------------


@router.post("/{asset_id}/approve", response_model=AssetApproveResponse)
async def approve_asset(request: Request, asset_id: int) -> AssetApproveResponse:
    """Approve a shadow asset, transitioning its status to 'approved'.

    Returns 404 if the asset does not exist.
    Returns 409 if the asset is not in 'shadow' status.
    Creates a discovery_event recording the approval.
    """
    db_path: str = request.app.state.db_path

    asset = await get_asset_by_id(db_path, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

    if asset.status != "shadow":
        raise HTTPException(
            status_code=409,
            detail="Asset is not in shadow status",
        )

    # Transition status and auto-log the status-change event
    await update_asset_status(db_path, asset_id, "approved")

    # Insert an additional explicit approval event for auditability
    event = DiscoveryEvent(
        event_type="model_changed",
        asset_id=asset_id,
        details={
            "change": "approved",
            "old_status": "shadow",
            "new_status": "approved",
        },
        detected_at=datetime.utcnow(),
    )
    event_id = await insert_discovery_event(db_path, event)

    # Fetch the refreshed asset
    updated = await get_asset_by_id(db_path, asset_id)
    assert updated is not None  # update_asset_status would have raised if missing

    return AssetApproveResponse(
        asset=asset_to_response(updated),
        event_id=event_id,
    )
