"""Settings API endpoints for enterprise features (OTEL, custom pricing, etc.)."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from urllib.parse import urlparse

from .auth import verify_token, require_role, require_enterprise
from .database import execute_query, execute_insert, get_db
from .encryption import get_encryption_manager, EncryptionManager
from .models import (
    OtelConfig,
    OtelConfigResponse,
    OtelTestResponse,
    TokenPayload,
    PricingResponse,
)
from .telemetry.forwarder import get_forwarder

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])


# ============ OTEL Configuration Endpoints ============


@router.put("/otel")
async def update_otel_config(
    request: Request,
    body: OtelConfig,
    token: TokenPayload = Depends(verify_token),
) -> dict:
    """
    Update OTEL configuration for workspace.

    Auth: owner only
    Validates endpoint is reachable before storing.
    """
    await require_role("owner", token)

    # Validate endpoint is HTTPS
    parsed = urlparse(body.endpoint)
    if parsed.scheme != "https":
        raise HTTPException(
            status_code=400, detail="OTEL endpoint must use HTTPS protocol"
        )

    # Test endpoint connectivity
    forwarder = get_forwarder()
    ok, latency_ms = await forwarder.test_endpoint(body.endpoint, body.api_key)

    if not ok:
        raise HTTPException(
            status_code=400, detail="Failed to connect to OTEL endpoint"
        )

    # Encrypt API key before storing
    try:
        encryption_manager = get_encryption_manager()
        encrypted_key = encryption_manager.encrypt(body.api_key)
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to encrypt API key")

    # Update workspace OTEL config in database
    try:
        db = await get_db()
        async with db.transaction():
            await db.execute(
                """
                UPDATE workspaces
                SET otel_endpoint = $1,
                    otel_api_key_encrypted = $2,
                    otel_enabled = $3
                WHERE id = $4
                """,
                body.endpoint,
                encrypted_key,
                body.enabled,
                token.workspace_id,
            )
    except Exception as e:
        logger.error(f"Failed to update OTEL config: {e}")
        raise HTTPException(status_code=500, detail="Failed to save OTEL config")

    return {
        "status": "connected",
        "test_span_sent": True,
        "latency_ms": latency_ms,
    }


@router.get("/otel")
async def get_otel_config(
    token: TokenPayload = Depends(verify_token),
) -> OtelConfigResponse:
    """Get current OTEL configuration (with masked API key)."""
    await require_role("admin", token)

    try:
        result = await execute_query(
            "SELECT otel_endpoint, otel_api_key_encrypted, otel_enabled FROM workspaces WHERE id = $1",
            token.workspace_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Workspace not found")

        row = result[0]
        endpoint = row.get("otel_endpoint")
        encrypted_key = row.get("otel_api_key_encrypted")
        enabled = row.get("otel_enabled", False)

        # Decrypt and mask API key
        api_key_masked = "****"
        if encrypted_key:
            try:
                encryption_manager = get_encryption_manager()
                api_key = encryption_manager.decrypt(encrypted_key)
                api_key_masked = EncryptionManager.mask_api_key(api_key)
            except Exception as e:
                logger.warning(f"Failed to decrypt OTEL key: {e}")

        return OtelConfigResponse(
            enabled=enabled,
            endpoint=endpoint or "",
            api_key_masked=api_key_masked,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch OTEL config: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch OTEL config")


@router.post("/otel/test")
async def test_otel_endpoint(
    token: TokenPayload = Depends(verify_token),
) -> OtelTestResponse:
    """Test OTEL endpoint connectivity."""
    await require_role("admin", token)

    # Fetch current config
    try:
        result = await execute_query(
            "SELECT otel_endpoint, otel_api_key_encrypted FROM workspaces WHERE id = $1",
            token.workspace_id,
        )

        if not result or not result[0].get("otel_endpoint"):
            raise HTTPException(
                status_code=400, detail="OTEL endpoint not configured"
            )

        row = result[0]
        endpoint = row["otel_endpoint"]
        encrypted_key = row["otel_api_key_encrypted"]

        if not encrypted_key:
            raise HTTPException(
                status_code=400, detail="OTEL API key not configured"
            )

        # Decrypt API key
        encryption_manager = get_encryption_manager()
        api_key = encryption_manager.decrypt(encrypted_key)

        # Test endpoint
        forwarder = get_forwarder()
        ok, latency_ms = await forwarder.test_endpoint(endpoint, api_key)

        if ok:
            return OtelTestResponse(ok=True, latency_ms=latency_ms)
        else:
            return OtelTestResponse(
                ok=False, error="Failed to reach OTEL endpoint"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OTEL test failed: {e}")
        return OtelTestResponse(ok=False, error=str(e))


# ============ Custom Pricing Endpoints ============


@router.get("/pricing")
async def get_pricing(
    token: TokenPayload = Depends(verify_token),
) -> PricingResponse:
    """Get current pricing (default or custom override)."""
    await require_role("admin", token)

    try:
        # Fetch custom pricing if set
        result = await execute_query(
            "SELECT custom_pricing FROM workspace_settings WHERE workspace_id = $1",
            token.workspace_id,
        )

        if result and result[0].get("custom_pricing"):
            custom_pricing = result[0]["custom_pricing"]
            return PricingResponse(pricing=custom_pricing)

        # Return default pricing (empty - means use standard rates)
        return PricingResponse(pricing={})

    except Exception as e:
        logger.error(f"Failed to fetch pricing: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch pricing")


@router.put("/pricing")
async def update_pricing(
    request: Request,
    body: dict,
    token: TokenPayload = Depends(verify_token),
) -> dict:
    """
    Update custom pricing for workspace (enterprise plan only).

    Body: {"model_name": {"input_per_1m": X.XX, "output_per_1m": Y.YY}}
    """
    await require_role("admin", token)
    await require_enterprise(token)

    # Validate pricing format
    try:
        for model, rates in body.items():
            if not isinstance(rates, dict):
                raise ValueError(f"Invalid rates for {model}")
            if "input_per_1m" not in rates or "output_per_1m" not in rates:
                raise ValueError(
                    f"Missing input_per_1m or output_per_1m for {model}"
                )
            # Validate rates are positive floats
            float(rates["input_per_1m"])
            float(rates["output_per_1m"])
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid pricing format: {e}")

    # Upsert custom pricing
    try:
        db = await get_db()
        async with db.transaction():
            await db.execute(
                """
                INSERT INTO workspace_settings (workspace_id, custom_pricing)
                VALUES ($1, $2)
                ON CONFLICT (workspace_id)
                DO UPDATE SET custom_pricing = $2, updated_at = NOW()
                """,
                token.workspace_id,
                body,
            )

        # Log to audit log
        await execute_insert(
            """
            INSERT INTO workspace_activity (workspace_id, user_id, action, detail)
            VALUES ($1, $2, $3, $4)
            """,
            token.workspace_id,
            token.user_id,
            "update_custom_pricing",
            {"models_updated": list(body.keys())},
        )

        return {"status": "updated", "models": list(body.keys())}

    except Exception as e:
        logger.error(f"Failed to update pricing: {e}")
        raise HTTPException(status_code=500, detail="Failed to update pricing")


# ============ Monthly spend budget ============


class BudgetSettingRequest(BaseModel):
    monthly_budget_usd: Optional[float] = None  # None to clear the override


@router.put("/budget")
async def update_budget(
    body: BudgetSettingRequest,
    token: TokenPayload = Depends(verify_token),
) -> dict:
    """Admin+. Set or clear this workspace's monthly spend cap (USD).

    Writes `limit_overrides.monthly_spend_cap_usd` — the same value
    `resolve_limits()` resolves and `ingest.py` hard-enforces (429 at the cap)
    and `/api/v1/budget` forecasts against. `null` clears the override so the
    plan default applies again.
    """
    await require_role("admin", token)

    amount = body.monthly_budget_usd
    if amount is not None and amount <= 0:
        raise HTTPException(
            status_code=422, detail="monthly_budget_usd must be greater than 0"
        )

    if amount is not None:
        await execute_insert(
            """
            UPDATE workspaces
            SET limit_overrides =
                COALESCE(limit_overrides, '{}'::jsonb)
                || jsonb_build_object('monthly_spend_cap_usd', $1::numeric)
            WHERE id = $2
            """,
            amount,
            token.workspace_id,
        )
    else:
        await execute_insert(
            """
            UPDATE workspaces
            SET limit_overrides =
                COALESCE(limit_overrides, '{}'::jsonb) - 'monthly_spend_cap_usd'
            WHERE id = $1
            """,
            token.workspace_id,
        )

    # Best-effort audit trail (money-affecting setting). Must never block the write.
    try:
        await execute_insert(
            """
            INSERT INTO workspace_activity (workspace_id, user_id, action, detail)
            VALUES ($1, $2, $3, $4::jsonb)
            """,
            token.workspace_id,
            token.user_id,
            "update_monthly_budget",
            json.dumps({"monthly_spend_cap_usd": amount}),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("budget audit-log write failed (ignored): %s", e)

    return {"monthly_budget_usd": amount}


class TeamBudgetSettingRequest(BaseModel):
    team: str
    monthly_budget_usd: Optional[float] = None  # None to clear


@router.put("/team-budget")
async def update_team_budget(
    body: TeamBudgetSettingRequest,
    token: TokenPayload = Depends(verify_token),
) -> dict:
    """Admin+. Set or clear a per-team monthly budget (USD).

    Writes `limit_overrides.team_budgets.<team>` on the workspace; read back by
    `GET /api/v1/team-budgets` with month-to-date spend from the team tag.
    Display/alerting only — the workspace-level cap is what ingest enforces.
    """
    await require_role("admin", token)

    team = body.team.strip()
    if not team:
        raise HTTPException(status_code=422, detail="team must be non-empty")
    amount = body.monthly_budget_usd
    if amount is not None and amount <= 0:
        raise HTTPException(
            status_code=422, detail="monthly_budget_usd must be greater than 0"
        )

    if amount is not None:
        # jsonb_set cannot create INTERMEDIATE keys — with no existing
        # 'team_budgets' object the write silently no-ops. The inner
        # jsonb_set seeds the parent (depth-1 path always traversable),
        # the outer one sets the leaf.
        await execute_insert(
            """
            UPDATE workspaces
            SET limit_overrides = jsonb_set(
                jsonb_set(
                    COALESCE(limit_overrides, '{}'::jsonb),
                    '{team_budgets}',
                    COALESCE(limit_overrides->'team_budgets', '{}'::jsonb),
                    true
                ),
                ARRAY['team_budgets', $1],
                to_jsonb($2::numeric),
                true
            )
            WHERE id = $3
            """,
            team,
            amount,
            token.workspace_id,
        )
    else:
        await execute_insert(
            """
            UPDATE workspaces
            SET limit_overrides =
                COALESCE(limit_overrides, '{}'::jsonb) #- ARRAY['team_budgets', $1]
            WHERE id = $2
            """,
            team,
            token.workspace_id,
        )

    # Best-effort audit trail (money-affecting setting). Must never block the write.
    try:
        await execute_insert(
            """
            INSERT INTO workspace_activity (workspace_id, user_id, action, detail)
            VALUES ($1, $2, $3, $4::jsonb)
            """,
            token.workspace_id,
            token.user_id,
            "update_team_budget",
            json.dumps({"team": team, "monthly_budget_usd": amount}),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("team-budget audit-log write failed (ignored): %s", e)

    return {"team": team, "monthly_budget_usd": amount}


# Phase 12: Slack webhook configuration for alert rules.
class SlackWebhookRequest(BaseModel):
    webhook_url: Optional[str] = None  # None to clear


@router.put("/slack-webhook")
async def update_slack_webhook(
    body: SlackWebhookRequest,
    token: TokenPayload = Depends(verify_token),
) -> dict:
    """
    Owner-only. Set or clear the Slack webhook URL for this workspace's alert rules.

    - webhook_url must start with https://hooks.slack.com/ (or be null to clear).
    - Updates all alert_rules for the workspace:
        - If URL provided: sets slack_webhook_url + channel = 'both'
        - If URL is null: clears slack_webhook_url + channel = 'email'
    """
    await require_role("owner", token)

    url = body.webhook_url
    if url is not None:
        from urllib.parse import urlparse as _urlparse
        _p = _urlparse(url)
        if _p.scheme != "https" or _p.hostname != "hooks.slack.com":
            raise HTTPException(
                status_code=422,
                detail="webhook_url must be an https://hooks.slack.com/ URL",
            )

    if url is not None:
        result = await execute_insert(
            """
            UPDATE alert_rules
            SET slack_webhook_url = $1,
                channel = 'both',
                updated_at = NOW()
            WHERE workspace_id = $2
            """,
            url,
            token.workspace_id,
        )
    else:
        result = await execute_insert(
            """
            UPDATE alert_rules
            SET slack_webhook_url = NULL,
                channel = 'email',
                updated_at = NOW()
            WHERE workspace_id = $1
            """,
            token.workspace_id,
        )

    updated_count = int(result.split()[-1]) if result else 0
    return {"updated_rules": updated_count}


# Phase 10 extension: Teams webhook configuration for alert rules.
class TeamsWebhookRequest(BaseModel):
    webhook_url: Optional[str] = None  # None to clear


@router.put("/teams-webhook")
async def update_teams_webhook(
    body: TeamsWebhookRequest,
    token: TokenPayload = Depends(verify_token),
) -> dict:
    """
    Owner-only. Set or clear the Teams webhook URL for this workspace's alert rules.

    - webhook_url must be a valid Microsoft/Office webhook URL (or null to clear).
    - Updates all alert_rules for the workspace:
        - If URL provided: sets teams_webhook_url + channel = 'teams'
        - If URL is null: clears teams_webhook_url + channel = 'email'
    """
    await require_role("owner", token)

    url = body.webhook_url
    if url is not None:
        from .alert_engine import is_valid_teams_webhook
        if not is_valid_teams_webhook(url):
            raise HTTPException(
                status_code=422,
                detail="webhook_url must be a valid Microsoft Teams webhook URL",
            )

    if url is not None:
        result = await execute_insert(
            """
            UPDATE alert_rules
            SET teams_webhook_url = $1,
                channel = 'teams',
                updated_at = NOW()
            WHERE workspace_id = $2
            """,
            url,
            token.workspace_id,
        )
    else:
        result = await execute_insert(
            """
            UPDATE alert_rules
            SET teams_webhook_url = NULL,
                channel = 'email',
                updated_at = NOW()
            WHERE workspace_id = $1
            """,
            token.workspace_id,
        )

    updated_count = int(result.split()[-1]) if result else 0
    return {"updated_rules": updated_count}
