import logging
import secrets
import time
from uuid import uuid4
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from passlib.hash import bcrypt

from .config import settings
from .database import execute_query, execute_insert
from .models import (
    LoginRequest,
    LoginResponse,
    SignupRequest,
    SignupResponse,
    TokenPayload,
    WorkspaceResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# API key cache: {api_key: (workspace_id, plan, timestamp)}
_api_key_cache: dict = {}


def generate_api_key() -> str:
    """Generate a new API key with 'bl_live_' prefix."""
    return f"bl_live_{secrets.token_hex(16)}"


def encode_jwt(workspace_id: str, user_id: str, role: str, plan: str) -> str:
    """Encode JWT token."""
    now = int(time.time())
    exp = now + settings.jwt_expiration_seconds

    payload = TokenPayload(
        workspace_id=workspace_id,
        user_id=user_id,
        role=role,
        plan=plan,
        iat=now,
        exp=exp,
    )

    return jwt.encode(
        payload.model_dump(),
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_jwt(token: str) -> Optional[TokenPayload]:
    """Decode and validate JWT token."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        return TokenPayload(**payload)
    except JWTError:
        return None


async def verify_token(request: Request) -> TokenPayload:
    """Extract and verify JWT from Authorization header."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    token = auth_header[7:]  # Remove "Bearer " prefix
    payload = decode_jwt(token)

    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return payload


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


async def upsert_user(
    email: str,
    name: Optional[str] = None,
    password: Optional[str] = None,
    google_id: Optional[str] = None,
    github_id: Optional[str] = None,
) -> str:
    """
    Upsert user by email, google_id, or github_id.
    Returns user_id.
    """
    password_hash = bcrypt.hash(password) if password else None

    # Try to find existing user
    if google_id:
        result = await execute_query(
            "SELECT id FROM users WHERE google_id = $1",
            google_id,
        )
        if result:
            return str(result[0]["id"])

    if github_id:
        result = await execute_query(
            "SELECT id FROM users WHERE github_id = $1",
            github_id,
        )
        if result:
            return str(result[0]["id"])

    # Check by email
    result = await execute_query(
        "SELECT id FROM users WHERE email = $1",
        email,
    )
    if result:
        user_id = str(result[0]["id"])
        # Update OAuth IDs if provided
        update_fields = []
        update_params = []
        param_idx = 1

        if google_id:
            update_fields.append(f"google_id = ${param_idx}")
            update_params.append(google_id)
            param_idx += 1

        if github_id:
            update_fields.append(f"github_id = ${param_idx}")
            update_params.append(github_id)
            param_idx += 1

        if password_hash:
            update_fields.append(f"password_hash = ${param_idx}")
            update_params.append(password_hash)
            param_idx += 1

        if update_fields:
            update_params.append(user_id)
            await execute_insert(
                f"UPDATE users SET {', '.join(update_fields)} WHERE id = ${param_idx}",
                *update_params,
            )

        return user_id

    # Create new user
    user_id = str(uuid4())
    try:
        await execute_insert(
            """
            INSERT INTO users (id, email, name, password_hash, google_id, github_id, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            user_id,
            email,
            name,
            password_hash,
            google_id,
            github_id,
            datetime.utcnow(),
        )
        logger.info(f"Created new user: {user_id} ({email})")
    except Exception as e:
        logger.error(f"Failed to create user: {e}")
        raise HTTPException(status_code=500, detail="Failed to create user")

    return user_id


async def ensure_workspace_member(
    workspace_id: str,
    user_id: str,
    role: str = "viewer",
) -> str:
    """
    Ensure user is member of workspace.
    Returns the user's role in the workspace.
    """
    # Check if already a member
    result = await execute_query(
        """
        SELECT role FROM workspace_members
        WHERE workspace_id = $1 AND user_id = $2 AND active = true
        """,
        workspace_id,
        user_id,
    )

    if result:
        return result[0]["role"]

    # Add as member
    member_id = str(uuid4())
    try:
        await execute_insert(
            """
            INSERT INTO workspace_members (id, workspace_id, user_id, role, joined_at)
            VALUES ($1, $2, $3, $4, $5)
            """,
            member_id,
            workspace_id,
            user_id,
            role,
            datetime.utcnow(),
        )
        logger.info(f"Added user {user_id} to workspace {workspace_id} as {role}")
    except Exception as e:
        logger.error(f"Failed to add workspace member: {e}")
        raise HTTPException(status_code=500, detail="Failed to add workspace member")

    return role


async def auto_migrate_user_for_workspace(workspace_id: str, workspace_owner_email: str) -> tuple:
    """
    Auto-migrate existing single-user workspace by creating user + member records.
    Called on first login to transparently add user/membership tracking.
    Returns: (user_id, role)
    """
    # Check if workspace already has members
    result = await execute_query(
        "SELECT COUNT(*) as count FROM workspace_members WHERE workspace_id = $1",
        workspace_id,
    )

    if result and result[0]["count"] > 0:
        # Already migrated
        return (None, None)

    # Create user for owner
    user_id = await upsert_user(email=workspace_owner_email)
    role = await ensure_workspace_member(workspace_id, user_id, role="owner")

    return (user_id, role)


async def get_workspace_by_api_key(api_key: str) -> Optional[tuple]:
    """
    Get workspace by API key with caching.
    Returns: (workspace_id, plan) or None if not found.
    """
    # Check cache first
    if api_key in _api_key_cache:
        workspace_id, plan, cached_at = _api_key_cache[api_key]
        if time.time() - cached_at < settings.api_key_cache_ttl:
            return (workspace_id, plan)
        else:
            del _api_key_cache[api_key]

    # Query database
    result = await execute_query(
        "SELECT id, plan FROM workspaces WHERE api_key = $1 AND active = true",
        api_key,
    )

    if not result:
        return None

    row = result[0]
    workspace_id = str(row["id"])
    plan = row["plan"]

    # Cache the result
    _api_key_cache[api_key] = (workspace_id, plan, time.time())

    return (workspace_id, plan)


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    Login with email+password or API key.
    Returns JWT token and workspace details.
    """
    if request.email and request.password:
        # Email + password login
        user_result = await execute_query(
            "SELECT id, email, password_hash FROM users WHERE email = $1",
            request.email,
        )
        if not user_result or not user_result[0]["password_hash"]:
            raise HTTPException(status_code=401, detail="Invalid email or password")

        user_row = user_result[0]
        if not bcrypt.verify(request.password, user_row["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        user_id = str(user_row["id"])

        # Update last_login
        await execute_insert(
            "UPDATE users SET last_login = $1 WHERE id = $2",
            datetime.utcnow(), user_id,
        )

        # Find user's workspace membership
        member_result = await execute_query(
            """
            SELECT wm.workspace_id, wm.role, w.id, w.name, w.owner_email, w.plan, w.api_key, w.created_at, w.active
            FROM workspace_members wm
            JOIN workspaces w ON w.id = wm.workspace_id
            WHERE wm.user_id = $1 AND wm.active = true AND w.active = true
            ORDER BY wm.joined_at ASC
            LIMIT 1
            """,
            user_id,
        )
        if not member_result:
            raise HTTPException(status_code=401, detail="No workspace found for this account")

        row = member_result[0]
        workspace_id = str(row["workspace_id"])
        role = row["role"]

    elif request.api_key:
        # API key login (legacy / CLI flow)
        result = await execute_query(
            "SELECT id, name, owner_email, plan, api_key, created_at, active FROM workspaces WHERE api_key = $1 AND active = true",
            request.api_key,
        )
        if not result:
            logger.warning("Failed login attempt with invalid API key")
            raise HTTPException(status_code=401, detail="Invalid API key")

        row = result[0]
        workspace_id = str(row["id"])

        # Auto-migrate workspace if needed
        user_id, role = await auto_migrate_user_for_workspace(workspace_id, row["owner_email"])

        if user_id is None:
            member_result = await execute_query(
                "SELECT user_id, role FROM workspace_members WHERE workspace_id = $1 AND active = true LIMIT 1",
                workspace_id,
            )
            if not member_result:
                raise HTTPException(status_code=500, detail="Failed to get user role")
            user_id = str(member_result[0]["user_id"])
            role = member_result[0]["role"]
    else:
        raise HTTPException(status_code=400, detail="Provide email+password or api_key")

    token = encode_jwt(workspace_id, user_id, role, row["plan"])

    workspace = WorkspaceResponse(
        id=workspace_id,
        name=row["name"],
        owner_email=row["owner_email"],
        plan=row["plan"],
        api_key=row["api_key"],
        created_at=row["created_at"],
        active=row["active"],
    )

    return LoginResponse(
        token=token,
        expires_in=settings.jwt_expiration_seconds,
        workspace=workspace,
    )


@router.post("/signup", response_model=SignupResponse)
async def signup(request: SignupRequest):
    """
    Create a new workspace and user with email+password.
    Returns JWT token so user is logged in immediately.
    """
    # Check if email already exists
    existing = await execute_query(
        "SELECT id FROM users WHERE email = $1", request.email,
    )
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists. Please sign in.")

    if len(request.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    workspace_id = str(uuid4())
    api_key = generate_api_key()

    try:
        # Create workspace
        await execute_insert(
            """
            INSERT INTO workspaces (id, name, owner_email, plan, api_key, created_at, active)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            workspace_id,
            request.workspace_name,
            request.email,
            "free",
            api_key,
            datetime.utcnow(),
            True,
        )

        # Create user with password and add to workspace
        user_id = await upsert_user(
            email=request.email,
            name=request.email.split("@")[0],
            password=request.password,
        )
        await ensure_workspace_member(workspace_id, user_id, role="owner")

        logger.info(f"New workspace created: {workspace_id} with user {user_id}")

        # Generate JWT so user is logged in immediately
        token = encode_jwt(workspace_id, user_id, "owner", "free")

        workspace = WorkspaceResponse(
            id=workspace_id,
            name=request.workspace_name,
            owner_email=request.email,
            plan="free",
            api_key=api_key,
            created_at=datetime.utcnow(),
            active=True,
        )

        return SignupResponse(
            api_key=api_key,
            workspace_id=workspace_id,
            token=token,
            expires_in=settings.jwt_expiration_seconds,
            workspace=workspace,
            message="Workspace created successfully.",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create workspace: {e}")
        raise HTTPException(status_code=500, detail="Failed to create workspace")


@router.get("/invite/{token}")
async def accept_invitation(token: str, redirect_to: Optional[str] = None, request: Request = None):
    """
    Accept invitation by token.
    If user is authenticated, accept immediately.
    If not authenticated, redirect to signup with invite token.
    """
    # Look up invitation
    result = await execute_query(
        "SELECT id, workspace_id, email, role, expires_at, accepted_at FROM invitations WHERE token = $1",
        token,
    )

    if not result:
        raise HTTPException(status_code=404, detail="Invitation not found")

    invitation = result[0]
    invitation_id = invitation["id"]
    workspace_id = str(invitation["workspace_id"])
    invited_email = invitation["email"]
    invited_role = invitation["role"]
    expires_at = invitation["expires_at"]
    accepted_at = invitation["accepted_at"]

    # Check if expired
    if expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="Invitation has expired")

    # Check if already accepted
    if accepted_at is not None:
        raise HTTPException(status_code=410, detail="Invitation has already been accepted")

    # Check if user is authenticated
    auth_header = request.headers.get("Authorization") if request else None
    if auth_header and auth_header.startswith("Bearer "):
        # User is authenticated, accept invitation
        token_str = auth_header[7:]
        payload = decode_jwt(token_str)

        if not payload:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        # Check if email matches
        user_result = await execute_query(
            "SELECT email FROM users WHERE id = $1",
            str(payload.user_id),
        )

        if not user_result:
            raise HTTPException(status_code=400, detail="User not found")

        user_email = user_result[0]["email"]

        if user_email != invited_email:
            raise HTTPException(
                status_code=409,
                detail=f"Invitation email ({invited_email}) does not match your account email ({user_email})",
            )

        # Accept invitation
        try:
            # Add user to workspace
            await ensure_workspace_member(workspace_id, str(payload.user_id), invited_role)

            # Mark invitation as accepted
            await execute_insert(
                """
                UPDATE invitations SET accepted_at = $1 WHERE id = $2
                """,
                datetime.utcnow(),
                str(invitation_id),
            )

            logger.info(
                f"Accepted invitation {invitation_id} for {invited_email} to workspace {workspace_id}"
            )

            # Log activity
            from .team_api import log_activity
            await log_activity(
                workspace_id,
                payload.user_id,
                "member_joined",
                {"email": invited_email, "role": invited_role},
            )

        except Exception as e:
            logger.error(f"Failed to accept invitation: {e}")
            raise HTTPException(status_code=500, detail="Failed to accept invitation")

        # Redirect to dashboard
        redirect_url = redirect_to or f"{settings.burnlens_frontend_url}/dashboard"
        return RedirectResponse(url=redirect_url, status_code=303)

    else:
        # User not authenticated, redirect to signup with invite token
        signup_url = f"{settings.burnlens_frontend_url}/signup?invite={token}"
        if redirect_to:
            signup_url += f"&redirect_to={redirect_to}"
        return RedirectResponse(url=signup_url, status_code=303)
