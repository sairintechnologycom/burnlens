"""Stub endpoints to satisfy the frontend until real implementations ship.

Tracked in .planning/backlog/frontend-api-gaps.md — each handler here must be
replaced with a real implementation before the feature it powers ships.
"""
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends

from .auth import TokenPayload, verify_token

router = APIRouter(tags=["stubs"])


# /api/v1/connections removed 2026-07-19 along with its frontend page: nothing
# in the cloud consumed stored provider keys, so the page collected secrets
# only to 501. Re-add only WITH a real consumer (discovery/reconciliation).


@router.get("/api/v1/recommendations")
async def list_recommendations(
    token: TokenPayload = Depends(verify_token),
) -> List[dict]:
    return []


@router.post("/api/v1/sync/trigger")
async def trigger_sync(token: TokenPayload = Depends(verify_token)):
    return {
        "status": "ok",
        "triggered_at": datetime.now(timezone.utc).isoformat(),
        "note": "Client-side sync runs from the proxy; this endpoint is a no-op ack.",
    }


@router.get("/api/team-budgets")
async def list_team_budgets(
    token: TokenPayload = Depends(verify_token),
) -> List[dict]:
    return []


# /api/budget graduated out of stubs → real impl at dashboard_api.py
# GET /api/v1/budget (monthly spend + burn-rate forecast). Frontend repointed.
