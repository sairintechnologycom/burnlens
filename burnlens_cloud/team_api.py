"""Team management API endpoints."""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Query


def _hash_invitation_token(token: str) -> str:
    """Derive the DB-storage hash for an invitation token.

    Tokens are 128-bit uuid4-derived values, so plain SHA-256 is sufficient —
    no slow KDF is needed (the attacker cannot dictionary-attack a high-entropy
    secret). The purpose of hashing is to ensure a DB leak does not yield
    usable invite-acceptance credentials.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

from .config import settings
from .database import execute_query, execute_insert
from .plans import resolve_limits
from .auth import verify_token, TokenPayload, upsert_user, ensure_workspace_member, require_feature
from .models import (
    WorkspaceMemberResponse,
    InvitationRequest,
    InvitationResponse,
    MemberRoleUpdate,
    ActivityLogEntry,
    UserResponse,
    TeamActivityResponse,
)
from .email import send_invitation_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/team", tags=["team"])

# Role hierarchy for permission checking
ROLE_HIERARCHY = {"viewer": 0, "admin": 1, "owner": 2}


async def require_role(required_role: str, token: TokenPayload):
    """
    Check if user has required role.
    Raises 403 HTTPException if insufficient permissions.
    """
    if ROLE_HIERARCHY.get(token.role, -1) < ROLE_HIERARCHY.get(required_role, 999):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "insufficient_role",
                "required": required_role,
                "current": token.role,
            },
        )


async def log_activity(
    workspace_id: UUID, user_id: UUID, action: str, detail: dict
):
    """Log admin action to workspace_activity table."""
    try:
        await execute_insert(
            """
            INSERT INTO workspace_activity (workspace_id, user_id, action, detail, created_at)
            VALUES ($1, $2, $3, $4, $5)
            """,
            str(workspace_id),
            str(user_id),
            action,
            json.dumps(detail),
            datetime.utcnow(),
        )
    except Exception as e:
        logger.error(f"Failed to log activity: {e}")
        # Don't raise - activity logging failures shouldn't break the request


async def get_seat_limit(workspace_id) -> int:
    """Resolve the workspace's effective seat limit via plan_limits + overrides.

    Returns a large sentinel (10**9) when the resolved seat_count is None
    (meaning "unlimited" per Phase 6 D-02) so check_seat_limit's "current >= limit"
    comparison behaves correctly for unlimited plans.
    """
    limits = await resolve_limits(workspace_id)
    return limits.seat_count if limits is not None and limits.seat_count is not None else 10**9


async def check_seat_limit(workspace_id: UUID, plan: str) -> bool:
    """Check if workspace is at seat limit.

    The `plan` parameter is retained for backwards compatibility with any
    external caller; the authoritative limit now comes from `resolve_limits`
    (plan_limits + per-workspace overrides) via `get_seat_limit(workspace_id)`.
    """
    limit = await get_seat_limit(workspace_id)
    result = await execute_query(
        """
        SELECT COUNT(*) as count FROM workspace_members
        WHERE workspace_id = $1 AND active = true
        """,
        str(workspace_id),
    )
    current_count = result[0]["count"] if result else 0
    return current_count >= limit


_PLAN_PRICE_ORDER = ("free", "cloud", "teams")


async def _current_seat_count(workspace_id) -> int:
    """Active-member count for the workspace (drives D-14 `current` field)."""
    rows = await execute_query(
        """
        SELECT COUNT(*) AS c
        FROM workspace_members
        WHERE workspace_id = $1 AND active = true
        """,
        str(workspace_id),
    )
    return int(rows[0]["c"]) if rows else 0


async def _lowest_plan_with_seat_count(current: int) -> Optional[str]:
    """Cheapest plan whose seat_count > current (for D-14 `required_plan`)."""
    rows = await execute_query(
        "SELECT plan FROM plan_limits WHERE seat_count IS NULL OR seat_count > $1",
        current,
    )
    if not rows:
        return None
    plans_ok = {row["plan"] for row in rows}
    for candidate in _PLAN_PRICE_ORDER:
        if candidate in plans_ok:
            return candidate
    return None


@router.get(
    "/members",
    response_model=List[WorkspaceMemberResponse],
    dependencies=[Depends(require_feature("teams_view"))],
)
async def list_members(token: TokenPayload = Depends(verify_token)):
    """List all members of workspace."""
    # Any authenticated workspace member can list members
    result = await execute_query(
        """
        SELECT
            wm.id, wm.user_id, wm.role, wm.joined_at, wm.invited_by,
            u.email, u.name, u.last_login
        FROM workspace_members wm
        JOIN users u ON wm.user_id = u.id
        WHERE wm.workspace_id = $1 AND wm.active = true
        ORDER BY wm.joined_at ASC
        """,
        str(token.workspace_id),
    )

    members = []
    for row in result:
        members.append(
            WorkspaceMemberResponse(
                id=row["id"],
                email=row["email"],
                name=row["name"],
                role=row["role"],
                joined_at=row["joined_at"],
                last_login=row["last_login"],
                invited_by=row["invited_by"],
            )
        )

    return members


@router.delete(
    "/members/{member_id}",
    dependencies=[Depends(require_feature("teams_view"))],
)
async def remove_member(
    member_id: UUID,
    token: TokenPayload = Depends(verify_token),
):
    """Remove a member from workspace (admin+ only)."""
    await require_role("admin", token)

    # Check if member exists
    result = await execute_query(
        """
        SELECT user_id, role FROM workspace_members
        WHERE id = $1 AND workspace_id = $2 AND active = true
        """,
        str(member_id),
        str(token.workspace_id),
    )

    if not result:
        raise HTTPException(status_code=404, detail="Member not found")

    member_user_id = result[0]["user_id"]
    member_role = result[0]["role"]

    # Check if trying to remove last owner
    if member_role == "owner":
        owner_count = await execute_query(
            """
            SELECT COUNT(*) as count FROM workspace_members
            WHERE workspace_id = $1 AND role = 'owner' AND active = true
            """,
            str(token.workspace_id),
        )
        if owner_count[0]["count"] <= 1:
            raise HTTPException(
                status_code=400, detail="Cannot remove the last owner of workspace"
            )

    # Deactivate member
    try:
        await execute_insert(
            """
            UPDATE workspace_members SET active = false
            WHERE id = $1
            """,
            str(member_id),
        )
        logger.info(f"Removed member {member_id} from workspace {token.workspace_id}")
    except Exception as e:
        logger.error(f"Failed to remove member: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove member")

    # Log activity
    await log_activity(
        token.workspace_id,
        token.user_id,
        "member_removed",
        {"target_user_id": str(member_user_id), "role": member_role},
    )

    return {"status": "removed", "user_id": str(member_user_id)}


@router.patch(
    "/members/{member_id}",
    dependencies=[Depends(require_feature("teams_view"))],
)
async def update_member_role(
    member_id: UUID,
    update: MemberRoleUpdate,
    token: TokenPayload = Depends(verify_token),
):
    """Update member role (admin+ only)."""
    await require_role("admin", token)

    # Validate role
    if update.role not in ["viewer", "admin", "owner"]:
        raise HTTPException(status_code=400, detail="Invalid role")

    # Get current member info
    result = await execute_query(
        """
        SELECT user_id, role FROM workspace_members
        WHERE id = $1 AND workspace_id = $2 AND active = true
        """,
        str(member_id),
        str(token.workspace_id),
    )

    if not result:
        raise HTTPException(status_code=404, detail="Member not found")

    member_user_id = result[0]["user_id"]
    old_role = result[0]["role"]

    # Check if trying to downgrade last owner
    if old_role == "owner" and update.role != "owner":
        owner_count = await execute_query(
            """
            SELECT COUNT(*) as count FROM workspace_members
            WHERE workspace_id = $1 AND role = 'owner' AND active = true
            """,
            str(token.workspace_id),
        )
        if owner_count[0]["count"] <= 1:
            raise HTTPException(
                status_code=400, detail="Cannot downgrade the last owner"
            )

    # Update role
    try:
        await execute_insert(
            """
            UPDATE workspace_members SET role = $1
            WHERE id = $2
            """,
            update.role,
            str(member_id),
        )
        logger.info(
            f"Updated member {member_id} role from {old_role} to {update.role}"
        )
    except Exception as e:
        logger.error(f"Failed to update member role: {e}")
        raise HTTPException(status_code=500, detail="Failed to update member role")

    # Log activity
    await log_activity(
        token.workspace_id,
        token.user_id,
        "role_changed",
        {
            "target_user_id": str(member_user_id),
            "previous_role": old_role,
            "new_role": update.role,
        },
    )

    return {"id": str(member_id), "role": update.role}


@router.post(
    "/invite",
    response_model=InvitationResponse,
    dependencies=[Depends(require_feature("teams_view"))],
)
async def invite_member(
    request: InvitationRequest,
    token: TokenPayload = Depends(verify_token),
):
    """Send invitation to join workspace (admin+ only)."""
    await require_role("admin", token)

    # Get workspace info
    ws_result = await execute_query(
        "SELECT plan, name FROM workspaces WHERE id = $1",
        str(token.workspace_id),
    )
    if not ws_result:
        raise HTTPException(status_code=404, detail="Workspace not found")

    plan = ws_result[0]["plan"]
    ws_name = ws_result[0]["name"]

    # Plan-gate is now enforced at the FastAPI dependency layer via
    # `Depends(require_feature("teams_view"))` on this route. Free/Cloud
    # workspaces hit 402 BEFORE this handler body runs (D-18).

    # Check if email already a member
    existing = await execute_query(
        """
        SELECT user_id FROM workspace_members wm
        JOIN users u ON wm.user_id = u.id
        WHERE wm.workspace_id = $1 AND u.email = $2 AND wm.active = true
        """,
        str(token.workspace_id),
        request.email,
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="User is already a member of this workspace",
        )

    # Check seat limit
    if await check_seat_limit(token.workspace_id, plan):
        limit = await get_seat_limit(token.workspace_id)
        current = await _current_seat_count(token.workspace_id)
        required = await _lowest_plan_with_seat_count(current)
        raise HTTPException(
            status_code=402,
            detail={
                "error": "seat_limit_reached",
                "limit": limit,
                "current": current,
                "required_plan": required,
                "upgrade_url": f"{settings.burnlens_frontend_url}/settings#billing",
            },
        )

    # Validate role
    if request.role not in ["viewer", "admin"]:
        raise HTTPException(status_code=400, detail="Invalid role (must be viewer or admin)")

    # Create invitation
    invitation_id = str(uuid4())
    token_str = str(uuid4()).replace("-", "")[:32]  # 32-char hex token
    expires_at = datetime.utcnow() + timedelta(hours=settings.invitation_expiry_hours)

    try:
        await execute_insert(
            """
            INSERT INTO invitations
            (id, workspace_id, email, role, token_hash, invited_by, expires_at, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            invitation_id,
            str(token.workspace_id),
            request.email,
            request.role,
            _hash_invitation_token(token_str),
            str(token.user_id),
            expires_at,
            datetime.utcnow(),
        )
        logger.info(
            f"Created invitation {invitation_id} for {request.email} to workspace {token.workspace_id}"
        )
    except Exception as e:
        logger.error(f"Failed to create invitation: {e}")
        raise HTTPException(status_code=500, detail="Failed to create invitation")

    # Send email asynchronously
    user_result = await execute_query(
        "SELECT name FROM users WHERE id = $1",
        str(token.user_id),
    )
    invited_by_name = user_result[0]["name"] if user_result else None

    await send_invitation_email(
        request.email,
        ws_name,
        token_str,
        invited_by_name,
    )

    # Log activity
    await log_activity(
        token.workspace_id,
        token.user_id,
        "invite_sent",
        {"email": request.email, "role": request.role},
    )

    return InvitationResponse(
        id=UUID(invitation_id),
        email=request.email,
        token=token_str,
        expires_at=expires_at,
        created_at=datetime.utcnow(),
    )


@router.get(
    "/activity",
    dependencies=[Depends(require_feature("teams_view"))],
)
async def get_activity(
    token: TokenPayload = Depends(verify_token),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Get workspace activity log (admin+ only)."""
    await require_role("admin", token)

    # Get total count
    count_result = await execute_query(
        """
        SELECT COUNT(*) as count FROM workspace_activity
        WHERE workspace_id = $1
        """,
        str(token.workspace_id),
    )
    total = count_result[0]["count"] if count_result else 0

    # Get activity entries
    result = await execute_query(
        """
        SELECT
            wa.id, wa.action, wa.detail, wa.created_at,
            u.id as user_id, u.email, u.name
        FROM workspace_activity wa
        LEFT JOIN users u ON wa.user_id = u.id
        WHERE wa.workspace_id = $1
        ORDER BY wa.created_at DESC
        LIMIT $2 OFFSET $3
        """,
        str(token.workspace_id),
        limit,
        offset,
    )

    entries = []
    for row in result:
        user = None
        if row["user_id"]:
            user = UserResponse(
                id=row["user_id"],
                email=row["email"],
                name=row["name"],
            )

        entries.append(
            ActivityLogEntry(
                id=row["id"],
                action=row["action"],
                detail=row["detail"],
                created_at=row["created_at"],
                user=user,
            )
        )

    return TeamActivityResponse(
        entries=entries,
        total=total,
        limit=limit,
        offset=offset,
    )
