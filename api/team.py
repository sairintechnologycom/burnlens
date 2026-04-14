"""Team management — invites, members, roles, activity."""
from __future__ import annotations

import json
import logging
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from fastapi import APIRouter, Depends, HTTPException, Request

from . import config
from .auth import _encode_jwt, get_current_workspace, require_role
from .models import (
    AcceptRequest,
    ActivityEntry,
    InvitationInfo,
    InviteRequest,
    InviteResponse,
    MemberOut,
    MembersResponse,
    PendingInviteOut,
    RoleUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---- helpers ----------------------------------------------------------------

async def _log_activity(
    workspace_id: str,
    action: str,
    detail: dict | None = None,
    user_id: str | None = None,
) -> None:
    from .database import pool
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO workspace_activity (workspace_id, user_id, action, detail)
               VALUES ($1, $2, $3, $4)""",
            workspace_id,
            user_id,
            action,
            json.dumps(detail) if detail else None,
        )


def _send_invite_email(
    to_email: str, workspace_name: str, token: str, role: str
) -> None:
    """Send invitation email via SMTP. Fails silently if SMTP not configured."""
    if not config.SMTP_HOST:
        logger.warning("SMTP not configured — skipping invite email to %s", to_email)
        return

    accept_url = f"https://burnlens.app/invite/{token}"
    msg = EmailMessage()
    msg["Subject"] = f"You've been invited to {workspace_name} on BurnLens"
    msg["From"] = config.SMTP_FROM
    msg["To"] = to_email
    msg.set_content(
        f"You've been invited to join {workspace_name} on BurnLens as a {role}.\n\n"
        f"Accept your invitation:\n{accept_url}\n\n"
        f"This link expires in {config.INVITATION_EXPIRY_HOURS} hours."
    )

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.starttls()
            if config.SMTP_USER:
                server.login(config.SMTP_USER, config.SMTP_PASS)
            server.send_message(msg)
        logger.info("Invite email sent to %s", to_email)
    except Exception:
        logger.exception("Failed to send invite email to %s", to_email)


# ---- invite -----------------------------------------------------------------

@router.post("/team/invite", response_model=InviteResponse)
async def invite_member(
    body: InviteRequest,
    ws: dict = Depends(require_role("owner", "admin")),
):
    """Send an invitation to join this workspace."""
    # Plan gate
    if ws["plan"] not in ("teams", "enterprise"):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "teams_plan_required",
                "upgrade_url": "https://burnlens.app/signup",
            },
        )

    from .database import pool
    async with pool.acquire() as conn:
        # Seat limit check
        member_count = await conn.fetchval(
            "SELECT COUNT(*) FROM workspace_members WHERE workspace_id = $1 AND active = true",
            ws["id"],
        )
        seat_limit = config.PLAN_SEAT_LIMITS.get(ws["plan"])
        if seat_limit is not None and member_count >= seat_limit:
            raise HTTPException(
                status_code=422,
                detail={"error": "seat_limit_reached", "limit": seat_limit},
            )

        # Already a member?
        existing = await conn.fetchrow(
            """SELECT id FROM workspace_members
               WHERE workspace_id = $1
                 AND user_id = (SELECT id FROM users WHERE email = $2)
                 AND active = true""",
            ws["id"],
            body.email,
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail={"error": "already_member"},
            )

        # Create invitation
        token = secrets.token_hex(32)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=config.INVITATION_EXPIRY_HOURS)

        row = await conn.fetchrow(
            """INSERT INTO invitations (workspace_id, email, role, token, invited_by, expires_at)
               VALUES ($1, $2, $3, $4, $5, $6)
               RETURNING id, expires_at""",
            ws["id"],
            body.email,
            body.role,
            token,
            ws["user_id"],
            expires,
        )

    # Send email (non-blocking failure OK)
    _send_invite_email(body.email, ws["name"], token, body.role)

    # Log activity
    await _log_activity(
        ws["id"], "invite_sent",
        {"email": body.email, "role": body.role},
        ws["user_id"],
    )

    return InviteResponse(invitation_id=row["id"], expires_at=row["expires_at"])


# ---- accept invite ----------------------------------------------------------

@router.get("/invite/{token}", response_model=InvitationInfo)
async def get_invitation(token: str):
    """Look up an invitation by token (public — no auth)."""
    from .database import pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT i.*, w.name AS workspace_name,
                      (SELECT email FROM users WHERE id = i.invited_by) AS inviter_email
               FROM invitations i
               JOIN workspaces w ON w.id = i.workspace_id
               WHERE i.token = $1""",
            token,
        )

    if not row:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if row["accepted_at"]:
        raise HTTPException(
            status_code=409, detail={"error": "already_accepted"}
        )
    if row["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=410, detail={"error": "invitation_expired"}
        )

    return InvitationInfo(
        workspace_name=row["workspace_name"],
        role=row["role"],
        inviter_email=row["inviter_email"],
        expires_at=row["expires_at"],
    )


@router.post("/invite/{token}/accept")
async def accept_invitation(token: str, body: AcceptRequest):
    """Accept an invitation — creates user + membership, returns JWT."""
    from .database import pool
    async with pool.acquire() as conn:
        inv = await conn.fetchrow(
            """SELECT i.*, w.plan
               FROM invitations i
               JOIN workspaces w ON w.id = i.workspace_id
               WHERE i.token = $1""",
            token,
        )

        if not inv:
            raise HTTPException(status_code=404, detail="Invitation not found")
        if inv["accepted_at"]:
            raise HTTPException(
                status_code=409, detail={"error": "already_accepted"}
            )
        if inv["expires_at"] < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=410, detail={"error": "invitation_expired"}
            )

        now = datetime.now(timezone.utc)

        # Upsert user
        user = await conn.fetchrow(
            """INSERT INTO users (email, name, last_login)
               VALUES ($1, $2, $3)
               ON CONFLICT (email) DO UPDATE SET name = $2, last_login = $3
               RETURNING id""",
            body.email,
            body.name,
            now,
        )
        user_id = str(user["id"])

        # Create membership
        await conn.execute(
            """INSERT INTO workspace_members (workspace_id, user_id, role, invited_by, joined_at)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (workspace_id, user_id) DO UPDATE SET active = true, role = $3, joined_at = $5""",
            inv["workspace_id"],
            user_id,
            inv["role"],
            inv["invited_by"],
            now,
        )

        # Mark invitation accepted
        await conn.execute(
            "UPDATE invitations SET accepted_at = $1 WHERE id = $2",
            now,
            inv["id"],
        )

    ws_id = str(inv["workspace_id"])
    plan = inv["plan"]

    await _log_activity(
        ws_id, "member_joined",
        {"email": body.email, "role": inv["role"]},
        user_id,
    )

    jwt_token = _encode_jwt(ws_id, plan, user_id=user_id, role=inv["role"])
    return {"token": jwt_token, "plan": plan, "role": inv["role"]}


# ---- members ----------------------------------------------------------------

@router.get("/team/members", response_model=MembersResponse)
async def list_members(
    ws: dict = Depends(get_current_workspace),
):
    """List workspace members and pending invitations."""
    from .database import pool
    async with pool.acquire() as conn:
        members_rows = await conn.fetch(
            """SELECT wm.user_id, u.email, u.name, wm.role, wm.joined_at, u.last_login, wm.active
               FROM workspace_members wm
               JOIN users u ON u.id = wm.user_id
               WHERE wm.workspace_id = $1 AND wm.active = true
               ORDER BY wm.joined_at""",
            ws["id"],
        )
        pending_rows = await conn.fetch(
            """SELECT email, role, created_at, expires_at
               FROM invitations
               WHERE workspace_id = $1 AND accepted_at IS NULL AND expires_at > $2
               ORDER BY created_at DESC""",
            ws["id"],
            datetime.now(timezone.utc),
        )

    members = [
        MemberOut(
            user_id=r["user_id"],
            email=r["email"],
            name=r["name"],
            role=r["role"],
            joined_at=r["joined_at"],
            last_login=r["last_login"],
            active=r["active"],
        )
        for r in members_rows
    ]
    pending = [
        PendingInviteOut(
            email=r["email"],
            role=r["role"],
            created_at=r["created_at"],
            expires_at=r["expires_at"],
        )
        for r in pending_rows
    ]

    return MembersResponse(members=members, pending=pending)


@router.delete("/team/members/{user_id}")
async def remove_member(
    user_id: str,
    ws: dict = Depends(require_role("owner", "admin")),
):
    """Deactivate a workspace member."""
    if ws["user_id"] == user_id:
        raise HTTPException(status_code=400, detail={"error": "cannot_remove_self"})

    from .database import pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT role FROM workspace_members WHERE workspace_id = $1 AND user_id = $2 AND active = true",
            ws["id"],
            user_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Member not found")
        if row["role"] == "owner":
            raise HTTPException(
                status_code=400, detail={"error": "cannot_remove_owner"}
            )

        await conn.execute(
            "UPDATE workspace_members SET active = false WHERE workspace_id = $1 AND user_id = $2",
            ws["id"],
            user_id,
        )

    await _log_activity(ws["id"], "member_removed", {"user_id": user_id}, ws["user_id"])
    return {"ok": True}


@router.patch("/team/members/{user_id}")
async def change_role(
    user_id: str,
    body: RoleUpdate,
    ws: dict = Depends(require_role("owner")),
):
    """Change a member's role (owner only)."""
    from .database import pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT role FROM workspace_members WHERE workspace_id = $1 AND user_id = $2 AND active = true",
            ws["id"],
            user_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Member not found")
        if row["role"] == "owner":
            raise HTTPException(
                status_code=400, detail={"error": "cannot_change_owner_role"}
            )

        await conn.execute(
            "UPDATE workspace_members SET role = $1 WHERE workspace_id = $2 AND user_id = $3",
            body.role,
            ws["id"],
            user_id,
        )

    await _log_activity(
        ws["id"], "role_changed",
        {"user_id": user_id, "new_role": body.role},
        ws["user_id"],
    )
    return {"ok": True}


# ---- activity ---------------------------------------------------------------

@router.get("/api/activity", response_model=list[ActivityEntry])
async def activity_log(
    limit: int = 50,
    ws: dict = Depends(require_role("owner", "admin")),
):
    """Return recent workspace activity."""
    from .database import pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT wa.action, wa.detail, wa.created_at,
                      (SELECT email FROM users WHERE id = wa.user_id) AS user_email
               FROM workspace_activity wa
               WHERE wa.workspace_id = $1
               ORDER BY wa.created_at DESC
               LIMIT $2""",
            ws["id"],
            limit,
        )

    return [
        ActivityEntry(
            action=r["action"],
            detail=json.loads(r["detail"]) if r["detail"] else None,
            created_at=r["created_at"],
            user_email=r["user_email"],
        )
        for r in rows
    ]
