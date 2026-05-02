---
phase: 11-auth-essentials
plan: 03b
type: execute
wave: 2
depends_on: ["03a"]
files_modified:
  - burnlens_cloud/auth.py
autonomous: true
requirements: [AUTH-01, AUTH-02, AUTH-03, AUTH-04]
must_haves:
  truths:
    - "POST /auth/reset-password always returns HTTP 200 regardless of whether the email exists (no user enumeration)"
    - "POST /auth/reset-password/confirm validates token via atomic UPDATE rowcount (0 = already used or expired, 1 = claimed)"
    - "GET /auth/verify-email?token=xxx claims token atomically and sets users.email_verified_at = now()"
    - "POST /auth/resend-verification always returns HTTP 200; only sends if user exists and has unclaimed token"
    - "signup() fires send_welcome_email + send_verify_email after user creation; creates email_verification auth_token"
    - "signup() returns SignupResponse with email_verified=False"
  artifacts:
    - path: "burnlens_cloud/auth.py"
      provides: "4 new auth endpoints + signup email wiring"
      exports: ["POST /auth/reset-password", "POST /auth/reset-password/confirm", "POST /auth/resend-verification", "GET /auth/verify-email"]
  key_links:
    - from: "burnlens_cloud/auth.py::POST /auth/reset-password/confirm"
      to: "Plan 05b /reset-password frontend page"
      via: "POST with new_password + token"
      pattern: "reset-password/confirm"
    - from: "burnlens_cloud/auth.py::GET /auth/verify-email"
      to: "Plan 05b /verify-email frontend page"
      via: "GET with ?token= on page load"
      pattern: "verify-email"
---

<objective>
Add four new auth route handlers to `burnlens_cloud/auth.py` and wire transactional emails into the existing `signup()` function. Depends on Plan 03a for `encode_jwt` and model changes, and Plans 01/02 for DB schema and email send functions.

This is Part B of the split from original Plan 03.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/11-auth-essentials/11-CONTEXT.md
@burnlens_cloud/auth.py

<interfaces>
<!-- Token generation pattern (from api_keys_api.py):
import secrets, hashlib
raw_token = secrets.token_urlsafe(32)
token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
-->

<!-- signup() location (auth.py ~line 702):
After: logger.info(f"New workspace created: {workspace_id} with user {user_id}")
Before: token = encode_jwt(workspace_id, user_id, "owner", "free", email_verified=False)  [updated by Plan 03a]
-->

<!-- execute_insert returns asyncpg status string, e.g. "UPDATE 1", "UPDATE 0", "INSERT 0 1" -->
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add 4 new auth route handlers to auth.py</name>
  <files>burnlens_cloud/auth.py</files>
  <read_first>
    - burnlens_cloud/auth.py lines 700-800 (signup function — understand imports, error patterns, pii_crypto usage)
    - burnlens_cloud/auth.py lines 1-20 (imports — confirm hashlib, secrets, datetime already imported)
    - .planning/phases/11-auth-essentials/11-CONTEXT.md §D-01 (token table schema) §D-02 (expiry values)
  </read_first>
  <action>
Append the following 4 route handlers at the END of auth.py (after all existing routes). Ensure `import hashlib`, `import secrets` are already present (used in existing api_key generation); add to imports if missing.

**Route 1: POST /auth/reset-password** (always 200, no enumeration):
```python
class ResetPasswordRequest(BaseModel):
    email: str


@router.post("/reset-password", status_code=200)
async def request_password_reset(request: ResetPasswordRequest):
    """Request a password reset email. Always returns 200 to prevent user enumeration."""
    from .pii_crypto import lookup_hash as _lh
    email_norm = request.email.strip().lower()
    email_h = _lh(email_norm)

    rows = await execute_query(
        "SELECT id, email_encrypted FROM users WHERE email_hash = $1", email_h
    )
    if not rows:
        return {"message": "If an account with that email exists, a reset link has been sent."}

    user_id = str(rows[0]["id"])
    from .pii_crypto import decrypt_pii as _dec
    recipient_email = _dec(rows[0]["email_encrypted"])

    # Invalidate any existing unused password_reset tokens for this user.
    await execute_insert(
        "UPDATE auth_tokens SET used_at = now() WHERE user_id = $1 AND type = 'password_reset' AND used_at IS NULL",
        user_id,
    )

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    from datetime import timezone
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    await execute_insert(
        """
        INSERT INTO auth_tokens (user_id, type, token_hash, expires_at)
        VALUES ($1, 'password_reset', $2, $3)
        """,
        user_id, token_hash, expires_at,
    )

    reset_url = f"{settings.burnlens_frontend_url}/reset-password?token={raw_token}"
    from .email import send_reset_password_email
    await send_reset_password_email(recipient_email, reset_url)
    return {"message": "If an account with that email exists, a reset link has been sent."}
```

**Route 2: POST /auth/reset-password/confirm**:
```python
class ResetPasswordConfirmRequest(BaseModel):
    token: str
    new_password: str


@router.post("/reset-password/confirm", status_code=200)
async def confirm_password_reset(request: ResetPasswordConfirmRequest):
    """Validate reset token and set new password. Token is single-use."""
    if len(request.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if len(request.new_password) > 128:
        raise HTTPException(status_code=400, detail="Password too long (max 128 chars)")

    token_hash = hashlib.sha256(request.token.encode()).hexdigest()

    # Atomic single-use claim: rowcount 1 = claimed, 0 = already used or expired.
    result = await execute_insert(
        """
        UPDATE auth_tokens SET used_at = now()
        WHERE token_hash = $1
          AND type = 'password_reset'
          AND used_at IS NULL
          AND expires_at > now()
        """,
        token_hash,
    )
    if not result or result == "UPDATE 0":
        raise HTTPException(status_code=400, detail="Reset link is invalid or has expired.")

    row = await execute_query(
        "SELECT user_id FROM auth_tokens WHERE token_hash = $1", token_hash
    )
    if not row:
        raise HTTPException(status_code=400, detail="Reset link is invalid or has expired.")

    user_id = str(row[0]["user_id"])
    import bcrypt
    hashed = bcrypt.hashpw(request.new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    await execute_insert(
        "UPDATE users SET password_hash = $1 WHERE id = $2", hashed, user_id
    )

    # Send password-changed confirmation email (fail-open).
    user_email_row = await execute_query(
        "SELECT email_encrypted FROM users WHERE id = $1", user_id
    )
    if user_email_row and user_email_row[0].get("email_encrypted"):
        from .pii_crypto import decrypt_pii as _dec
        from .email import send_password_changed_email
        recipient = _dec(user_email_row[0]["email_encrypted"])
        await send_password_changed_email(recipient)

    return {"message": "Password updated successfully."}
```

**Route 3: GET /auth/verify-email** (claim token, set email_verified_at):
```python
@router.get("/verify-email", status_code=200)
async def verify_email(token: str):
    """Claim email verification token and mark email as verified."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    result = await execute_insert(
        """
        UPDATE auth_tokens SET used_at = now()
        WHERE token_hash = $1
          AND type = 'email_verification'
          AND used_at IS NULL
          AND expires_at > now()
        """,
        token_hash,
    )
    if not result or result == "UPDATE 0":
        raise HTTPException(status_code=400, detail="Verification link is invalid or has expired.")

    row = await execute_query(
        "SELECT user_id FROM auth_tokens WHERE token_hash = $1", token_hash
    )
    if not row:
        raise HTTPException(status_code=400, detail="Verification link is invalid or has expired.")

    user_id = str(row[0]["user_id"])
    await execute_insert(
        "UPDATE users SET email_verified_at = now() WHERE id = $1", user_id
    )
    return {"message": "Email verified successfully."}
```

**Route 4: POST /auth/resend-verification** (always 200):
```python
class ResendVerificationRequest(BaseModel):
    email: str


@router.post("/resend-verification", status_code=200)
async def resend_verification(request: ResendVerificationRequest):
    """Resend email verification link. Always returns 200."""
    from .pii_crypto import lookup_hash as _lh, decrypt_pii as _dec
    email_norm = request.email.strip().lower()
    rows = await execute_query(
        "SELECT id, email_encrypted, email_verified_at FROM users WHERE email_hash = $1",
        _lh(email_norm),
    )
    if not rows or rows[0].get("email_verified_at") is not None:
        return {"message": "If applicable, a verification email has been sent."}

    user_id = str(rows[0]["id"])
    recipient_email = _dec(rows[0]["email_encrypted"])

    # Invalidate existing unused tokens.
    await execute_insert(
        "UPDATE auth_tokens SET used_at = now() WHERE user_id = $1 AND type = 'email_verification' AND used_at IS NULL",
        user_id,
    )

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    from datetime import timezone
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    await execute_insert(
        "INSERT INTO auth_tokens (user_id, type, token_hash, expires_at) VALUES ($1, 'email_verification', $2, $3)",
        user_id, token_hash, expires_at,
    )

    verify_url = f"{settings.burnlens_frontend_url}/verify-email?token={raw_token}"
    from .email import send_verify_email
    await send_verify_email(recipient_email, verify_url)
    return {"message": "If applicable, a verification email has been sent."}
```
  </action>
  <acceptance_criteria>
    - burnlens_cloud/auth.py contains `@router.post("/reset-password", status_code=200)`
    - burnlens_cloud/auth.py contains `@router.post("/reset-password/confirm", status_code=200)`
    - burnlens_cloud/auth.py contains `@router.get("/verify-email", status_code=200)`
    - burnlens_cloud/auth.py contains `@router.post("/resend-verification", status_code=200)`
    - burnlens_cloud/auth.py contains `UPDATE auth_tokens SET used_at = now()` (atomic claim pattern)
    - burnlens_cloud/auth.py contains `result == "UPDATE 0"` (rowcount check for invalid/expired token)
    - burnlens_cloud/auth.py contains `send_password_changed_email` call in confirm handler
    - `python -c "import ast; ast.parse(open('burnlens_cloud/auth.py').read()); print('OK')"` → `OK`
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 2: Wire welcome + verify emails into signup() in auth.py</name>
  <files>burnlens_cloud/auth.py</files>
  <read_first>
    - burnlens_cloud/auth.py lines 760-790 (signup function after user creation — exact location of logger.info("New workspace created"))
  </read_first>
  <action>
In the `signup()` function, after the `logger.info(f"New workspace created: {workspace_id} with user {user_id}")` line and BEFORE the `token = encode_jwt(...)` line, insert:

```python
        # Phase 11: send welcome + verification emails (fail-open via background tasks).
        raw_verify_token = secrets.token_urlsafe(32)
        verify_token_hash = hashlib.sha256(raw_verify_token.encode()).hexdigest()
        from datetime import timezone as _tz
        verify_expires = datetime.now(_tz.utc) + timedelta(hours=24)
        try:
            await execute_insert(
                "INSERT INTO auth_tokens (user_id, type, token_hash, expires_at) VALUES ($1, 'email_verification', $2, $3)",
                user_id, verify_token_hash, verify_expires,
            )
        except Exception:
            logger.exception("signup: failed to create email verification token for user %s", user_id)

        from .email import send_welcome_email, send_verify_email as _send_verify
        verify_url = f"{settings.burnlens_frontend_url}/verify-email?token={raw_verify_token}"
        await send_welcome_email(email_norm, request.workspace_name)
        await _send_verify(email_norm, verify_url)
```

Also update the `SignupResponse(...)` return statement to include `email_verified=False`.
  </action>
  <acceptance_criteria>
    - burnlens_cloud/auth.py contains `send_welcome_email(email_norm, request.workspace_name)` inside signup function
    - burnlens_cloud/auth.py contains `send_verify_email` call (or `_send_verify`) inside signup function
    - burnlens_cloud/auth.py contains `INSERT INTO auth_tokens` inside signup function (creating verify token)
    - burnlens_cloud/auth.py signup returns `SignupResponse` with `email_verified=False`
    - `python -c "import ast; ast.parse(open('burnlens_cloud/auth.py').read()); print('OK')"` → `OK`
  </acceptance_criteria>
</task>

</tasks>

<verification>
1. `grep -n "reset-password\|verify-email\|resend-verification" burnlens_cloud/auth.py` → shows all 4 new routes
2. `grep -c "UPDATE 0" burnlens_cloud/auth.py` → at least `2` (reset confirm + verify email)
3. `grep -n "send_welcome_email\|send_verify_email\|_send_verify" burnlens_cloud/auth.py` → shows signup wiring
4. `python -c "import ast; ast.parse(open('burnlens_cloud/auth.py').read()); print('OK')"` → `OK`
</verification>

<threat_model>
## Security Threat Model (ASVS L1)

| Threat | Severity | Mitigation |
|--------|----------|-----------|
| User enumeration via reset endpoint response | HIGH | POST /auth/reset-password always returns HTTP 200 with identical body regardless of email existence |
| Token replay after use | HIGH | Atomic UPDATE rowcount check (`result == "UPDATE 0"` → reject); `used_at` set in same UPDATE that validates |
| Expired token accepted | HIGH | `expires_at > now()` included in the UPDATE WHERE clause — enforced at DB level |
| Token brute force | HIGH | 256-bit entropy (`secrets.token_urlsafe(32)`); rate limit from Plan 03a; 1h/24h expiry |
| Password hash exposure in logs | HIGH | bcrypt hash never logged; user_id logged (not email) |
| Weak new password accepted | MEDIUM | 8–128 character check; bcrypt with gensalt() |
| CSRF on state-changing POST endpoints | LOW | API-only; no browser form POST from external origin; rate limiting reduces attack surface |

All HIGH threats mitigated.
</threat_model>

<must_haves>
- POST /auth/reset-password always returns 200 (no enumeration)
- Token claim is atomic: single UPDATE with rowcount check for both reset and verify
- signup() creates email_verification auth_token and fires send_welcome_email + send_verify_email
- signup() returns SignupResponse with email_verified=False
- All handlers fail-open: exceptions from email sends must not propagate HTTP 500
</must_haves>
