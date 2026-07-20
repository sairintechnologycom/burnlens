"""Alert rules API endpoints — list and patch workspace alert rules."""

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import verify_token, require_role
from .alert_engine import is_valid_teams_webhook
from .database import execute_query, execute_insert
from .models import TokenPayload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["alert-rules"])


class AlertRulePatch(BaseModel):
    enabled: Optional[bool] = None
    threshold_pct: Optional[int] = None   # must be 80 or 100 if provided
    extra_emails: Optional[List[str]] = None  # full-replace semantics
    teams_webhook_url: Optional[str] = None


@router.get("/alert-rules")
async def list_alert_rules(
    token: TokenPayload = Depends(verify_token),
) -> List[dict]:
    """List all alert rules for the authenticated workspace."""
    await require_role("viewer", token)
    try:
        rows = await execute_query(
            """
            SELECT id, threshold_pct, channel, enabled,
                   slack_webhook_url IS NOT NULL AS has_slack,
                   teams_webhook_url IS NOT NULL AS has_teams,
                   extra_emails, created_at, updated_at
            FROM alert_rules
            WHERE workspace_id = $1
            ORDER BY threshold_pct
            """,
            token.workspace_id,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to list alert rules: {e}")
        raise HTTPException(status_code=500, detail="failed_to_list_rules")


@router.patch("/alert-rules/{rule_id}")
async def patch_alert_rule(
    rule_id: str,
    body: AlertRulePatch,
    token: TokenPayload = Depends(verify_token),
) -> dict:
    """Update an alert rule. Owner role required. Supports partial update."""
    await require_role("owner", token)

    # Validate threshold_pct before touching DB
    if body.threshold_pct is not None and body.threshold_pct not in (80, 100):
        raise HTTPException(status_code=422, detail="threshold_pct must be 80 or 100")

    # Build dynamic SET clause — only non-None fields
    fields: list[str] = []
    params: list = []
    idx = 1

    if body.enabled is not None:
        fields.append(f"enabled = ${idx}")
        params.append(body.enabled)
        idx += 1
    if body.threshold_pct is not None:
        fields.append(f"threshold_pct = ${idx}")
        params.append(body.threshold_pct)
        idx += 1
    if body.extra_emails is not None:
        fields.append(f"extra_emails = ${idx}")
        params.append(body.extra_emails)
        idx += 1
    if body.teams_webhook_url is not None:
        # Empty string clears the webhook; a non-empty value must be a real
        # Teams host (SSRF/exfil guard — same validator as settings_api).
        if body.teams_webhook_url and not is_valid_teams_webhook(body.teams_webhook_url):
            raise HTTPException(
                status_code=422,
                detail="teams_webhook_url must be a valid Microsoft Teams webhook URL",
            )
        fields.append(f"teams_webhook_url = ${idx}")
        params.append(body.teams_webhook_url)
        idx += 1

    if not fields:
        raise HTTPException(status_code=422, detail="no fields to update")

    fields.append("updated_at = NOW()")
    sql = f"""
        UPDATE alert_rules
        SET {', '.join(fields)}
        WHERE id = ${idx} AND workspace_id = ${idx + 1}
    """
    params.extend([rule_id, str(token.workspace_id)])

    try:
        result = await execute_insert(sql, *params)
        count = int(result.split()[-1]) if result else 0
        if count == 0:
            raise HTTPException(status_code=404, detail="rule_not_found")
        return {"updated": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update alert rule {rule_id}: {e}")
        raise HTTPException(status_code=500, detail="failed_to_update_rule")
