"""FastAPI router for discovery event endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

from burnlens.api.schemas import DiscoveryEventListResponse, event_to_response
from burnlens.storage.queries import get_discovery_events

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.get("/events", response_model=DiscoveryEventListResponse)
async def list_discovery_events(
    request: Request,
    event_type: Optional[str] = Query(default=None, description="Filter by event type"),
    asset_id: Optional[int] = Query(default=None, description="Filter by asset ID"),
    since: Optional[str] = Query(default=None, description="Filter events detected at or after this ISO date (e.g. 2026-01-01)"),
    until: Optional[str] = Query(default=None, description="Filter events detected at or before this ISO date (e.g. 2026-12-31)"),
    limit: int = Query(default=50, ge=1, le=500, description="Maximum number of events to return"),
) -> DiscoveryEventListResponse:
    """List discovery events with optional filters.

    Supports filtering by event_type, asset_id, and date range (since/until).
    Results are ordered by detected_at descending.
    """
    db_path: str = request.app.state.db_path
    events = await get_discovery_events(
        db_path,
        asset_id=asset_id,
        event_type=event_type,
        date_since=since,
        date_until=until,
        limit=limit,
    )
    items = [event_to_response(e) for e in events]
    return DiscoveryEventListResponse(items=items, total=len(items))
