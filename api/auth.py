"""Signup, login, JWT helpers, waitlist, and OAuth SSO."""
from __future__ import annotations

import logging
import secrets
import time
import urllib.parse
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
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


def _encode_jwt(
    workspace_id: str,
    plan: str,
    user_id: str | None = None,
    role: str = "owner",
) -> str:
    now = int(time.time())
    payload = {
        "workspace_id": workspace_id,
        "plan": plan,
        "user_id": user_id,
        "role": role,
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
    """FastAPI dependency: extract workspace + user context from Bearer JWT."""
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
        "user_id": payload.get("user_id"),
        "role": payload.get("role", "owner"),
    }


def require_role(*roles: str):
    """Dependency factory: require the current user's role to be in the allowed list."""
    async def _check(request: Request) -> dict:
        ws = await get_current_workspace(request)
        if ws["role"] not in roles:
            raise HTTPException(
                status_code=403,
                detail={"error": "insufficient_role", "required": roles[0]},
            )
        return ws
    return _check


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


# ---- SSO helpers ------------------------------------------------------------

async def _sso_upsert_user(
    email: str,
    name: str | None,
    google_id: str | None = None,
    github_id: str | None = None,
) -> str:
    """Upsert a user by SSO provider ID or email. Returns user_id as str."""
    from .database import pool
    now = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        # 1. Try match by provider ID
        if google_id:
            row = await conn.fetchrow(
                "SELECT id FROM users WHERE google_id = $1", google_id
            )
            if row:
                await conn.execute(
                    "UPDATE users SET last_login = $1 WHERE id = $2", now, row["id"]
                )
                return str(row["id"])

        if github_id:
            row = await conn.fetchrow(
                "SELECT id FROM users WHERE github_id = $1", github_id
            )
            if row:
                await conn.execute(
                    "UPDATE users SET last_login = $1 WHERE id = $2", now, row["id"]
                )
                return str(row["id"])

        # 2. Try match by email — link the SSO ID
        row = await conn.fetchrow("SELECT id FROM users WHERE email = $1", email)
        if row:
            if google_id:
                await conn.execute(
                    "UPDATE users SET google_id = $1, last_login = $2 WHERE id = $3",
                    google_id, now, row["id"],
                )
            elif github_id:
                await conn.execute(
                    "UPDATE users SET github_id = $1, last_login = $2 WHERE id = $3",
                    github_id, now, row["id"],
                )
            return str(row["id"])

        # 3. New user
        new = await conn.fetchrow(
            """INSERT INTO users (email, name, google_id, github_id, last_login)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING id""",
            email, name, google_id, github_id, now,
        )
        return str(new["id"])


async def _sso_resolve_workspace(user_id: str, email: str) -> dict | None:
    """Check workspace membership or auto-accept a pending invitation.

    Returns {workspace_id, plan, role} or None if no workspace found.
    """
    from .database import pool
    now = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        # Check existing membership
        member = await conn.fetchrow(
            """SELECT wm.workspace_id, w.plan, wm.role
               FROM workspace_members wm
               JOIN workspaces w ON w.id = wm.workspace_id
               WHERE wm.user_id = $1 AND wm.active = true
               LIMIT 1""",
            user_id,
        )
        if member:
            return {
                "workspace_id": str(member["workspace_id"]),
                "plan": member["plan"],
                "role": member["role"],
            }

        # Check if user is workspace owner (created via signup, not in members table)
        owner_ws = await conn.fetchrow(
            """SELECT id, plan FROM workspaces
               WHERE owner_email = $1 AND active = true
               LIMIT 1""",
            email,
        )
        if owner_ws:
            return {
                "workspace_id": str(owner_ws["id"]),
                "plan": owner_ws["plan"],
                "role": "owner",
            }

        # Check for pending invitation matching this email
        inv = await conn.fetchrow(
            """SELECT i.id, i.workspace_id, i.role, i.invited_by, w.plan
               FROM invitations i
               JOIN workspaces w ON w.id = i.workspace_id
               WHERE i.email = $1 AND i.accepted_at IS NULL AND i.expires_at > $2
               ORDER BY i.created_at DESC
               LIMIT 1""",
            email, now,
        )
        if inv:
            # Auto-accept the invitation (same logic as POST /invite/{token}/accept)
            await conn.execute(
                """INSERT INTO workspace_members (workspace_id, user_id, role, invited_by, joined_at)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (workspace_id, user_id)
                   DO UPDATE SET active = true, role = $3, joined_at = $5""",
                inv["workspace_id"], user_id, inv["role"], inv["invited_by"], now,
            )
            await conn.execute(
                "UPDATE invitations SET accepted_at = $1 WHERE id = $2",
                now, inv["id"],
            )
            return {
                "workspace_id": str(inv["workspace_id"]),
                "plan": inv["plan"],
                "role": inv["role"],
            }

    return None


def _callback_redirect(token: str) -> RedirectResponse:
    """Redirect to callback.html with JWT in URL fragment."""
    return RedirectResponse(
        url=f"/auth/callback.html#token={token}",
        status_code=302,
    )


def _signup_redirect(email: str, provider: str) -> RedirectResponse:
    """Redirect to signup with pre-filled email for users without a workspace."""
    qs = urllib.parse.urlencode({"email": email, "sso": provider})
    return RedirectResponse(url=f"/signup?{qs}", status_code=302)


# ---- Google OAuth -----------------------------------------------------------

@router.get("/auth/google")
async def google_auth(request: Request):
    """Redirect to Google OAuth consent screen."""
    state = secrets.token_urlsafe(32)
    # Store state in a signed cookie for CSRF protection
    redirect_uri = f"{config.BASE_URL}/auth/google/callback"
    params = urllib.parse.urlencode({
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "select_account",
    })
    response = RedirectResponse(
        url=f"https://accounts.google.com/o/oauth2/v2/auth?{params}",
        status_code=302,
    )
    response.set_cookie(
        key="oauth_state",
        value=state,
        max_age=600,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


@router.get("/auth/google/callback")
async def google_callback(request: Request, code: str = "", state: str = ""):
    """Exchange Google auth code for user profile, upsert, and redirect."""
    # CSRF check
    cookie_state = request.cookies.get("oauth_state", "")
    if not state or not cookie_state or state != cookie_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state (CSRF check failed)")

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    redirect_uri = f"{config.BASE_URL}/auth/google/callback"

    async with httpx.AsyncClient(timeout=15) as client:
        # Exchange code for tokens
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        if token_resp.status_code != 200:
            logger.error("Google token exchange failed: %s", token_resp.text)
            raise HTTPException(status_code=502, detail="Google authentication failed")

        tokens = token_resp.json()
        access_token = tokens.get("access_token")

        # Get user profile
        profile_resp = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if profile_resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to get Google profile")

        profile = profile_resp.json()

    google_id = profile["sub"]
    email = profile["email"]
    name = profile.get("name")

    user_id = await _sso_upsert_user(email, name, google_id=google_id)
    ws = await _sso_resolve_workspace(user_id, email)

    if not ws:
        return _signup_redirect(email, "google")

    jwt_token = _encode_jwt(ws["workspace_id"], ws["plan"], user_id=user_id, role=ws["role"])
    response = _callback_redirect(jwt_token)
    response.delete_cookie("oauth_state")
    return response


# ---- GitHub OAuth -----------------------------------------------------------

@router.get("/auth/github")
async def github_auth(request: Request):
    """Redirect to GitHub OAuth authorization."""
    state = secrets.token_urlsafe(32)
    redirect_uri = f"{config.BASE_URL}/auth/github/callback"
    params = urllib.parse.urlencode({
        "client_id": config.GITHUB_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "read:user user:email",
        "state": state,
    })
    response = RedirectResponse(
        url=f"https://github.com/login/oauth/authorize?{params}",
        status_code=302,
    )
    response.set_cookie(
        key="oauth_state",
        value=state,
        max_age=600,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


@router.get("/auth/github/callback")
async def github_callback(request: Request, code: str = "", state: str = ""):
    """Exchange GitHub auth code for user profile, upsert, and redirect."""
    cookie_state = request.cookies.get("oauth_state", "")
    if not state or not cookie_state or state != cookie_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state (CSRF check failed)")

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    async with httpx.AsyncClient(timeout=15) as client:
        # Exchange code for access token
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": config.GITHUB_CLIENT_ID,
                "client_secret": config.GITHUB_CLIENT_SECRET,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code != 200:
            logger.error("GitHub token exchange failed: %s", token_resp.text)
            raise HTTPException(status_code=502, detail="GitHub authentication failed")

        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(status_code=502, detail="GitHub did not return access token")

        gh_headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

        # Get user profile
        user_resp = await client.get(
            "https://api.github.com/user", headers=gh_headers,
        )
        if user_resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to get GitHub profile")
        gh_user = user_resp.json()

        # Get primary verified email
        emails_resp = await client.get(
            "https://api.github.com/user/emails", headers=gh_headers,
        )
        email = None
        if emails_resp.status_code == 200:
            for em in emails_resp.json():
                if em.get("primary") and em.get("verified"):
                    email = em["email"]
                    break
        if not email:
            email = gh_user.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="No verified email found on GitHub account")

    github_id = str(gh_user["id"])
    name = gh_user.get("name") or gh_user.get("login")

    user_id = await _sso_upsert_user(email, name, github_id=github_id)
    ws = await _sso_resolve_workspace(user_id, email)

    if not ws:
        return _signup_redirect(email, "github")

    jwt_token = _encode_jwt(ws["workspace_id"], ws["plan"], user_id=user_id, role=ws["role"])
    response = _callback_redirect(jwt_token)
    response.delete_cookie("oauth_state")
    return response
