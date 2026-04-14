import logging
import secrets
import time
from uuid import uuid4
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from jose import JWTError, jwt

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


def encode_jwt(workspace_id: str, plan: str) -> str:
    """Encode JWT token."""
    now = int(time.time())
    exp = now + settings.jwt_expiration_seconds

    payload = TokenPayload(
        workspace_id=workspace_id,
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
    Login with API key.
    Returns JWT token and workspace details.
    """
    result = await execute_query(
        "SELECT id, name, owner_email, plan, api_key, created_at, active FROM workspaces WHERE api_key = $1 AND active = true",
        request.api_key,
    )

    if not result:
        logger.warning(f"Failed login attempt with invalid API key")
        raise HTTPException(status_code=401, detail="Invalid API key")

    row = result[0]
    workspace_id = str(row["id"])

    token = encode_jwt(workspace_id, row["plan"])

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
    Create a new workspace.
    Returns API key for use in future login and ingest calls.
    """
    workspace_id = str(uuid4())
    api_key = generate_api_key()

    try:
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

        logger.info(f"New workspace created: {workspace_id}")

        return SignupResponse(
            api_key=api_key,
            workspace_id=workspace_id,
            message="Workspace created successfully. Use the API key to login and start syncing data.",
        )
    except Exception as e:
        logger.error(f"Failed to create workspace: {e}")
        raise HTTPException(status_code=500, detail="Failed to create workspace")
