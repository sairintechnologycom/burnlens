"""Enterprise OTEL settings endpoints."""
from __future__ import annotations

import json
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException

from .auth import get_current_workspace, require_role
from .crypto import encrypt, decrypt, mask_api_key
from .models import OtelConfig, OtelConfigResponse, OtelTestResponse
from .telemetry.forwarder import get_forwarder

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_enterprise(ws: dict) -> None:
    """Raise 403 if workspace is not on enterprise plan."""
    if ws["plan"] != "enterprise":
        raise HTTPException(
            status_code=403,
            detail={
                "error": "enterprise_plan_required",
                "upgrade_url": "mailto:hello@burnlens.app",
            },
        )


@router.put("/settings/otel")
async def update_otel_config(
    body: OtelConfig,
    ws: dict = Depends(require_role("owner")),
):
    """
    Configure OTEL push for this workspace.

    Requires owner role + enterprise plan.
    Validates the endpoint is HTTPS and reachable (sends a test span).
    Encrypts the api_key before storing.
    """
    _require_enterprise(ws)

    # Validate HTTPS
    parsed = urlparse(body.endpoint)
    if parsed.scheme != "https":
        raise HTTPException(
            status_code=400, detail="OTEL endpoint must use HTTPS"
        )

    # Test connectivity
    forwarder = get_forwarder()
    ok, latency_ms, err = await forwarder.send_test_span(body.endpoint, body.api_key)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reach OTEL endpoint: {err}",
        )

    # Encrypt API key
    encrypted_key = encrypt(body.api_key)

    # Persist
    from .database import pool
    async with pool.acquire() as conn:
        await conn.execute(
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
            ws["id"],
        )

        # Audit log
        await conn.execute(
            """INSERT INTO workspace_activity (workspace_id, user_id, action, detail)
               VALUES ($1, $2, $3, $4)""",
            ws["id"],
            ws["user_id"],
            "otel_configured",
            json.dumps({"endpoint": body.endpoint}),
        )

    return {"status": "connected", "test_span_sent": True}


@router.get("/settings/otel", response_model=OtelConfigResponse)
async def get_otel_config(
    ws: dict = Depends(require_role("owner", "admin")),
):
    """Return current OTEL config with masked api_key."""
    from .database import pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT otel_endpoint, otel_api_key_encrypted, otel_enabled, otel_last_push
               FROM workspaces WHERE id = $1""",
            ws["id"],
        )

    if not row:
        raise HTTPException(status_code=404, detail="Workspace not found")

    masked = "****"
    if row["otel_api_key_encrypted"]:
        try:
            plain = decrypt(row["otel_api_key_encrypted"])
            masked = mask_api_key(plain)
        except Exception:
            logger.warning("Could not decrypt OTEL key for workspace %s", ws["id"])

    return OtelConfigResponse(
        endpoint=row["otel_endpoint"] or "",
        api_key_masked=masked,
        enabled=row["otel_enabled"],
        last_push=row["otel_last_push"],
    )


@router.post("/settings/otel/test", response_model=OtelTestResponse)
async def test_otel(
    ws: dict = Depends(require_role("owner")),
):
    """Send a single test span to the configured endpoint."""
    from .database import pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT otel_endpoint, otel_api_key_encrypted FROM workspaces WHERE id = $1",
            ws["id"],
        )

    if not row or not row["otel_endpoint"]:
        raise HTTPException(status_code=400, detail="OTEL endpoint not configured")
    if not row["otel_api_key_encrypted"]:
        raise HTTPException(status_code=400, detail="OTEL API key not configured")

    api_key = decrypt(row["otel_api_key_encrypted"])
    forwarder = get_forwarder()
    ok, latency_ms, err = await forwarder.send_test_span(row["otel_endpoint"], api_key)

    if ok:
        return OtelTestResponse(ok=True, latency_ms=latency_ms)
    return OtelTestResponse(ok=False, error=err or "connection refused")
