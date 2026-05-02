"""
Phase 12: Railway cron endpoint for alert evaluation.

POST /cron/evaluate-alerts
  - Protected by Authorization: Bearer {CRON_SECRET}
  - Calls evaluate_all_workspaces(db_pool)
  - Returns {"evaluated": N, "fired": M}
  - Fail-open: exceptions from evaluate_all_workspaces are caught; returns {"evaluated": 0, "fired": 0}
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .alert_engine import evaluate_all_workspaces
from .config import settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/cron", tags=["cron"])
_bearer = HTTPBearer(auto_error=False)


def _verify_cron_secret(credentials: HTTPAuthorizationCredentials | None) -> None:
    """Raise 401 if the bearer token does not match CRON_SECRET."""
    if not settings.cron_secret:
        raise HTTPException(status_code=401, detail="CRON_SECRET not configured")
    if credentials is None or not secrets.compare_digest(
        credentials.credentials, settings.cron_secret
    ):
        raise HTTPException(status_code=401, detail="Invalid cron secret")


@router.post("/evaluate-alerts")
async def evaluate_alerts(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """
    Hourly cron endpoint. Evaluates all alert rules for all non-free workspaces.

    Railway should POST here with Authorization: Bearer {CRON_SECRET}.
    Returns {"evaluated": N, "fired": M} always — fail-open.
    """
    _verify_cron_secret(credentials)
    db_pool: Any = request.app.state.db_pool
    try:
        result = await evaluate_all_workspaces(db_pool)
        log.info("cron/evaluate-alerts: %s", result)
        return result
    except Exception as exc:
        log.error("cron/evaluate-alerts: unhandled error: %s", exc)
        return {"evaluated": 0, "fired": 0}
