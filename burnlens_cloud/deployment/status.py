"""SLA and status tracking for enterprise deployment."""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional

import httpx

from ..database import execute_insert, execute_query
from ..config import settings

logger = logging.getLogger(__name__)


def _default_base_url() -> str:
    """Pick the loopback URL matching the port uvicorn is actually bound to."""
    # Match the Procfile default (${PORT:-8080}) so the self-probe hits
    # the same port uvicorn binds to when PORT is unset.
    port = os.getenv("PORT") or "8080"
    return f"http://localhost:{port}"


class StatusChecker:
    """Monitors health of BurnLens cloud services and records uptime."""

    # Probed via GET; every path must return 2xx when the component is healthy.
    ENDPOINTS = {
        "Ingest API": "/health",
        "Dashboard API": "/health",
        "Cloud Sync": "/health/sync",
    }

    def __init__(self, base_url: Optional[str] = None, timeout_seconds: int = 5):
        """Initialize status checker."""
        self.base_url = (base_url or _default_base_url()).rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def check_endpoint(self, name: str, path: str) -> tuple[bool, int]:
        """
        Check an endpoint and return (ok, response_ms).

        Returns:
            (True, latency_ms) on 2xx response
            (False, latency_ms) on error or non-2xx response
        """
        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(f"{self.base_url}{path}")

            latency_ms = int((time.time() - start) * 1000)
            ok = 200 <= response.status_code < 300

            return ok, latency_ms

        except asyncio.TimeoutError:
            latency_ms = int((time.time() - start) * 1000)
            logger.warning(f"Status check timeout for {name} ({path})")
            return False, latency_ms
        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            logger.error(f"Status check error for {name}: {e}")
            return False, latency_ms

    async def run_check(self):
        """Run all health checks and record results."""
        for name, path in self.ENDPOINTS.items():
            ok, latency_ms = await self.check_endpoint(name, path)

            # Record to database
            try:
                await execute_insert(
                    """
                    INSERT INTO status_checks
                    (checked_at, endpoint, response_ms, status_code, ok)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    datetime.utcnow(),
                    name,
                    latency_ms,
                    200 if ok else 500,
                    ok,
                )
            except Exception as e:
                logger.error(f"Failed to record status check for {name}: {e}")

    async def get_component_status(
        self, days: int = 30
    ) -> tuple[str, float]:
        """
        Calculate component status and uptime %.

        Returns:
            (status, uptime_pct) where status is "operational" | "degraded" | "down"
            and uptime_pct is float like 99.97
        """
        try:
            result = await execute_query(
                """
                SELECT COUNT(*) as total, COUNT(*) FILTER (WHERE ok = true) as ok_count
                FROM status_checks
                WHERE checked_at > NOW() - INTERVAL '1 day' * $1
                """,
                days,
            )

            if not result or result[0]["total"] == 0:
                return "unknown", 0.0

            row = result[0]
            total = row["total"]
            ok_count = row["ok_count"]
            uptime_pct = (ok_count / total) * 100 if total > 0 else 0.0

            # Determine status
            if uptime_pct >= 99.5:
                status = "operational"
            elif uptime_pct >= 95.0:
                status = "degraded"
            else:
                status = "down"

            return status, uptime_pct

        except Exception as e:
            logger.error(f"Failed to calculate component status: {e}")
            return "unknown", 0.0


class StatusPageRenderer:
    """Renders the public status page HTML."""

    TEMPLATE = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>BurnLens Status</title>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                background: #080c10;
                color: #e0e0e0;
                padding: 2rem;
            }}
            .container {{
                max-width: 800px;
                margin: 0 auto;
            }}
            header {{
                text-align: center;
                margin-bottom: 3rem;
                border-bottom: 1px solid #1a2332;
                padding-bottom: 2rem;
            }}
            h1 {{
                font-size: 2rem;
                margin-bottom: 0.5rem;
                color: #00e5c8;
            }}
            .status-grid {{
                display: grid;
                gap: 1.5rem;
                margin-bottom: 3rem;
            }}
            .component {{
                background: #0f1419;
                border-left: 4px solid #444;
                padding: 1.5rem;
                border-radius: 4px;
            }}
            .component.operational {{
                border-left-color: #10b981;
            }}
            .component.degraded {{
                border-left-color: #f59e0b;
            }}
            .component.down {{
                border-left-color: #ef4444;
            }}
            .component-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 0.5rem;
            }}
            .component-name {{
                font-weight: 600;
                font-size: 1.1rem;
            }}
            .badge {{
                padding: 0.25rem 0.75rem;
                border-radius: 12px;
                font-size: 0.875rem;
                font-weight: 500;
            }}
            .badge.operational {{
                background: #10b98144;
                color: #10b981;
            }}
            .badge.degraded {{
                background: #f59e0b44;
                color: #f59e0b;
            }}
            .badge.down {{
                background: #ef444444;
                color: #ef4444;
            }}
            .uptime {{
                color: #888;
                font-size: 0.875rem;
                margin-top: 0.5rem;
            }}
            .uptime-pct {{
                color: #00e5c8;
                font-weight: 600;
            }}
            .incidents {{
                background: #0f1419;
                padding: 1.5rem;
                border-radius: 4px;
                border-left: 4px solid #444;
                margin-bottom: 2rem;
            }}
            .incidents h2 {{
                font-size: 1.2rem;
                margin-bottom: 1rem;
                color: #00e5c8;
            }}
            .incident {{
                padding: 0.75rem;
                background: #1a2332;
                border-radius: 4px;
                margin-bottom: 0.5rem;
                font-size: 0.875rem;
            }}
            .incident-none {{
                color: #888;
                font-style: italic;
            }}
            footer {{
                text-align: center;
                color: #666;
                font-size: 0.875rem;
                border-top: 1px solid #1a2332;
                padding-top: 2rem;
            }}
            .uptime-chart {{
                display: flex;
                gap: 2px;
                margin-top: 1rem;
                height: 30px;
            }}
            .uptime-bar {{
                flex: 1;
                background: #333;
                border-radius: 2px;
                cursor: pointer;
                title: "90 days ago";
            }}
            .uptime-bar.green {{
                background: #10b981;
            }}
            .uptime-bar.amber {{
                background: #f59e0b;
            }}
            .uptime-bar.red {{
                background: #ef4444;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>🔥 BurnLens Status</h1>
                <p>All systems operational</p>
                <p style="color: #666; font-size: 0.875rem; margin-top: 0.5rem;">
                    Last updated: {last_updated}
                </p>
            </header>

            <div class="status-grid">
                {components}
            </div>

            <div class="incidents">
                <h2>Incidents</h2>
                {incidents}
            </div>

            <footer>
                <p>Subscribe for status updates: <input type="email" placeholder="your@email.com" style="padding: 0.5rem; border: 1px solid #333; background: #0f1419; color: #e0e0e0; border-radius: 4px; width: 250px;" /></p>
                <p style="margin-top: 1rem;">Follow @burnlens_app on Twitter for updates</p>
            </footer>
        </div>
    </body>
    </html>
    """

    @staticmethod
    def render(components: list[dict]) -> str:
        """
        Render status page HTML.

        Args:
            components: List of component dicts with keys:
                - name: Component name
                - status: "operational" | "degraded" | "down"
                - uptime_30d: float (e.g., 99.97)

        Returns:
            HTML string
        """
        component_html = ""
        for comp in components:
            status = comp["status"]
            uptime = comp["uptime_30d"]
            component_html += f"""
            <div class="component {status}">
                <div class="component-header">
                    <span class="component-name">{comp['name']}</span>
                    <span class="badge {status}">{status.upper()}</span>
                </div>
                <div class="uptime">
                    30-day uptime: <span class="uptime-pct">{uptime:.2f}%</span>
                </div>
            </div>
            """

        incidents_html = (
            '<div class="incident incident-none">No incidents reported</div>'
        )

        html = StatusPageRenderer.TEMPLATE.format(
            components=component_html,
            incidents=incidents_html,
            last_updated=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        )

        return html


# Global checker instance
_status_checker: Optional[StatusChecker] = None


def get_status_checker() -> StatusChecker:
    """Get or initialize the global status checker."""
    global _status_checker
    if _status_checker is None:
        _status_checker = StatusChecker()
    return _status_checker
