"""Stub endpoints to satisfy the frontend until real implementations ship.

Tracked in .planning/backlog/frontend-api-gaps.md — each handler here must be
replaced with a real implementation before the feature it powers ships.
"""
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from .auth import TokenPayload, verify_token

router = APIRouter(tags=["stubs"])


@router.get("/api/v1/connections")
async def list_connections(token: TokenPayload = Depends(verify_token)) -> List[dict]:
    return []


@router.post("/api/v1/connections", status_code=501)
async def create_connection(token: TokenPayload = Depends(verify_token)):
    raise HTTPException(status_code=501, detail="connections_not_implemented")


@router.delete("/api/v1/connections/{connection_id}", status_code=501)
async def delete_connection(
    connection_id: str, token: TokenPayload = Depends(verify_token)
):
    raise HTTPException(status_code=501, detail="connections_not_implemented")


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


@router.get("/api/budget")
async def get_budget_alias(token: TokenPayload = Depends(verify_token)):
    return {
        "budget_usd": None,
        "spent_usd": 0.0,
        "remaining_usd": None,
        "forecast_usd": 0.0,
        "pct_used": 0.0,
        "is_over_budget": False,
        "is_on_pace_to_exceed": False,
        "period_days": 30,
        "elapsed_days": 0,
    }
