"""Findings + waste-alerts HTTP surface (BL-F1)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from .auth import TokenPayload, require_role, verify_token
from .dashboard_api import clamp_days_by_plan
from .database import get_pool
from .findings import (
    VALID_STATUSES,
    finding_to_dict,
    get_economics_overview,
    list_findings,
    refresh_findings,
    set_finding_status,
    waste_alert_from_finding,
)
from .models import EconomicsOverview, FindingItem, FindingStatusBody

router = APIRouter(prefix="/api/v1", tags=["findings"])


def _require_requested_with(x_requested_with: Optional[str]) -> None:
    if not x_requested_with:
        raise HTTPException(status_code=403, detail="Missing X-Requested-With header")


@router.get("/findings", response_model=list[FindingItem])
async def get_findings(
    token: TokenPayload = Depends(verify_token),
    status: Optional[str] = Query(default=None),
):
    """Persisted waste findings for this workspace. Refreshes if stale."""
    await require_role("viewer", token)
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of: {', '.join(VALID_STATUSES)}",
        )
    pool = get_pool()
    async with pool.acquire() as conn:
        await refresh_findings(conn, token.workspace_id)
        rows = await list_findings(conn, token.workspace_id, status=status)
    return [finding_to_dict(r) for r in rows]


@router.post("/findings/{fingerprint}/status", response_model=FindingItem)
async def post_finding_status(
    fingerprint: str,
    body: FindingStatusBody,
    token: TokenPayload = Depends(verify_token),
    x_requested_with: Optional[str] = Header(default=None, alias="X-Requested-With"),
):
    """Move a finding through its lifecycle. Snapshots a baseline on resolve."""
    await require_role("viewer", token)
    _require_requested_with(x_requested_with)
    if body.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of: {', '.join(VALID_STATUSES)}",
        )
    pool = get_pool()
    async with pool.acquire() as conn:
        updated = await set_finding_status(
            conn, token.workspace_id, fingerprint, body.status
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Finding not found")
        rows = await conn.fetch(
            """
            SELECT * FROM waste_findings
             WHERE workspace_id = $1 AND fingerprint = $2
            """,
            token.workspace_id,
            fingerprint,
        )
    return finding_to_dict(rows[0])


@router.get("/economics", response_model=EconomicsOverview)
async def get_economics(
    token: TokenPayload = Depends(verify_token),
    days: int = Query(7, description="Number of days to look back"),
):
    """Spend, waste rate, error spend, cost per accepted outcome."""
    await require_role("viewer", token)
    days = clamp_days_by_plan(days, token.plan)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    pool = get_pool()
    async with pool.acquire() as conn:
        return await get_economics_overview(conn, token.workspace_id, cutoff)


@router.get("/waste-alerts")
async def get_waste_alerts(token: TokenPayload = Depends(verify_token)):
    """Open findings, mapped to the existing waste-alerts response shape."""
    await require_role("viewer", token)
    pool = get_pool()
    async with pool.acquire() as conn:
        await refresh_findings(conn, token.workspace_id)
        rows = await list_findings(conn, token.workspace_id, status="open")
    return [waste_alert_from_finding(r) for r in rows]
