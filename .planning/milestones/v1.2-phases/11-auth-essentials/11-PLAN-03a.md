---
phase: 11-auth-essentials
plan: 03a
type: execute
wave: 2
depends_on: ["01", "02"]
files_modified:
  - burnlens_cloud/models.py
  - burnlens_cloud/rate_limit.py
  - burnlens_cloud/auth.py
autonomous: true
requirements: [AUTH-05, AUTH-07]
must_haves:
  truths:
    - "TokenPayload gains email_verified: bool = True field"
    - "LoginResponse gains email_verified: bool = True field"
    - "SignupResponse gains email_verified: bool = False field"
    - "encode_jwt signature extended to accept email_verified: bool = True"
    - "encode_jwt passes email_verified into TokenPayload"
    - "login call site derives email_verified via grandfathering logic (has_pending_token query)"
    - "signup call site passes email_verified=False to encode_jwt"
    - "DEFAULT_RULES in rate_limit.py includes ('/auth/reset-password', 3, 900)"
  artifacts:
    - path: "burnlens_cloud/models.py"
      provides: "TokenPayload.email_verified field; LoginResponse/SignupResponse email_verified field"
      exports: ["TokenPayload", "LoginResponse", "SignupResponse"]
    - path: "burnlens_cloud/auth.py"
      provides: "encode_jwt updated signature + both call sites updated"
      exports: ["encode_jwt"]
    - path: "burnlens_cloud/rate_limit.py"
      provides: "Rate limit rule for /auth/reset-password (3 req/900s)"
      exports: ["DEFAULT_RULES"]
  key_links:
    - from: "burnlens_cloud/models.py::TokenPayload.email_verified"
      to: "Plan 03b auth routes + Plan 05a useAuth"
      via: "JWT payload → login/signup response → localStorage burnlens_email_verified"
      pattern: "email_verified"
---

<objective>
Add `email_verified: bool` to `TokenPayload`, `LoginResponse`, and `SignupResponse` in `models.py`. Update `encode_jwt` to accept and propagate the field. Update both call sites in `auth.py` (login uses grandfathering logic; signup passes `False`). Add the password-reset rate-limit rule to `rate_limit.py`.

This is Part A of the split from original Plan 03. Part B (`11-PLAN-03b.md`) adds the 4 route handlers and signup email wiring.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/11-auth-essentials/11-CONTEXT.md
@burnlens_cloud/auth.py
@burnlens_cloud/models.py
@burnlens_cloud/rate_limit.py

<interfaces>
<!-- TokenPayload (models.py lines 101-108):
class TokenPayload(BaseModel):
    workspace_id: UUID
    user_id: UUID
    role: str
    plan: str
    iat: int
    exp: int
-->

<!-- encode_jwt (auth.py line 179):
def encode_jwt(workspace_id: str, user_id: str, role: str, plan: str) -> str:
    payload = TokenPayload(...)
    return jwt.encode(payload.model_dump(), settings.jwt_secret, algorithm="HS256")
-->

<!-- DEFAULT_RULES (rate_limit.py lines 86-91):
DEFAULT_RULES: tuple[tuple[str, int, int], ...] = (
    ("/auth/login", 10, 60),
    ("/auth/signup", 5, 60),
    ("/auth/invite", 20, 60),
    ("/v1/ingest", 600, 60),
)
-->

<!-- signup() call site (auth.py line 770):
token = encode_jwt(workspace_id, user_id, "owner", "free")
-->

<!-- login() call site (auth.py line 677):
token = encode_jwt(workspace_id, user_id, role, row["plan"])
-->
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add email_verified to TokenPayload, LoginResponse, SignupResponse in models.py</name>
  <files>burnlens_cloud/models.py</files>
  <read_first>
    - burnlens_cloud/models.py lines 77-110 (LoginResponse, SignupResponse, TokenPayload — exact field list)
  </read_first>
  <action>
Three changes to models.py:

1. **TokenPayload** — add `email_verified: bool = True` as the last field (after `exp: int`):
```python
class TokenPayload(BaseModel):
    workspace_id: UUID
    user_id: UUID
    role: str
    plan: str
    iat: int
    exp: int
    email_verified: bool = True
```

2. **LoginResponse** — add `email_verified: bool = True` field:
```python
class LoginResponse(BaseModel):
    token: str
    expires_in: int
    workspace: WorkspaceResponse
    email_verified: bool = True
```

3. **SignupResponse** — add `email_verified: bool = False` field (new signups are unverified):
```python
class SignupResponse(BaseModel):
    api_key: str
    workspace_id: UUID
    token: str
    expires_in: int
    workspace: WorkspaceResponse
    message: str = "Workspace created successfully."
    email_verified: bool = False
```
  </action>
  <acceptance_criteria>
    - burnlens_cloud/models.py contains `email_verified: bool = True` inside TokenPayload class
    - burnlens_cloud/models.py contains `email_verified: bool = True` inside LoginResponse class
    - burnlens_cloud/models.py contains `email_verified: bool = False` inside SignupResponse class
    - `python -c "import ast; ast.parse(open('burnlens_cloud/models.py').read()); print('OK')"` → `OK`
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 2: Update encode_jwt signature and both call sites in auth.py</name>
  <files>burnlens_cloud/auth.py</files>
  <read_first>
    - burnlens_cloud/auth.py lines 179-198 (encode_jwt function — full body)
    - burnlens_cloud/auth.py lines 670-680 (login call site: encode_jwt(workspace_id, user_id, role, row["plan"]))
    - burnlens_cloud/auth.py lines 765-775 (signup call site: encode_jwt(workspace_id, user_id, "owner", "free"))
  </read_first>
  <action>
Three changes to auth.py:

1. **encode_jwt signature** — add `email_verified: bool = True` parameter and include in TokenPayload:
```python
def encode_jwt(workspace_id: str, user_id: str, role: str, plan: str, email_verified: bool = True) -> str:
    payload = TokenPayload(
        workspace_id=workspace_id,
        user_id=user_id,
        role=role,
        plan=plan,
        email_verified=email_verified,
        iat=int(datetime.utcnow().timestamp()),
        exp=int((datetime.utcnow() + timedelta(seconds=settings.jwt_expiration_seconds)).timestamp()),
    )
    return jwt.encode(payload.model_dump(), settings.jwt_secret, algorithm="HS256")
```

2. **Login call site** — after fetching the user/workspace row, add the grandfathering query before the encode_jwt call:
```python
# Determine email_verified: True if email_verified_at is set, or if user has
# no pending verification token (pre-v1.2 grandfathered users have no token).
has_pending_token = await execute_query(
    "SELECT 1 FROM auth_tokens WHERE user_id=$1 AND type='email_verification' AND used_at IS NULL AND expires_at > now()",
    user_id,
)
email_verified = bool(row.get("email_verified_at")) or not bool(has_pending_token)
```
Then update the encode_jwt call to pass `email_verified=email_verified`.
Also update the `LoginResponse(...)` return to include `email_verified=email_verified`.

Read lines 590–680 before editing to confirm the exact variable names (`user_id`, `row`, etc.) used in the login path.

3. **Signup call site** — new signups are unverified; pass `email_verified=False`:
```python
token = encode_jwt(workspace_id, user_id, "owner", "free", email_verified=False)
```
  </action>
  <acceptance_criteria>
    - burnlens_cloud/auth.py `encode_jwt` signature contains `email_verified: bool = True`
    - burnlens_cloud/auth.py contains `has_pending_token = await execute_query(` near the login encode_jwt call
    - burnlens_cloud/auth.py contains `email_verified=email_verified` in the login path encode_jwt call
    - burnlens_cloud/auth.py contains `email_verified=False` in the signup path encode_jwt call
    - `python -c "import ast; ast.parse(open('burnlens_cloud/auth.py').read()); print('OK')"` → `OK`
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 3: Add password-reset rate-limit rule to DEFAULT_RULES in rate_limit.py</name>
  <files>burnlens_cloud/rate_limit.py</files>
  <read_first>
    - burnlens_cloud/rate_limit.py lines 86-92 (DEFAULT_RULES tuple — exact current content)
  </read_first>
  <action>
Add `("/auth/reset-password", 3, 900)` to the DEFAULT_RULES tuple (3 requests per 900 seconds = 15 minutes per IP):

```python
DEFAULT_RULES: tuple[tuple[str, int, int], ...] = (
    ("/auth/login", 10, 60),
    ("/auth/signup", 5, 60),
    ("/auth/invite", 20, 60),
    ("/auth/reset-password", 3, 900),
    ("/v1/ingest", 600, 60),
)
```
  </action>
  <acceptance_criteria>
    - burnlens_cloud/rate_limit.py contains `("/auth/reset-password", 3, 900)` inside DEFAULT_RULES tuple
    - `python -c "import ast; ast.parse(open('burnlens_cloud/rate_limit.py').read()); print('OK')"` → `OK`
  </acceptance_criteria>
</task>

</tasks>

<verification>
1. `grep "email_verified" burnlens_cloud/models.py` → shows 3 lines (TokenPayload, LoginResponse, SignupResponse)
2. `grep -n "email_verified" burnlens_cloud/auth.py` → shows encode_jwt signature + login site + signup site
3. `grep '"/auth/reset-password"' burnlens_cloud/rate_limit.py` → shows the DEFAULT_RULES entry
4. `python -c "import ast; ast.parse(open('burnlens_cloud/models.py').read()); print('OK')"` → `OK`
5. `python -c "import ast; ast.parse(open('burnlens_cloud/auth.py').read()); print('OK')"` → `OK`
6. `python -c "import ast; ast.parse(open('burnlens_cloud/rate_limit.py').read()); print('OK')"` → `OK`
</verification>

<threat_model>
## Security Threat Model (ASVS L1)

| Threat | Severity | Mitigation |
|--------|----------|-----------|
| Token brute force on reset endpoint | HIGH | 3 req/15min rate limit via DEFAULT_RULES entry added in Task 3 |
| Grandfathered user incorrectly marked unverified | MEDIUM | `email_verified = bool(email_verified_at) OR NOT has_pending_token` — old users with no token row evaluate as verified |
| JWT email_verified field tampered | LOW | JWT signed with `settings.jwt_secret`; tampering invalidates signature |

No high-severity unmitigated threats.
</threat_model>

<must_haves>
- TokenPayload.email_verified bool added; encode_jwt updated; login + signup call sites updated
- Grandfathering logic: NULL email_verified_at + no pending token → email_verified=True
- Rate limit rule /auth/reset-password 3/900s added to DEFAULT_RULES
- All 3 files parse without Python syntax errors
</must_haves>
