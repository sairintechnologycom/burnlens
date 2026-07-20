"""
Phase 10: Action APIs for clickable alerts.

Handles the execution of remediation actions (e.g. pause API key)
triggered from signed links in Slack/Teams notifications.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .action_tokens import verify_action_token, consume_action_token, ActionTokenPayload
from .database import execute_query, execute_insert
from .auth import invalidate_api_key_cache, verify_token, require_role
from .models import TokenPayload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/actions", tags=["actions"])


class ActionExecuteRequest(BaseModel):
    token: str


class RevertActionRequest(BaseModel):
    original_activity_id: str
    action: str  # unpause_api_key, revert_budget, revert_downgrade


@router.get("/confirm")
async def confirm_action(token: str):
    """
    Validate the action token and render a confirmation page.
    Prevents GET-based prefetching from triggering state changes.
    """
    payload = await verify_action_token(token)
    if not payload:
        raise HTTPException(status_code=400, detail="invalid_or_expired_token")

    # Build human-readable description. Values come from a server-signed token,
    # but escape anyway — never interpolate raw strings into HTML.
    import html as _html

    action_label = _html.escape(payload.action.replace("_", " ").title())
    target_desc = (
        f"target {_html.escape(str(payload.target_id))}"
        if payload.target_id
        else "this workspace"
    )
    token_attr = _html.escape(token, quote=True)

    html = f"""
    <html>
        <head>
            <title>Confirm Action — BurnLens</title>
            <style>
                body {{ font-family: -apple-system, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; background: #f9fafb; }}
                .card {{ background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); max-width: 400px; text-align: center; }}
                h1 {{ font-size: 1.25rem; color: #111827; }}
                p {{ color: #4b5563; margin-bottom: 2rem; }}
                button {{ background: #2563eb; color: white; border: none; padding: 0.75rem 1.5rem; border-radius: 6px; cursor: pointer; font-weight: 600; }}
                button:hover {{ background: #1d4ed8; }}
                .danger {{ background: #dc2626; }}
                .danger:hover {{ background: #b91c1c; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>Confirm Action</h1>
                <p>Are you sure you want to <strong>{action_label}</strong> for {target_desc}?</p>
                <form action="/api/v1/actions/execute" method="POST">
                    <input type="hidden" name="token" value="{token_attr}">
                    <button type="submit" class="{'danger' if 'pause' in payload.action else ''}">Confirm {action_label}</button>
                </form>
            </div>
        </body>
    </html>
    """
    return HTMLResponse(content=html)


@router.post("/execute")
async def execute_action(request: Request):
    """
    Validate the token, execute the requested action, and log to audit trail.
    Accepts token from form data (sent by confirm page).
    """
    form = await request.form()
    token = form.get("token")
    if not token or not isinstance(token, str):
        raise HTTPException(status_code=400, detail="missing_token")

    payload = await verify_action_token(token)
    if not payload:
        raise HTTPException(status_code=400, detail="invalid_or_expired_token")

    # Enforce single-use
    if not await consume_action_token(payload.jti):
        raise HTTPException(status_code=400, detail="token_already_consumed")

    # Execute action
    success = False
    detail = {"target_id": payload.target_id}

    try:
        if payload.action == "pause_api_key":
            success = await _handle_pause_api_key(payload.workspace_id, payload.target_id)
        elif payload.action == "increase_budget":
            success = await _handle_increase_budget(payload.workspace_id)
        elif payload.action == "downgrade_model":
            success = await _handle_downgrade_model(payload.workspace_id)
        else:
            logger.warning("actions_api: unknown action %s", payload.action)
            raise HTTPException(status_code=400, detail="unknown_action")

        if not success:
            raise HTTPException(status_code=500, detail="action_failed")

        # Log to workspace_activity
        # detail is serialized to JSONB in DB
        await _log_action_activity(payload.workspace_id, payload.action, detail)

        return {"ok": True, "message": f"Action {payload.action} executed successfully"}

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("actions_api: execution failed: %s", exc)
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/revert")
async def revert_action(
    body: RevertActionRequest,
    token: TokenPayload = Depends(verify_token),
) -> dict:
    """
    Undo a previous remediation action. Admin/Owner only.
    """
    await require_role("admin", token)

    workspace_id = token.workspace_id

    # Fetch original activity to verify ownership and get details
    try:
        activity_id = int(body.original_activity_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_activity_id")

    res = await execute_query(
        "SELECT action, detail FROM workspace_activity WHERE id = $1 AND workspace_id = $2",
        activity_id,
        workspace_id,
    )
    if not res:
        raise HTTPException(status_code=404, detail="activity_not_found")

    original = res[0]
    detail = original["detail"]

    success = False
    try:
        if body.action == "unpause_api_key":
            key_id = detail.get("target_id")
            if not key_id:
                raise HTTPException(status_code=400, detail="missing_target_key")
            
            res_key = await execute_query(
                "UPDATE api_keys SET paused_at = NULL WHERE id = $1 AND workspace_id = $2 RETURNING key_hash",
                key_id, workspace_id
            )
            if res_key:
                invalidate_api_key_cache(res_key[0]["key_hash"])
                success = True

        elif body.action == "revert_budget":
            # Remove the monthly_request_cap override
            await execute_insert(
                "UPDATE workspaces SET limit_overrides = limit_overrides - 'monthly_request_cap' WHERE id = $1",
                workspace_id
            )
            success = True

        elif body.action == "revert_downgrade":
            # Remove the budget_downgrade overrides
            await execute_insert(
                "UPDATE workspaces SET routing_overrides = routing_overrides - 'budget_downgrade' - 'downgrade_threshold_pct' WHERE id = $1",
                workspace_id
            )
            success = True
        
        else:
            raise HTTPException(status_code=400, detail="unsupported_revert_action")

        if not success:
            raise HTTPException(status_code=500, detail="revert_failed")

        # Log the reversal
        await _log_action_activity(workspace_id, body.action, {"reverted_id": activity_id})

        return {"ok": True, "message": f"Action {body.action} executed successfully"}

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("actions_api: revert failed: %s", exc)
        raise HTTPException(status_code=500, detail="internal_error")


async def _handle_pause_api_key(workspace_id: str, key_id: Optional[str]) -> bool:
    if not key_id:
        return False
    
    result = await execute_query(
        """
        UPDATE api_keys
        SET paused_at = NOW()
        WHERE id = $1 AND workspace_id = $2 AND revoked_at IS NULL
        RETURNING key_hash
        """,
        key_id, workspace_id
    )
    if result:
        # Invalidate auth cache so pause takes effect immediately
        invalidate_api_key_cache(result[0]["key_hash"])
        return True
    return False


async def _handle_increase_budget(workspace_id: str) -> bool:
    """Increase monthly request cap by 50% as an emergency measure."""
    # First get current limit
    res = await execute_query(
        "SELECT monthly_request_cap FROM resolve_limits($1)",
        workspace_id
    )
    if not res:
        return False
    
    current_cap = res[0]["monthly_request_cap"] or 10000  # fallback to free tier if null
    new_cap = int(current_cap * 1.5)

    # Update limit_overrides
    await execute_insert(
        """
        UPDATE workspaces
        SET limit_overrides = COALESCE(limit_overrides, '{}'::jsonb) || jsonb_build_object('monthly_request_cap', $1::int)
        WHERE id = $2
        """,
        new_cap, workspace_id
    )
    return True


async def _handle_downgrade_model(workspace_id: str) -> bool:
    """Enable aggressive budget-aware model downgrade for this workspace."""
    await execute_insert(
        """
        UPDATE workspaces
        SET routing_overrides = COALESCE(routing_overrides, '{}'::jsonb) || '{"budget_downgrade": true, "downgrade_threshold_pct": 50.0}'::jsonb
        WHERE id = $1
        """,
        workspace_id
    )
    return True


async def _log_action_activity(workspace_id: str, action: str, detail: dict):
    """Insert into workspace_activity table."""
    try:
        await execute_insert(
            """
            INSERT INTO workspace_activity (workspace_id, action, detail)
            VALUES ($1, $2, $3)
            """,
            workspace_id, f"action_{action}", detail
        )
    except Exception as exc:
        logger.warning("actions_api: failed to log activity: %s", exc)
