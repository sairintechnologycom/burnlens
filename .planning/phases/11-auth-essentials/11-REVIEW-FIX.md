---
phase: 11-auth-essentials
fixed_at: 2026-05-02T12:30:00Z
review_path: .planning/phases/11-auth-essentials/11-REVIEW.md
iteration: 1
findings_in_scope: 11
fixed: 11
skipped: 0
status: all_fixed
---

# Phase 11: Code Review Fix Report

**Fixed at:** 2026-05-02T12:30:00Z
**Source review:** .planning/phases/11-auth-essentials/11-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 11 (4 Critical, 7 Warning)
- Fixed: 11
- Skipped: 0

## Fixed Issues

### CR-01: TOCTOU in `confirm_password_reset`

**Files modified:** `burnlens_cloud/auth.py`
**Commit:** 8df4046
**Applied fix:** Replaced the two-query pattern (UPDATE then separate SELECT) with a single `UPDATE ... RETURNING user_id` query. The `user_id` is now returned atomically from the same statement that consumes the token, eliminating the TOCTOU window entirely.

---

### CR-02: TOCTOU in `verify_email` + CR-03: Token exposed in GET query string

**Files modified:** `burnlens_cloud/auth.py`, `frontend/src/app/verify-email/page.tsx`
**Commit:** 600ebbb
**Applied fix (CR-02):** Same `UPDATE ... RETURNING user_id` pattern as CR-01 applied to `verify_email`. Added `VerifyEmailBody` Pydantic model for the request body.
**Applied fix (CR-03):** Changed `@router.get("/verify-email")` to `@router.post("/verify-email")` accepting `token` in the JSON request body. Updated `verify-email/page.tsx` to POST with `Content-Type: application/json` and `body: JSON.stringify({ token })` instead of embedding the token in the URL query string.

*Note: CR-02 and CR-03 were committed together as they are structurally coupled — both touch the same endpoint definition.*

---

### CR-04: Stored XSS via unescaped `workspace_name`/`invited_by_name`

**Files modified:** `burnlens_cloud/email.py`
**Commit:** 68d217d
**Applied fix:** Added `import html as _html` and `import urllib.parse` at the module level. Inside `send_invitation_email`, applied `_html.escape()` to both `workspace_name` and `invited_by_name` before f-string interpolation, and `urllib.parse.quote(..., safe=':/?=&')` to the `invite_url` used in `href` and `<code>` contexts. All user-supplied HTML context values are now escaped.

---

### WR-01: Rate-limit rule missing for `/auth/resend-verification`

**Files modified:** `burnlens_cloud/rate_limit.py`
**Commit:** 85859c9
**Applied fix:** Added `("/auth/resend-verification", 3, 900)` to `DEFAULT_RULES`, matching the same budget as `/auth/reset-password`.

---

### WR-02: `emailVerified` sourced from localStorage — tamper suppresses banner

**Files modified:** `frontend/src/lib/hooks/useAuth.ts`
**Commit:** 42c9ed5
**Applied fix:** Changed the null-fallback for `burnlens_email_verified` from `true` to `false`. A missing or tampered value now defaults to showing the verification banner rather than suppressing it. This is the safe direction: more banners, never fewer. Verified users have the value explicitly set to `"true"` by `verify-email/page.tsx` on successful verification.

---

### WR-03: X-Forwarded-For first hop trusted — rate limit bypassed by spoofing

**Files modified:** `burnlens_cloud/rate_limit.py`
**Commit:** 4c60ef3
**Applied fix:** Changed `xff.split(",")[0].strip()` to `xff.split(",")[-1].strip()`. Railway appends a real hop to the XFF header, so the legitimate client IP is the last entry. Taking the first entry allowed an attacker to spoof their rate-limit bucket by injecting a fake XFF value.

---

### WR-04: `email_verified` claim in login JWT always None

**Files modified:** `burnlens_cloud/auth.py`
**Commit:** 7d0d714
**Applied fix:** Added an explicit `SELECT email_verified_at FROM users WHERE id = $1` query executed after `user_id` is resolved (applies to both the email+password and api_key branches). The result `is_verified_by_timestamp` is ORed with `not bool(has_pending_token)` so the logic is correct for verified users, new unverified users, and grandfathered users without tokens.

---

### WR-05: `send_invitation_email` inline f-string instead of template system

**Files modified:** `burnlens_cloud/email.py`, `burnlens_cloud/emails/templates/invitation.html`
**Commit:** 99c295a
**Applied fix:** Created `burnlens_cloud/emails/templates/invitation.html` with `{{workspace_name}}`, `{{invited_by_intro}}`, and `{{invite_url}}` placeholders. Added `"invitation"` entry to `TEMPLATE_REGISTRY` (subject also uses `{{workspace_name}}`). Rewrote `send_invitation_email` to load the template file and use `.replace()` substitution with HTML-escaped values (CR-04 escaping preserved). Function is now structurally consistent with all other sender functions.

---

### WR-06: Webhook signature `tolerance` parameter unguarded

**Files modified:** `burnlens_cloud/billing.py`
**Commit:** a559a2f
**Applied fix:** Added `assert 0 < tolerance <= 300, f"tolerance must be between 1 and 300 seconds, got {tolerance}"` as the first statement in `_verify_signature`. This ensures misconfigured callers (tolerance=0 or extremely large values) raise immediately with a clear message rather than silently changing replay-window security properties.

---

### WR-07: BillingStatusBanner "resend" link goes to `/setup` not resend endpoint

**Files modified:** `frontend/src/components/BillingStatusBanner.tsx`, `frontend/src/lib/hooks/useAuth.ts`, `frontend/src/app/setup/page.tsx`
**Commit:** dcd1b56
**Applied fix:** Three-part change:
1. `setup/page.tsx` — `storeSession` now persists `data.workspace.owner_email` to `localStorage` as `burnlens_owner_email`.
2. `useAuth.ts` — Added `ownerEmail: string` to `AuthSession` interface and `LOCAL_SESSION`; reads `burnlens_owner_email` from localStorage; clears it on logout.
3. `BillingStatusBanner.tsx` — Replaced the `<a href="/setup">resend verification email</a>` link with a `<button>` that POSTs to `/auth/resend-verification` with the user's email. Button cycles through idle/sending/sent/error states for user feedback.

---

_Fixed: 2026-05-02T12:30:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
