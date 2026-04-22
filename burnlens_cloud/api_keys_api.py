"""API key management endpoints: create, list, revoke.

Plaintext keys are emitted EXACTLY ONCE at creation and never stored or re-emitted.
Callers must capture the `key` field from POST /api-keys and persist it client-side.

Per-plan cap enforcement uses `resolve_limits(workspace_id).api_key_count` as the
limit. Over-cap attempts return 402 with the D-14 standardized body.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from .auth import verify_token, generate_api_key, hash_api_key, invalidate_api_key_cache
from .config import settings
from .database import execute_query
from .models import ApiKey, ApiKeyCreateRequest, ApiKeyCreateResponse, TokenPayload
from .plans import resolve_limits

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


_PLAN_PRICE_ORDER = ("free", "cloud", "teams")


async def _lowest_plan_with_api_key_count(current: int) -> Optional[str]:
    """Cheapest plan whose api_key_count > current, or None if no plan exceeds it."""
    rows = await execute_query(
        "SELECT plan, api_key_count FROM plan_limits WHERE api_key_count IS NULL OR api_key_count > $1",
        current,
    )
    if not rows:
        return None
    plans_ok = {row["plan"] for row in rows}
    for candidate in _PLAN_PRICE_ORDER:
        if candidate in plans_ok:
            return candidate
    return None


@router.post("", response_model=ApiKeyCreateResponse)
async def create_api_key(
    body: ApiKeyCreateRequest,
    token: TokenPayload = Depends(verify_token),
) -> ApiKeyCreateResponse:
    """Create a new API key for the caller's workspace.

    Returns the plaintext `key` ONCE — it is never stored or re-emitted.
    402 if the workspace is at or above its plan's api_key_count cap.
    """
    limits = await resolve_limits(token.workspace_id)
    cap = limits.api_key_count if limits is not None else None  # may be None meaning "unlimited"

    count_rows = await execute_query(
        "SELECT COUNT(*) AS c FROM api_keys WHERE workspace_id = $1 AND revoked_at IS NULL",
        str(token.workspace_id),
    )
    current = int(count_rows[0]["c"]) if count_rows else 0

    if cap is not None and current >= cap:
        required = await _lowest_plan_with_api_key_count(current)
        raise HTTPException(
            status_code=402,
            detail={
                "error": "api_key_limit_reached",
                "limit": cap,
                "current": current,
                "required_plan": required,
                "upgrade_url": f"{settings.burnlens_frontend_url}/settings#billing",
            },
        )

    plaintext = generate_api_key()
    key_hash_value = hash_api_key(plaintext)
    name = (body.name or "Primary").strip() or "Primary"

    row = await execute_query(
        """
        INSERT INTO api_keys (workspace_id, key_hash, last4, name, created_by_user_id)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, name, last4, created_at, revoked_at
        """,
        str(token.workspace_id),
        key_hash_value,
        plaintext[-4:],
        name,
        str(token.user_id) if getattr(token, "user_id", None) else None,
    )
    r = row[0]
    logger.info("api_key.created workspace=%s id=%s name=%s", token.workspace_id, r["id"], name)
    return ApiKeyCreateResponse(
        id=r["id"],
        name=r["name"],
        last4=r["last4"],
        created_at=r["created_at"],
        revoked_at=r["revoked_at"],
        key=plaintext,
    )


@router.get("", response_model=list[ApiKey])
async def list_api_keys(
    token: TokenPayload = Depends(verify_token),
) -> list[ApiKey]:
    """List API keys for the caller's workspace. Never returns plaintext or hash."""
    rows = await execute_query(
        """
        SELECT id, name, last4, created_at, revoked_at
        FROM api_keys
        WHERE workspace_id = $1
        ORDER BY created_at DESC
        """,
        str(token.workspace_id),
    )
    return [ApiKey(**r) for r in rows]


@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: UUID,
    token: TokenPayload = Depends(verify_token),
) -> dict:
    """Soft-revoke: sets revoked_at = now(). 404 if the key belongs to another workspace.

    404 (not 403) on cross-tenant access is deliberate — indistinguishability prevents
    cross-tenant enumeration of key ids.
    """
    result = await execute_query(
        """
        UPDATE api_keys
        SET revoked_at = NOW()
        WHERE id = $1 AND workspace_id = $2 AND revoked_at IS NULL
        RETURNING id, key_hash
        """,
        str(key_id),
        str(token.workspace_id),
    )
    if not result:
        raise HTTPException(status_code=404, detail={"error": "api_key_not_found"})

    revoked_hash = result[0]["key_hash"]

    # CR-02: evict the in-memory auth cache so the revoked key stops
    # authenticating immediately rather than remaining valid for up to
    # api_key_cache_ttl seconds.
    invalidate_api_key_cache(revoked_hash)

    logger.info("api_key.revoked workspace=%s id=%s", token.workspace_id, key_id)
    return {"ok": True, "id": str(key_id)}
