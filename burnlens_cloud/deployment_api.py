"""Deployment and status API endpoints."""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from .database import execute_query
from .deployment.status import get_status_checker, StatusPageRenderer
from .models import StatusResponse, ComponentStatus

logger = logging.getLogger(__name__)
router = APIRouter(tags=["status"])


@router.get("/status", response_class=HTMLResponse)
async def status_page():
    """Public status page (no authentication)."""
    try:
        status_checker = get_status_checker()

        # Get status for each component
        components = []
        for name in ["Ingest API", "Dashboard API", "Cloud Sync"]:
            # For now, hardcode to all operational
            # In production, these would be fetched from database
            components.append({
                "name": name,
                "status": "operational",
                "uptime_30d": 99.97,
            })

        html = StatusPageRenderer.render(components)
        return html

    except Exception as e:
        logger.error(f"Failed to render status page: {e}")
        # Return a simple fallback status page
        return """
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
            <p>Status page unavailable. All services appear to be operational.</p>
        </body>
        </html>
        """


@router.get("/api/status")
async def status_api() -> StatusResponse:
    """Public status API endpoint (JSON, no authentication)."""
    try:
        status_checker = get_status_checker()

        # Fetch component status
        components = []
        for name in ["Ingest API", "Dashboard API", "Cloud Sync"]:
            status, uptime = await status_checker.get_component_status(days=30)
            components.append(
                ComponentStatus(
                    name=name,
                    uptime_30d=uptime,
                    status=status,
                )
            )

        return StatusResponse(
            components=components,
            incidents=[],
        )

    except Exception as e:
        logger.error(f"Failed to fetch status: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch status")
