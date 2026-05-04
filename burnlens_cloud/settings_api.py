"""Settings API endpoints for enterprise features (OTEL, custom pricing, etc.)."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from urllib.parse import urlparse

from .auth import verify_token, require_role
from .database import execute_query, execute_insert, get_db
from .encryption import get_encryption_manager, EncryptionManager
from .models import (
    OtelConfig,
    OtelConfigResponse,
    OtelTestResponse,
    TokenPayload,
    PricingResponse,
    CustomPricingRequest,
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
            status_code=400, detail=f"Failed to connect to OTEL endpoint"
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

    # Check if enterprise plan
    if token.plan != "enterprise":
        raise HTTPException(
            status_code=403, detail="Custom pricing available for enterprise plan only"
        )

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
