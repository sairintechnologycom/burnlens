import hashlib
import logging
import secrets
import time
import urllib.parse
from uuid import uuid4, UUID
from datetime import datetime, timedelta
from typing import Callable, Optional
from fastapi import APIRouter, HTTPException, Depends, Request, Response
from fastapi.responses import RedirectResponse
import bcrypt as _bcrypt
import jwt
from jwt.exceptions import InvalidTokenError

from .config import settings


# ---------------------------------------------------------------------------
# Session cookie (C-3) — browsers get the JWT as an HttpOnly cookie so XSS
# cannot exfiltrate it from `localStorage`. The `token` field in login/signup
# JSON responses is still populated so the CLI (which stores it in
# ~/.burnlens/config.yaml and sends `Authorization: Bearer ...`) keeps working.
# ---------------------------------------------------------------------------

SESSION_COOKIE_NAME = "burnlens_session"


def _session_cookie_domain() -> Optional[str]:
    """Return the cookie Domain for cross-subdomain sharing in production.

    In prod, `burnlens.app` (frontend) and `api.burnlens.app` (backend) must
    share the cookie, so Domain must be set to the eTLD+1 parent. In dev
    (`localhost:3000` → `localhost:8420`) browsers do not accept Domain=localhost,
    so we leave it unset and the cookie is scoped to the backend host only.
    """
    if settings.environment != "production":
        return None
    try:
        parsed = urllib.parse.urlsplit(settings.burnlens_frontend_url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if not host or host in ("localhost", "127.0.0.1"):
        return None
    # Derive eTLD+1 the conservative way: strip a leading `www.`. For
    # `burnlens.app` this yields `.burnlens.app` which matches
    # `api.burnlens.app` as well as the apex.
    if host.startswith("www."):
        host = host[4:]
    return f".{host}"


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.jwt_expiration_seconds,
        httponly=True,
        secure=(settings.environment == "production"),
        samesite="lax",
        domain=_session_cookie_domain(),
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        domain=_session_cookie_domain(),
        path="/",
    )


def _safe_redirect(target: Optional[str]) -> Optional[str]:
    """Return `target` only if it is a safe in-app redirect; else None.

    Prevents open-redirect pivots where an attacker crafts a link that accepts
    an invitation and then bounces the authenticated user to an attacker-
    controlled origin. Accepts only relative paths (starting with '/') that
    do NOT start with '//' (protocol-relative), or absolute URLs whose origin
    matches `settings.burnlens_frontend_url`.
    """
    if not target:
        return None
    target = target.strip()
    if not target:
        return None
    # Allow same-origin relative paths.
    if target.startswith("/") and not target.startswith("//"):
        return target
    # Allow absolute URLs only if host matches the configured frontend.
    try:
        parsed = urllib.parse.urlsplit(target)
    except ValueError:
        return None
    allowed = urllib.parse.urlsplit(settings.burnlens_frontend_url)
    if (
        parsed.scheme in ("http", "https")
        and parsed.scheme == allowed.scheme
        and parsed.netloc == allowed.netloc
    ):
        return target
    return None
from .database import execute_query, execute_insert


# ---------------------------------------------------------------------------
# Phase 2b: feature-flagged PII reads on workspaces. Same env var governs
# reads across auth.py and billing.py. Small helper is duplicated here
# rather than imported to avoid a burnlens_cloud.auth ↔ burnlens_cloud.billing
# import cycle.
# ---------------------------------------------------------------------------


def _ws_pii_value(row, _plaintext_col: str, encrypted_col: str):
    """Read a workspace PII field by decrypting the *_encrypted column.

    Phase 2c dropped the plaintext columns; the `_plaintext_col` arg is
    retained so call-sites across auth.py / billing.py stay uniform and
    easy to grep. Returns None when the encrypted column is NULL (e.g.
    a free-plan workspace with no paddle_*).
    """
    val = row[encrypted_col]
    if not val:
        return None
    from .pii_crypto import decrypt_pii
    return decrypt_pii(val)
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


def invalidate_api_key_cache(key_hash: str) -> None:
    """Evict a single api_key_cache entry by hash.

    Called by api_keys_api.revoke_api_key so that a revoked key stops
    authenticating immediately rather than remaining valid for up to
    api_key_cache_ttl seconds. Safe to call for a hash that is not in
    the cache (dict.pop with default).

    Note: this only invalidates the cache in the current process. In
    multi-worker deployments (Railway may spawn multiple Uvicorn
    workers), other workers still hold their own cache entries until
    TTL expiry. Keep api_key_cache_ttl short when revocation must
    propagate quickly across workers.
    """
    _api_key_cache.pop(key_hash, None)


def generate_api_key() -> str:
    """Generate a new API key with 'bl_live_' prefix."""
    return f"bl_live_{secrets.token_hex(16)}"


def hash_api_key(api_key: str) -> str:
    """Derive the lookup hash stored in the DB for an API key.

    SHA-256 of the plaintext key is adequate here because the key already
    carries ~128 bits of entropy from secrets.token_hex — we do not need a
    slow KDF (which exists to defeat dictionary attacks on low-entropy
    passwords). The purpose of hashing is defense-in-depth: a read-only DB
    breach reveals only hashes, not usable keys.
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def encode_jwt(workspace_id: str, user_id: str, role: str, plan: str, email_verified: bool = True) -> str:
    """Encode JWT token."""
    now = int(time.time())
    exp = now + settings.jwt_expiration_seconds

    payload = TokenPayload(
        workspace_id=workspace_id,
        user_id=user_id,
        role=role,
        plan=plan,
        email_verified=email_verified,
        iat=now,
        exp=exp,
    )

    return jwt.encode(
        payload.model_dump(mode="json"),
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
    except InvalidTokenError:
        return None


async def verify_token(request: Request) -> TokenPayload:
    """Extract and verify JWT.

    Accepts two transports so browser and CLI clients share one pipeline:
      1. `burnlens_session` HttpOnly cookie (browser — C-3).
      2. `Authorization: Bearer <jwt>` header (CLI / API clients).
    The cookie is checked first; the header is the fallback.
    """
    token: Optional[str] = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

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


# ---------------------------------------------------------------------------
# Plan-entitlement middleware (Phase 9 D-17 / GATE-05)
# ---------------------------------------------------------------------------
# `require_feature(name)` is a FastAPI dependency factory that raises 402 when
# the caller's workspace plan does not include the named gated feature. The
# lookup goes through `resolve_limits` so `plan_limits.gated_features` is the
# single source of truth (Phase 6 D-08) — adding a new gated feature in a
# future phase is a seed change, not a code change.
#
# Security notes (threat_model T-09-12): the gate decision is based on the
# server-side `resolve_limits(token.workspace_id)` lookup, NOT on the
# `token.plan` claim inside the JWT. A stale or forged `token.plan` cannot
# grant access; `token.plan` only appears in the 402 body as display copy.

# Deterministic price order for "cheapest plan with this feature" lookups.
# Alphabetic sort would put "cloud" before "free" which is wrong — this tuple
# is authoritative. Enterprise is intentionally absent until it has a fixed
# public price.
_PLAN_PRICE_ORDER = ("free", "cloud", "teams")


async def _lowest_plan_with_feature(name: str) -> Optional[str]:
    """Return the cheapest plan whose `gated_features[name]` is true, or None.

    Reads `plan_limits.gated_features` directly — this is a per-call lookup,
    not per-workspace, so it does not go through `resolve_limits`. Callers:
    the 402 body builder in `require_feature` and (future) team_api seat-limit
    / api-key-limit handlers that want to suggest an upgrade target.
    """
    rows = await execute_query(
        "SELECT plan, gated_features FROM plan_limits WHERE (gated_features->>$1)::boolean = true",
        name,
    )
    if not rows:
        return None
    plans_with_feature = {row["plan"] for row in rows}
    for candidate in _PLAN_PRICE_ORDER:
        if candidate in plans_with_feature:
            return candidate
    return None


def require_feature(name: str) -> Callable:
    """FastAPI dependency factory: 402 if caller's plan does not include `name`.

    Usage:
      `@router.get("/customers", dependencies=[Depends(require_feature("customers_view"))])`
      or `async def handler(token: TokenPayload = Depends(require_feature("teams_view")))`.

    Per D-17, the 402 body is:
      {error: "feature_not_in_plan", required_feature, current_plan, required_plan, upgrade_url}

    `required_plan` is the cheapest plan whose `gated_features` has the flag
    true; None if no plan covers the feature. The upgrade_url points at the
    Phase 8 billing card anchor (`/settings#billing`), not the pre-Phase-8
    `/upgrade` URL.
    """
    # Lazy import to avoid any future auth <-> plans import cycle. `plans.py`
    # currently does not import from auth, but keeping this lazy is cheap
    # insurance for downstream refactors.
    from .plans import resolve_limits

    async def checker(token: TokenPayload = Depends(verify_token)) -> TokenPayload:
        limits = await resolve_limits(token.workspace_id)
        features = limits.gated_features if limits is not None else {}
        if not features.get(name, False):
            required = await _lowest_plan_with_feature(name)
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "feature_not_in_plan",
                    "required_feature": name,
                    "current_plan": token.plan,
                    "required_plan": required,
                    "upgrade_url": f"{settings.burnlens_frontend_url}/settings#billing",
                },
            )
        return token

    return checker


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

    Phase 1c: PII columns are encrypted-only. The plaintext email /
    google_id / github_id columns have been dropped. PII_MASTER_KEY
    MUST be present or every call raises PIICryptoError.
    """
    from .pii_crypto import encrypt_pii, lookup_hash

    password_hash = (
        _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")
        if password
        else None
    )

    email_enc = encrypt_pii(email) if email else None
    email_h = lookup_hash(email) if email else None
    google_enc = encrypt_pii(google_id) if google_id else None
    google_h = lookup_hash(google_id) if google_id else None
    github_enc = encrypt_pii(github_id) if github_id else None
    github_h = lookup_hash(github_id) if github_id else None

    # Find existing user by hash columns.
    if google_id:
        result = await execute_query(
            "SELECT id FROM users WHERE google_id_hash = $1", google_h,
        )
        if result:
            return str(result[0]["id"])

    if github_id:
        result = await execute_query(
            "SELECT id FROM users WHERE github_id_hash = $1", github_h,
        )
        if result:
            return str(result[0]["id"])

    result = await execute_query(
        "SELECT id FROM users WHERE email_hash = $1", email_h,
    )
    if result:
        user_id = str(result[0]["id"])
        # Update OAuth IDs if provided.
        # SECURITY: `update_fields` elements MUST remain hardcoded literal strings.
        # Never build them from user input or dynamic column names — that would
        # turn the f-string below into a SQL injection.
        update_fields = []
        update_params = []
        param_idx = 1

        if google_id:
            update_fields.append(f"google_id_encrypted = ${param_idx}")
            update_params.append(google_enc)
            param_idx += 1
            update_fields.append(f"google_id_hash = ${param_idx}")
            update_params.append(google_h)
            param_idx += 1

        if github_id:
            update_fields.append(f"github_id_encrypted = ${param_idx}")
            update_params.append(github_enc)
            param_idx += 1
            update_fields.append(f"github_id_hash = ${param_idx}")
            update_params.append(github_h)
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

    # Create new user. Only encrypted + hash columns are written.
    user_id = str(uuid4())
    try:
        await execute_insert(
            """
            INSERT INTO users (
                id, name, password_hash, created_at,
                email_encrypted, email_hash,
                google_id_encrypted, google_id_hash,
                github_id_encrypted, github_id_hash
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            user_id,
            name,
            password_hash,
            datetime.utcnow(),
            email_enc,
            email_h,
            google_enc,
            google_h,
            github_enc,
            github_h,
        )
        logger.info("Created new user: %s", user_id)
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

    Lookup is performed against the stored `api_key_hash` column so the
    plaintext never appears in any query log. The in-memory cache is also
    keyed on the hash to avoid leaking plaintext through a process dump.
    """
    key_hash = hash_api_key(api_key)

    # Check cache first (keyed on hash)
    if key_hash in _api_key_cache:
        workspace_id, plan, cached_at = _api_key_cache[key_hash]
        if time.time() - cached_at < settings.api_key_cache_ttl:
            return (workspace_id, plan)
        else:
            del _api_key_cache[key_hash]

    # Query database by hash — dual-read transition (Phase 9 D-12):
    # prefer the new `api_keys` table so keys created via Plan 04's POST
    # /api-keys endpoint authenticate immediately, and fall back to the
    # legacy `workspaces.api_key_hash` column for pre-migration keys.
    # The fallback is scheduled for removal in a follow-up release
    # (v1.1.1+) once every live key has been migrated.
    result = await execute_query(
        """
        SELECT w.id AS id, w.plan AS plan
        FROM api_keys ak
        JOIN workspaces w ON w.id = ak.workspace_id
        WHERE ak.key_hash = $1 AND ak.revoked_at IS NULL AND w.active = true
        LIMIT 1
        """,
        key_hash,
    )
    if not result:
        # Legacy fallback for keys created before the api_keys table landed.
        result = await execute_query(
            "SELECT id, plan FROM workspaces WHERE api_key_hash = $1 AND active = true",
            key_hash,
        )

    if not result:
        return None

    row = result[0]
    workspace_id = str(row["id"])
    plan = row["plan"]

    _api_key_cache[key_hash] = (workspace_id, plan, time.time())

    return (workspace_id, plan)


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, response: Response):
    """
    Login with email+password or API key.
    Returns JWT token and workspace details.
    """
    if request.email and request.password:
        # Email + password login — normalize email to lowercase so mixed-case
        # typing (e.g. iPhone auto-capitalize) matches the stored row.
        if len(request.password) > 128:
            raise HTTPException(status_code=400, detail="Password too long")
        email_norm = request.email.strip().lower()
        from .pii_crypto import lookup_hash as _lh
        user_result = await execute_query(
            "SELECT id, password_hash FROM users WHERE email_hash = $1",
            _lh(email_norm),
        )
        if not user_result or not user_result[0]["password_hash"]:
            raise HTTPException(status_code=401, detail="Invalid email or password")

        user_row = user_result[0]
        if not _bcrypt.checkpw(
            request.password.encode("utf-8"),
            user_row["password_hash"].encode("utf-8"),
        ):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        user_id = str(user_row["id"])

        # Update last_login
        await execute_insert(
            "UPDATE users SET last_login = $1 WHERE id = $2",
            datetime.utcnow(), user_id,
        )

        # Find user's workspace membership. Phase 2c: plaintext owner_email
        # and plaintext api_key columns were dropped; read the encrypted
        # owner_email + the api_key_last4 column needed for masked display.
        member_result = await execute_query(
            """
            SELECT wm.workspace_id, wm.role, w.id, w.name,
                   w.owner_email_encrypted,
                   w.plan, w.api_key_last4, w.created_at, w.active
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
        # API key login (legacy / CLI flow) — look up by hash. Phase 2c:
        # plaintext api_key and owner_email columns are gone; read
        # api_key_last4 for the masked display and decrypt owner_email
        # for the auto-migration seed.
        result = await execute_query(
            """
            SELECT id, name, owner_email_encrypted,
                   plan, api_key_last4, created_at, active
            FROM workspaces WHERE api_key_hash = $1 AND active = true
            """,
            hash_api_key(request.api_key),
        )
        if not result:
            logger.warning("Failed login attempt with invalid API key")
            raise HTTPException(status_code=401, detail="Invalid API key")

        row = result[0]
        workspace_id = str(row["id"])

        owner_email_resolved = _ws_pii_value(
            row, "owner_email", "owner_email_encrypted"
        )
        user_id, role = await auto_migrate_user_for_workspace(
            workspace_id, owner_email_resolved
        )

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

    # Determine email_verified: True if email_verified_at is set, or if user has
    # no pending verification token (pre-v1.2 grandfathered users have no token).
    has_pending_token = await execute_query(
        "SELECT 1 FROM auth_tokens WHERE user_id=$1 AND type='email_verification' AND used_at IS NULL AND expires_at > now()",
        user_id,
    )
    email_verified = bool(row.get("email_verified_at")) or not bool(has_pending_token)

    token = encode_jwt(workspace_id, user_id, role, row["plan"], email_verified=email_verified)
    _set_session_cookie(response, token)

    # Never echo the full plaintext API key on login — the user received it
    # once at signup. Return a masked form built from the persisted last4.
    # Phase 2c: owner_email decrypted from owner_email_encrypted; api_key
    # masked form built from api_key_last4 (plaintext column dropped).
    _last4 = row["api_key_last4"] or ""
    workspace = WorkspaceResponse(
        id=workspace_id,
        name=row["name"],
        owner_email=_ws_pii_value(row, "owner_email", "owner_email_encrypted"),
        plan=row["plan"],
        api_key=f"bl_live_****{_last4}" if _last4 else "****",
        created_at=row["created_at"],
        active=row["active"],
    )

    return LoginResponse(
        token=token,
        expires_in=settings.jwt_expiration_seconds,
        workspace=workspace,
        email_verified=email_verified,
    )


@router.post("/signup", response_model=SignupResponse)
async def signup(request: SignupRequest, response: Response):
    """
    Create a new workspace and user with email+password.
    Returns JWT token so user is logged in immediately.
    """
    # Normalize email so case differences don't create duplicate/unreachable accounts.
    email_norm = request.email.strip().lower()
    if len(request.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if len(request.password) > 128:
        raise HTTPException(status_code=400, detail="Password too long (max 128 chars)")

    # Check if email already exists (hash-based equality — emails are no
    # longer stored as plaintext post-Phase-1c).
    from .pii_crypto import lookup_hash as _lh
    existing = await execute_query(
        "SELECT id FROM users WHERE email_hash = $1", _lh(email_norm),
    )
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists. Please sign in.")

    workspace_id = str(uuid4())
    api_key = generate_api_key()
    api_key_hash_value = hash_api_key(api_key)

    # Phase 2c: plaintext owner_email + api_key columns are gone. Require
    # encrypt+hash to succeed — a PIICryptoError here means PII_MASTER_KEY
    # is misconfigured and we cannot create accounts at all, which is the
    # correct fail-closed behavior.
    from .pii_crypto import encrypt_pii as _pii_enc, lookup_hash as _pii_hash
    owner_email_encrypted = _pii_enc(email_norm)
    owner_email_hash = _pii_hash(email_norm)

    try:
        # Create workspace. api_key plaintext is returned in the signup
        # response once and discarded; only api_key_hash (for lookups) and
        # api_key_last4 (for masked display on later logins) are persisted.
        await execute_insert(
            """
            INSERT INTO workspaces (
                id, name, owner_email_encrypted, owner_email_hash,
                plan, api_key_hash, api_key_last4, created_at, active
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            workspace_id,
            request.workspace_name,
            owner_email_encrypted,
            owner_email_hash,
            "free",
            api_key_hash_value,
            api_key[-4:],
            datetime.utcnow(),
            True,
        )

        # Create user with password and add to workspace
        user_id = await upsert_user(
            email=email_norm,
            name=email_norm.split("@")[0],
            password=request.password,
        )
        await ensure_workspace_member(workspace_id, user_id, role="owner")

        logger.info(f"New workspace created: {workspace_id} with user {user_id}")

        # Generate JWT so user is logged in immediately
        token = encode_jwt(workspace_id, user_id, "owner", "free", email_verified=False)
        _set_session_cookie(response, token)

        workspace = WorkspaceResponse(
            id=workspace_id,
            name=request.workspace_name,
            owner_email=email_norm,
            plan="free",
            api_key=api_key,
            created_at=datetime.utcnow(),
            active=True,
        )

        return SignupResponse(
            api_key=api_key,
            workspace_id=UUID(workspace_id),
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
    # Phase 4: invitations store sha256(token), not the plaintext, so a DB
    # leak does not yield usable invite credentials. The token from the URL
    # must be hashed here before the lookup.
    token_hash_value = hashlib.sha256(token.encode("utf-8")).hexdigest()
    result = await execute_query(
        "SELECT id, workspace_id, email, role, expires_at, accepted_at FROM invitations WHERE token_hash = $1",
        token_hash_value,
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

        # Check if email matches. Compare keyed hashes (no plaintext email
        # in SQL logs) and decrypt the stored value only for the 409 body.
        from .pii_crypto import lookup_hash as _lh, decrypt_pii as _dec
        user_result = await execute_query(
            "SELECT email_hash, email_encrypted FROM users WHERE id = $1",
            str(payload.user_id),
        )
        if not user_result:
            raise HTTPException(status_code=400, detail="User not found")
        stored_hash = user_result[0]["email_hash"]
        if stored_hash != _lh(invited_email):
            # Decrypt solely to echo the user's own email back in the
            # 409 body — the user already knows it; nothing is leaked.
            enc = user_result[0].get("email_encrypted")
            shown = _dec(enc) if enc else "(unknown)"
            raise HTTPException(
                status_code=409,
                detail=f"Invitation email ({invited_email}) does not match your account email ({shown})",
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

        # Redirect to dashboard — validate redirect_to against allowlist to prevent
        # open-redirect phishing pivots.
        redirect_url = _safe_redirect(redirect_to) or f"{settings.burnlens_frontend_url}/dashboard"
        return RedirectResponse(url=redirect_url, status_code=303)

    else:
        # User not authenticated, redirect to signup with invite token
        signup_url = f"{settings.burnlens_frontend_url}/signup?invite={token}"
        safe_redirect = _safe_redirect(redirect_to)
        if safe_redirect:
            signup_url += f"&redirect_to={urllib.parse.quote(safe_redirect, safe='')}"
        return RedirectResponse(url=signup_url, status_code=303)


@router.post("/logout")
async def logout(response: Response):
    """Clear the session cookie. Idempotent; no auth required."""
    _clear_session_cookie(response)
    return {"ok": True}
