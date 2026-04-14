"""Signup, login, JWT helpers, and waitlist."""
from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from jose import JWTError, jwt

from . import config
from .models import (
    LoginRequest,
    LoginResponse,
    SignupRequest,
    SignupResponse,
    WaitlistRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---- helpers ----------------------------------------------------------------

def generate_api_key() -> str:
    """Return a new API key: bl_live_ + 64 hex chars."""
    return f"bl_live_{secrets.token_hex(32)}"


def _encode_jwt(workspace_id: str, plan: str) -> str:
    now = int(time.time())
    payload = {
        "workspace_id": workspace_id,
        "plan": plan,
        "iat": now,
        "exp": now + config.JWT_EXPIRATION_SECONDS,
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def _decode_jwt(token: str) -> dict | None:
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except JWTError:
        return None


async def get_current_workspace(request: Request) -> dict:
    """FastAPI dependency: extract workspace from Bearer JWT."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    payload = _decode_jwt(auth[7:])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    from .database import pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, plan, active FROM workspaces WHERE id = $1",
            payload["workspace_id"],
        )
    if not row or not row["active"]:
        raise HTTPException(status_code=401, detail="Workspace not found or inactive")

    return {
        "id": str(row["id"]),
        "name": row["name"],
        "plan": row["plan"],
    }


# ---- routes -----------------------------------------------------------------

@router.post("/auth/signup", response_model=SignupResponse)
async def signup(body: SignupRequest):
    """Create a new workspace."""
    if "@" not in body.email:
        raise HTTPException(status_code=422, detail="Invalid email")
    if not (2 <= len(body.workspace_name) <= 60):
        raise HTTPException(status_code=422, detail="workspace_name must be 2-60 chars")

    api_key = generate_api_key()

    from .database import pool
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM workspaces WHERE owner_email = $1", body.email
        )
        if existing:
            raise HTTPException(status_code=409, detail={"error": "email_already_registered"})

        row = await conn.fetchrow(
            """
            INSERT INTO workspaces (name, owner_email, plan, api_key, created_at)
            VALUES ($1, $2, 'free', $3, $4)
            RETURNING id
            """,
            body.workspace_name,
            body.email,
            api_key,
            datetime.now(timezone.utc),
        )

    logger.info("Workspace created: %s", row["id"])
    return SignupResponse(
        api_key=api_key,
        workspace_id=row["id"],
        workspace_name=body.workspace_name,
    )


@router.post("/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    """Login with API key, returns JWT."""
    if not body.api_key.startswith("bl_live_"):
        raise HTTPException(status_code=401, detail={"error": "invalid_api_key"})

    from .database import pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, plan, active FROM workspaces WHERE api_key = $1",
            body.api_key,
        )

    if not row or not row["active"]:
        raise HTTPException(status_code=401, detail={"error": "invalid_api_key"})

    token = _encode_jwt(str(row["id"]), row["plan"])
    return LoginResponse(
        token=token,
        workspace_name=row["name"],
        plan=row["plan"],
    )


@router.post("/api/waitlist")
async def add_to_waitlist(body: WaitlistRequest):
    """Add email to waitlist (ignore duplicates)."""
    from .database import pool
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO waitlist (email, created_at)
            VALUES ($1, $2)
            ON CONFLICT (email) DO NOTHING
            """,
            body.email,
            datetime.now(timezone.utc),
        )
    return {"ok": True}
