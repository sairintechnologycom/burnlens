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
from .models import (
    ApiKey,
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyUpdateRequest,
    TokenPayload,
)
from .plans import resolve_limits

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/account/api-keys", tags=["api-keys"])


def _viewer_creator_filter(token: TokenPayload) -> Optional[str]:
    """Return token.user_id (str) when role is 'viewer', else None.

    Used as the $N parameter in queries that conditionally narrow scope:
        AND ($N::uuid IS NULL OR created_by_user_id = $N)
    Per Phase 16 D-01/D-03/D-04: viewers see/edit/revoke only keys they
    created; cross-creator access returns 404 (D-04 indistinguishability).
    """
    return str(token.user_id) if token.role == "viewer" else None


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
        RETURNING id, name, last4, created_at, revoked_at, paused_at
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
    """List API keys for the caller's workspace. Never returns plaintext or hash.

    Phase 16 (D-01, D-05): viewers see only keys they created;
    response includes last_used_at.
    """
    creator_filter = _viewer_creator_filter(token)
    rows = await execute_query(
        """
        SELECT id, name, last4, created_at, revoked_at, last_used_at, paused_at
        FROM api_keys
        WHERE workspace_id = $1
          AND ($2::uuid IS NULL OR created_by_user_id = $2)
        ORDER BY created_at DESC
        """,
        str(token.workspace_id),
        creator_filter,
    )
    return [ApiKey(**r) for r in rows]


@router.patch("/{key_id}", response_model=ApiKey)
async def update_api_key(
    key_id: UUID,
    body: ApiKeyUpdateRequest,
    token: TokenPayload = Depends(verify_token),
) -> ApiKey:
    """Rename an API key (Phase 16 APIKEY-04 / D-09, D-10, D-11).

    Single editable field — `name`. Hash is unchanged so the cache stays
    valid (no invalidate_api_key_cache call). Cross-tenant or wrong-creator
    edit returns 404 per D-04 indistinguishability.

    Revoked keys are immutable — terminal state (CR-01 closure). PATCH on a
    revoked key returns 404 with the same envelope as DELETE, preserving the
    D-04 indistinguishability rule.
    """
    creator_filter = _viewer_creator_filter(token)
    rows = await execute_query(
        """
        UPDATE api_keys
        SET name = $1
        WHERE id = $2
          AND workspace_id = $3
          AND revoked_at IS NULL
          AND ($4::uuid IS NULL OR created_by_user_id = $4)
        RETURNING id, name, last4, created_at, revoked_at, paused_at, last_used_at
        """,
        body.name,
        str(key_id),
        str(token.workspace_id),
        creator_filter,
    )
    if not rows:
        raise HTTPException(status_code=404, detail={"error": "api_key_not_found"})
    logger.info("api_key.renamed workspace=%s id=%s", token.workspace_id, key_id)
    return ApiKey(**rows[0])


@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: UUID,
    token: TokenPayload = Depends(verify_token),
) -> dict:
    """Soft-revoke: sets revoked_at = now(). 404 if the key belongs to another workspace.

    404 (not 403) on cross-tenant access is deliberate — indistinguishability prevents
    cross-tenant enumeration of key ids.
    """
    creator_filter = _viewer_creator_filter(token)
    result = await execute_query(
        """
        UPDATE api_keys
        SET revoked_at = NOW()
        WHERE id = $1
          AND workspace_id = $2
          AND revoked_at IS NULL
          AND ($3::uuid IS NULL OR created_by_user_id = $3)
        RETURNING id, key_hash
        """,
        str(key_id),
        str(token.workspace_id),
        creator_filter,
    )
    if not result:
        raise HTTPException(status_code=404, detail={"error": "api_key_not_found"})

    revoked_hash = result[0]["key_hash"]

    # CR-02: evict the in-memory auth cache so the revoked key stops
    # authenticating immediately rather than remaining valid for up to
    # api_key_cache_ttl seconds.
    invalidate_api_key_cache(revoked_hash)

    # WR-02: if this key's hash was backfilled from the legacy
    # workspaces.api_key_hash column (dual-read transition), clear the
    # legacy column so the fallback branch in get_workspace_by_api_key
    # cannot silently re-authenticate the same plaintext after revoke.
    await execute_query(
        """
        UPDATE workspaces
        SET api_key_hash = NULL, api_key_last4 = NULL
        WHERE id = $1 AND api_key_hash = $2
        """,
        str(token.workspace_id),
        revoked_hash,
    )

    logger.info("api_key.revoked workspace=%s id=%s", token.workspace_id, key_id)
    return {"ok": True, "id": str(key_id)}


@router.post("/{key_id}/pause", response_model=ApiKey)
async def pause_api_key(
    key_id: UUID,
    token: TokenPayload = Depends(verify_token),
) -> ApiKey:
    """Pause an API key: sets paused_at = now()."""
    creator_filter = _viewer_creator_filter(token)
    result = await execute_query(
        """
        UPDATE api_keys
        SET paused_at = NOW()
        WHERE id = $1
          AND workspace_id = $2
          AND revoked_at IS NULL
          AND ($3::uuid IS NULL OR created_by_user_id = $3)
        RETURNING id, name, last4, created_at, revoked_at, paused_at, last_used_at, key_hash
        """,
        str(key_id),
        str(token.workspace_id),
        creator_filter,
    )
    if not result:
        raise HTTPException(status_code=404, detail={"error": "api_key_not_found"})

    invalidate_api_key_cache(result[0]["key_hash"])
    logger.info("api_key.paused workspace=%s id=%s", token.workspace_id, key_id)
    return ApiKey(**result[0])


@router.post("/{key_id}/resume", response_model=ApiKey)
async def resume_api_key(
    key_id: UUID,
    token: TokenPayload = Depends(verify_token),
) -> ApiKey:
    """Resume a paused API key: sets paused_at = NULL."""
    creator_filter = _viewer_creator_filter(token)
    result = await execute_query(
        """
        UPDATE api_keys
        SET paused_at = NULL
        WHERE id = $1
          AND workspace_id = $2
          AND revoked_at IS NULL
          AND ($3::uuid IS NULL OR created_by_user_id = $3)
        RETURNING id, name, last4, created_at, revoked_at, paused_at, last_used_at, key_hash
        """,
        str(key_id),
        str(token.workspace_id),
        creator_filter,
    )
    if not result:
        raise HTTPException(status_code=404, detail={"error": "api_key_not_found"})

    # No need to invalidate cache if resuming, as it wasn't in cache while paused (or expired)
    logger.info("api_key.resumed workspace=%s id=%s", token.workspace_id, key_id)
    return ApiKey(**result[0])
