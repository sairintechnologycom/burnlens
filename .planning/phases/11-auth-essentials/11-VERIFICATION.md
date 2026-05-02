---
phase: 11-auth-essentials
verified: 2026-05-02T07:40:00Z
status: gaps_found
score: 10/13 must-haves verified
overrides_applied: 0
gaps:
  - truth: "POST /auth/reset-password/confirm validates token via atomic UPDATE rowcount (0 = already used or expired, 1 = claimed)"
    status: partial
    reason: "The UPDATE is atomic but user_id is fetched in a SEPARATE SELECT after the token has been consumed (TOCTOU — CR-01). Under a race between two near-simultaneous requests or a concurrent cleanup job, the second SELECT can return zero rows after the UPDATE succeeded, permanently burning the token without resetting the password. RETURNING user_id is absent. Identified by code review as CR-01."
    artifacts:
      - path: "burnlens_cloud/auth.py"
        issue: "Lines 1024-1028: SELECT user_id FROM auth_tokens WHERE token_hash = $1 issued after UPDATE SET used_at — no RETURNING clause. CR-01 fix was NOT applied."
    missing:
      - "Replace the two-query pattern (UPDATE then SELECT) with a single UPDATE ... RETURNING user_id in confirm_password_reset (lines 1011-1028)"

  - truth: "GET /auth/verify-email?token=xxx claims token atomically and sets users.email_verified_at = now()"
    status: partial
    reason: "Same TOCTOU as CR-01: user_id fetched in a second SELECT after the token is burned (CR-02). Additionally, the endpoint is a GET with the secret token in the URL query string — logged by Railway, browser history, and Referer headers (CR-03). Neither CR-02 nor CR-03 were fixed."
    artifacts:
      - path: "burnlens_cloud/auth.py"
        issue: "Lines 1068-1072: SELECT user_id FROM auth_tokens WHERE token_hash = $1 issued after UPDATE SET used_at — same TOCTOU as CR-01. RETURNING clause missing."
      - path: "burnlens_cloud/auth.py"
        issue: "Line 1050: @router.get('/verify-email') — token in URL query string exposes it in server logs, browser history, and Referer headers."
      - path: "frontend/src/app/verify-email/page.tsx"
        issue: "Line 23: fetch with GET and token in query string — must change to POST with token in request body."
    missing:
      - "Replace two-query pattern in verify_email with UPDATE ... RETURNING user_id (lines 1055-1074)"
      - "Change GET /auth/verify-email to POST /auth/verify-email accepting {token} in request body"
      - "Update frontend verify-email/page.tsx to POST {token} in request body instead of GET ?token="

  - truth: "Rate limit rule /auth/resend-verification present in DEFAULT_RULES"
    status: failed
    reason: "DEFAULT_RULES in rate_limit.py contains no entry for /auth/resend-verification. The endpoint is open to unlimited enumeration attempts and email-bomb abuse (WR-01 from code review). The plan (03a) only required /auth/reset-password rate limit, which was correctly added; resend-verification was called out in the review but no plan task covered it."
    artifacts:
      - path: "burnlens_cloud/rate_limit.py"
        issue: "DEFAULT_RULES tuple contains /auth/login, /auth/signup, /auth/invite, /auth/reset-password, /v1/ingest — no entry for /auth/resend-verification."
    missing:
      - "Add ('/auth/resend-verification', 3, 900) to DEFAULT_RULES in rate_limit.py"
---

# Phase 11: Auth Essentials Verification Report

**Phase Goal:** Cloud users can recover locked accounts and verify email ownership; transactional email infrastructure supports all current and future notification types
**Verified:** 2026-05-02T07:40:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC-1 | User can request reset, click link, set new password — single-use token | PARTIAL | Backend routes exist; token claim has TOCTOU race (CR-01, CR-02 unfixed) |
| SC-2 | Reset request endpoint always returns 200 — no enumeration | VERIFIED | auth.py line 964: always returns same message body regardless of email lookup result |
| SC-3 | New signup gets welcome + verification email; unverified user sees banner | VERIFIED | signup() fires send_welcome_email + send_verify_email; BillingStatusBanner renders verify banner when emailVerified=false |
| SC-4 | Pre-v1.2 users grandfathered as verified — no action required | VERIFIED | Grandfathering logic at auth.py line 685; email_verified_at NULL + no pending token → true; LOCAL_SESSION.emailVerified=true |
| SC-5 | Password-changed confirmation email sent after reset; payment receipt via template registry | PARTIAL | send_password_changed_email called in confirm handler; send_payment_receipt_email called from billing.py _handle_transaction_completed. However confirm_password_reset has TOCTOU meaning the email may fire even if the password update silently failed |

### Per-Plan Must-Have Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| T-01 | auth_tokens table exists with all specified columns and constraints | VERIFIED | database.py lines 858-868: CREATE TABLE IF NOT EXISTS auth_tokens with all required columns |
| T-02 | idx_auth_tokens_user_active index on auth_tokens(user_id, type) WHERE used_at IS NULL | VERIFIED | database.py lines 869-872 |
| T-03 | users table has email_verified_at TIMESTAMPTZ column (nullable) | VERIFIED | database.py lines 875-877: ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ |
| T-04 | Both schema changes are idempotent (IF NOT EXISTS guards) | VERIFIED | CREATE TABLE IF NOT EXISTS + ADD COLUMN IF NOT EXISTS throughout |
| T-05 | TemplateSpec TypedDict with correct fields; TEMPLATE_REGISTRY maps 5 keys | VERIFIED | email.py lines 18-50: TypedDict + registry with welcome, verify_email, password_changed, reset_password, payment_receipt |
| T-06 | 4 send_*_email() functions exist, fail-open, background-task pattern | VERIFIED | email.py lines 336-468: all 4 functions present with track_email_task(asyncio.create_task()) pattern |
| T-07 | All HTML template files exist with correct {{placeholder}} variables | VERIFIED | All 5 templates present: welcome.html, verify_email.html, password_changed.html, reset_password.html, payment_receipt.html |
| T-08 | TokenPayload / LoginResponse / SignupResponse gain email_verified field | VERIFIED | models.py lines 82, 100, 111: all three classes have correct defaults |
| T-09 | encode_jwt accepts email_verified parameter; both call sites updated | VERIFIED | auth.py line 180: signature with email_verified=True default; line 687: login site; line 799: signup site |
| T-10 | Login grandfathering logic: has_pending_token check | PARTIAL | auth.py line 681-685: has_pending_token query present. However row (from workspace JOIN query) does NOT include email_verified_at — so bool(row.get("email_verified_at")) always evaluates False (WR-04 from review). Grandfathering still works because the fallback `not bool(has_pending_token)` is correct for pre-v1.2 users who have no token row. |
| T-11 | DEFAULT_RULES includes ('/auth/reset-password', 3, 900) | VERIFIED | rate_limit.py line 90 |
| T-12 | POST /auth/reset-password always 200 (no enumeration) | VERIFIED | auth.py lines 963-992: returns identical message body whether email exists or not |
| T-13 | POST /auth/reset-password/confirm atomic single-use claim | PARTIAL | UPDATE rowcount check exists but user_id fetched in second SELECT after token consumed — TOCTOU (CR-01 unfixed) |
| T-14 | GET /auth/verify-email claims token atomically + sets email_verified_at | PARTIAL | Atomic UPDATE exists; same TOCTOU as CR-01; additionally token in URL query string (CR-03 unfixed) |
| T-15 | POST /auth/resend-verification always 200; only sends if user exists and unverified | VERIFIED | auth.py lines 1085-1119: always returns same message |
| T-16 | signup() fires welcome + verify emails; creates email_verification auth_token | VERIFIED | auth.py lines 780-796 |
| T-17 | signup() returns SignupResponse with email_verified=False | VERIFIED | auth.py lines 812-820 |
| T-18 | _handle_transaction_completed() wired in dispatch; calls send_payment_receipt_email | VERIFIED | billing.py line 372-373: dispatch wiring; line 576: function definition; line 642-643: email call |
| T-19 | AuthSession.emailVerified field; localStorage persistence; logout cleanup | VERIFIED | useAuth.ts lines 17, 39, 60-62, 100 |
| T-20 | setup/page.tsx stores emailVerified after login/signup; Forgot password? flow | VERIFIED | setup/page.tsx lines 31, 50-54, 99-102, 397-430 |
| T-21 | /reset-password page: form → POST /auth/reset-password/confirm; Suspense wrapper | VERIFIED | reset-password/page.tsx: lines 38-42 (POST to confirm), Suspense at line 294 |
| T-22 | /verify-email page: calls backend on mount; sets localStorage on success; Suspense | PARTIAL | Sets localStorage on success (line 26); Suspense present; BUT calls backend as GET with token in URL — CR-03 unfixed |
| T-23 | BillingStatusBanner renders verify banner when emailVerified=false && !isLocal | VERIFIED | BillingStatusBanner.tsx line 26: showVerify derived correctly; aria-label="Email verification required" at line 66 |
| T-24 | /auth/resend-verification rate-limited in DEFAULT_RULES | FAILED | No entry in rate_limit.py DEFAULT_RULES |

**Score:** 10/13 must-have truths verified (mapping SC truths 1-5 and T-13/T-14/T-24 to gap status)

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `burnlens_cloud/database.py` | auth_tokens table + index + email_verified_at column | VERIFIED | All present in init_db() |
| `burnlens_cloud/email.py` | TemplateSpec, TEMPLATE_REGISTRY, 5 send functions | VERIFIED | All present, syntax OK |
| `burnlens_cloud/emails/templates/welcome.html` | Welcome template | VERIFIED | Exists with {{workspace_name}} |
| `burnlens_cloud/emails/templates/verify_email.html` | Verify email template | VERIFIED | Exists with {{verify_url}} |
| `burnlens_cloud/emails/templates/password_changed.html` | Password changed template | VERIFIED | Exists, no variables needed |
| `burnlens_cloud/emails/templates/reset_password.html` | Reset password template | VERIFIED | Exists with {{reset_url}} |
| `burnlens_cloud/emails/templates/payment_receipt.html` | Payment receipt template | VERIFIED | Exists with all 3 variables |
| `burnlens_cloud/models.py` | TokenPayload/LoginResponse/SignupResponse with email_verified | VERIFIED | All 3 models updated |
| `burnlens_cloud/auth.py` | encode_jwt update + 4 new routes + signup wiring | PARTIAL | Present but 2 routes have TOCTOU |
| `burnlens_cloud/rate_limit.py` | /auth/reset-password rate limit | VERIFIED | Present |
| `burnlens_cloud/billing.py` | _handle_transaction_completed + dispatch | VERIFIED | Present and wired |
| `frontend/src/lib/hooks/useAuth.ts` | emailVerified in AuthSession + localStorage | VERIFIED | All present |
| `frontend/src/app/setup/page.tsx` | emailVerified storage + Forgot password flow | VERIFIED | Both present |
| `frontend/src/app/reset-password/page.tsx` | Password reset form page | VERIFIED | Exists, Suspense, POST to confirm |
| `frontend/src/app/verify-email/page.tsx` | Email verification page | PARTIAL | Exists, Suspense, localStorage on success — BUT uses GET not POST (CR-03) |
| `frontend/src/components/BillingStatusBanner.tsx` | Email verify banner | VERIFIED | showVerify, emailVerified===false, past_due preserved |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| database.py::auth_tokens | auth.py reset/verify routes | token_hash lookup | WIRED | token_hash used in UPDATE WHERE clauses |
| email.py::send_welcome_email | auth.py::signup() | called after user creation | WIRED | auth.py line 795 |
| email.py::send_verify_email | auth.py::signup() + resend-verification | called with verify_url | WIRED | auth.py lines 796, 1118 |
| email.py::send_password_changed_email | auth.py::confirm_password_reset | called after password update | WIRED | auth.py line 1045 |
| email.py::send_payment_receipt_email | billing.py::_handle_transaction_completed | called after workspace lookup | WIRED | billing.py line 643 |
| reset-password/page.tsx | auth.py POST /auth/reset-password/confirm | POST ${API_BASE}/auth/reset-password/confirm | WIRED | page.tsx line 38 |
| verify-email/page.tsx | auth.py GET /auth/verify-email | GET ${API_BASE}/auth/verify-email?token= | WIRED but INSECURE | Token exposed in URL (CR-03) |
| BillingStatusBanner.tsx | useAuth.ts::AuthSession.emailVerified | session?.emailVerified === false | WIRED | BillingStatusBanner.tsx line 26 |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| auth.py::login | email_verified | users + auth_tokens tables | YES (DB query) | FLOWING — but email_verified_at path always returns None (WR-04; see warnings) |
| auth.py::signup | email_verified=False | hardcoded constant | N/A (correct) | FLOWING |
| BillingStatusBanner.tsx | session.emailVerified | localStorage via useAuth | YES | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| auth_tokens table DDL present | grep -c "CREATE TABLE IF NOT EXISTS auth_tokens" database.py | 1 | PASS |
| reset-password route registered | grep -c 'router.post("/reset-password"' auth.py | 1 | PASS |
| verify-email route is GET (should be POST) | grep "router.get.*verify-email" auth.py | match | FAIL (CR-03) |
| resend-verification in DEFAULT_RULES | grep "resend-verification" rate_limit.py | no output | FAIL |
| TOCTOU: SELECT after UPDATE (no RETURNING) | grep "SELECT user_id FROM auth_tokens WHERE token_hash" auth.py | 2 matches | FAIL (CR-01+CR-02) |
| Python syntax valid | python3 -c "import ast; ast.parse(...)" on all 4 backend files | OK | PASS |
| HTML templates all exist | ls burnlens_cloud/emails/templates/ | all 5 present | PASS |

---

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| AUTH-01 | Password reset via email, always 200 | SATISFIED | POST /auth/reset-password at auth.py line 953; always returns 200 |
| AUTH-02 | Single-use time-limited reset token | PARTIAL | Token issued and claimed atomically via UPDATE — but TOCTOU means user_id lookup can fail silently after token is burned (CR-01) |
| AUTH-03 | Password reset endpoint rate-limited | SATISFIED | ('/auth/reset-password', 3, 900) in DEFAULT_RULES |
| AUTH-04 | Signup triggers verification email | SATISFIED | signup() creates auth_token + calls send_verify_email (auth.py lines 781-796) |
| AUTH-05 | Email confirmation via verification link | PARTIAL | GET /auth/verify-email works but: (1) TOCTOU on user_id lookup (CR-02), (2) token in URL query string (CR-03) |
| AUTH-06 | Unverified users see persistent banner | SATISFIED | BillingStatusBanner shows emailVerified===false banner; soft-gate only (MVP intent) |
| AUTH-07 | Pre-v1.2 users grandfathered as verified | SATISFIED | Grandfathering via not bool(has_pending_token); NULL email_verified_at treated as verified for old users |
| EMAIL-01 | Welcome email on signup | SATISFIED | send_welcome_email called in signup(); template exists |
| EMAIL-02 | Password-changed confirmation email after reset | SATISFIED | send_password_changed_email called in confirm_password_reset; template exists |
| EMAIL-03 | Payment receipt via Paddle webhook handler | SATISFIED | _handle_transaction_completed calls send_payment_receipt_email; wired into dispatch |
| EMAIL-04 | Typed template registry for future templates | SATISFIED | TEMPLATE_REGISTRY with TemplateSpec TypedDict in email.py; 5 templates registered |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| burnlens_cloud/auth.py | 1024-1028 | SELECT after consuming UPDATE — no RETURNING | BLOCKER | TOCTOU: token burned, user_id lookup can return 0 rows under concurrency; password update silently skipped |
| burnlens_cloud/auth.py | 1068-1072 | SELECT after consuming UPDATE — no RETURNING | BLOCKER | Same TOCTOU on email verification path |
| burnlens_cloud/auth.py | 1050 | @router.get with secret token in URL query string | BLOCKER | Token logged by Railway, browser history, Referer — secret no longer secret |
| frontend/src/app/verify-email/page.tsx | 23 | GET request with secret token in URL | BLOCKER | Frontend side of CR-03 — must change to POST with body |
| burnlens_cloud/rate_limit.py | 86-92 | /auth/resend-verification missing from DEFAULT_RULES | WARNING | Email-bomb and timing-based enumeration of registered emails |
| burnlens_cloud/email.py | 119-148 | send_invitation_email uses f-string with user-supplied values — no HTML escaping | WARNING | Stored-XSS on invitation email recipients (CR-04 — pre-existing, not introduced by Phase 11) |
| burnlens_cloud/auth.py | 685 | row.get("email_verified_at") always None — column not in JOIN SELECT | WARNING | email_verified_at path never fires; grandfathering still works via has_pending_token fallback but the code path is silently wrong |
| frontend/src/components/BillingStatusBanner.tsx | 82-90 | "resend verification email" link goes to /setup — no resend endpoint called | WARNING | User clicks link expecting resend; lands on login page with no resend UI (WR-07) |

---

### Human Verification Required

#### 1. End-to-end password reset flow

**Test:** Register a new account. Use "Forgot password?" on the /setup page. Enter the email and submit. Check that a reset email arrives (requires SendGrid configured). Click the reset link. Enter a new password. Verify the old password no longer works and the new password allows login.
**Expected:** All steps succeed; reset link is single-use (second click returns 400).
**Why human:** Requires live SendGrid configuration, email delivery, and browser interaction.

#### 2. Email verification banner dismissal

**Test:** Register a new account. Observe the amber verification banner in the dashboard. Click the verification link from the email. Navigate back to the dashboard without re-logging in.
**Expected:** Banner is gone (localStorage burnlens_email_verified set to "true" by verify-email page).
**Why human:** Requires live email delivery and browser localStorage interaction.

#### 3. Pre-v1.2 user grandfathering

**Test:** In a staging database, insert a user row with email_verified_at = NULL and no auth_tokens rows. Log in as that user. Check that the dashboard shows no verification banner.
**Expected:** emailVerified=true in JWT; banner absent.
**Why human:** Requires staging database access and session inspection.

#### 4. BillingStatusBanner "resend verification email" link

**Test:** Log in as an unverified user. Observe the amber banner. Click "resend verification email".
**Expected:** Based on current code, this navigates to /setup (login page) — NOT to a resend endpoint. This is a UX bug (WR-07).
**Why human:** Requires browser interaction; confirms the broken link behavior documented in WR-07.

---

### Gaps Summary

Three blockers prevent full phase goal achievement:

**Blocker 1 (CR-01+CR-02): TOCTOU in token redemption handlers.** Both `confirm_password_reset` and `verify_email` issue a `UPDATE ... SET used_at=now()` to atomically claim the token, then issue a second `SELECT user_id FROM auth_tokens WHERE token_hash=$1` to retrieve the user. The second SELECT has no `AND used_at IS NULL` filter, meaning it can return the burned row — but under concurrent load or a concurrent cleanup job the row may no longer be present, causing the SELECT to return empty. When that happens for `confirm_password_reset`, the token is permanently consumed but the password is never updated and no error is logged to the user (the 400 fires after the UPDATE). The fix is one-line per function: replace the two-query pattern with `UPDATE ... RETURNING user_id`.

**Blocker 2 (CR-03): Verification token in URL query string.** `GET /auth/verify-email?token=<raw_token>` exposes the 256-bit secret token in Railway access logs, browser history, and Referer headers. This makes the token recoverable by anyone with log read access. Both the backend (`@router.get`) and the frontend (`fetch` GET with encoded query param) must be changed to POST with token in request body. This also means the verify-email page's current `fetch(API_BASE/auth/verify-email?token=...)` call will break if the backend is fixed without the frontend change.

**Blocker 3 (WR-01): /auth/resend-verification has no rate limit.** The endpoint is absent from `DEFAULT_RULES` in `rate_limit.py`. An unauthenticated attacker can trigger unlimited outbound emails to any registered address with no throttle. The fix is a single-line addition to `DEFAULT_RULES`: `('/auth/resend-verification', 3, 900)`.

These three gaps leave AUTH-02 (single-use reset), AUTH-05 (email confirmation), and the secure transport of the verification credential in a state that is functionally incomplete or insecure. The remaining 10 requirements (AUTH-01, AUTH-03, AUTH-04, AUTH-06, AUTH-07, EMAIL-01 through EMAIL-04) are fully satisfied.

---

_Verified: 2026-05-02T07:40:00Z_
_Verifier: Claude (gsd-verifier)_
