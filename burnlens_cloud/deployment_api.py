"""Deployment and status API endpoints."""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from .deployment.status import get_status_checker, StatusPageRenderer
from .models import StatusResponse, ComponentStatus

logger = logging.getLogger(__name__)
router = APIRouter(tags=["status"])

COMPONENTS = ("Ingest API", "Dashboard API", "Cloud Sync")


async def _component_rows() -> list[dict]:
    checker = get_status_checker()
    rows = []
    for name in COMPONENTS:
        status, uptime = await checker.get_component_status(name, days=30)
        rows.append({"name": name, "status": status, "uptime_30d": uptime})
    return rows


@router.get("/status", response_class=HTMLResponse)
async def status_page():
    """Public status page (no authentication)."""
    try:
        components = await _component_rows()
        html = StatusPageRenderer.render(components)
        return HTMLResponse(content=html, status_code=200)

    except Exception as e:
        logger.error(f"Failed to render status page: {e}")
        # Fail closed: an unavailable monitor must never claim the service is
        # operational.  A 503 also makes external probes detect the problem.
        return HTMLResponse(content="""
        <!DOCTYPE html>
        <html>
        <head>
            <title>BurnLens Status</title>
            <style>
                body { background: #080c10; color: #e0e0e0; font-family: sans-serif; padding: 2rem; text-align: center; }
                h1 { color: #00e5c8; }
            </style>
        </head>
        <body>
            <h1>🔥 BurnLens Status</h1>
            <p>Status data is currently unavailable. Service health is unknown.</p>
        </body>
        </html>
        """, status_code=503)


@router.get("/api/status")
async def status_api() -> StatusResponse:
    """Public status API endpoint (JSON, no authentication)."""
    try:
        components = []
        for row in await _component_rows():
            components.append(
                ComponentStatus(
                    name=row["name"],
                    uptime_30d=row["uptime_30d"],
                    status=row["status"],
                )
            )

        return StatusResponse(
            components=components,
            incidents=[],
        )

    except Exception as e:
        logger.error(f"Failed to fetch status: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch status")
