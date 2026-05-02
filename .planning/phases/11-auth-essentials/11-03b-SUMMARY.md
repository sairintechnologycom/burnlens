---
phase: 11-auth-essentials
plan: "03b"
subsystem: cloud-backend
tags: [auth, password-reset, email-verification, token-claim, security]

# Dependency graph
requires:
  - 11-01 (auth_tokens table + email_verified_at column)
  - 11-02 (email.py send functions)
  - 11-03a (encode_jwt email_verified + models + rate limit)
provides:
  - burnlens_cloud/auth.py::POST /auth/reset-password
  - burnlens_cloud/auth.py::POST /auth/reset-password/confirm
  - burnlens_cloud/auth.py::GET /auth/verify-email
  - burnlens_cloud/auth.py::POST /auth/resend-verification
  - burnlens_cloud/auth.py::signup() email wiring (welcome + verify)
affects:
  - 11-05b (reset-password and verify-email frontend pages consume these endpoints)

# Tech tracking
tech-stack:
  added:
    - pydantic BaseModel import added directly to auth.py for new request models
  patterns:
    - "Anti-enumeration: POST /auth/reset-password always returns identical HTTP 200 response regardless of email existence"
    - "Atomic single-use token claim: UPDATE ... SET used_at = now() WHERE ... AND used_at IS NULL — rowcount 0 = reject"
    - "Fail-open email dispatch: send_welcome_email + send_verify_email called in signup; exceptions caught and logged, not re-raised"
    - "Token invalidation before re-issue: existing unused tokens are soft-deleted via used_at before creating a new one"

key-files:
  created: []
  modified:
    - burnlens_cloud/auth.py

key-decisions:
  - "Pydantic BaseModel imported directly in auth.py rather than in .models — request-body models for the 4 new endpoints live alongside their route handlers (colocation pattern)"
  - "signup() email wiring uses fail-open try/except around auth_token INSERT: if token creation fails, user is still logged in; error is logged, not propagated"
  - "SignupResponse explicitly passes email_verified=False even though default is False — makes intent clear at the call site"

requirements-completed: [AUTH-01, AUTH-02, AUTH-03, AUTH-04]

# Metrics
duration: "12min"
completed: "2026-05-02"
---

# Phase 11 Plan 03b: 4 Auth Endpoints + Signup Email Wiring Summary

**4 auth endpoints (reset-password, reset-password/confirm, verify-email, resend-verification) with atomic single-use token claims and anti-enumeration; signup() wired to fire welcome + verify emails and create email_verification auth_token.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-05-02T06:24:00Z
- **Completed:** 2026-05-02T06:36:56Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

### Task 1: 4 new auth route handlers

- **POST /auth/reset-password** — accepts email, always returns HTTP 200 (anti-enumeration). Looks up user by email_hash; if found: invalidates existing unused password_reset tokens, creates new token (1h expiry, secrets.token_urlsafe(32) → SHA-256 hash stored), fires send_reset_password_email.
- **POST /auth/reset-password/confirm** — accepts token + new_password. Validates length (8–128 chars). Atomic single-use claim via `UPDATE auth_tokens SET used_at = now() WHERE ... AND used_at IS NULL AND expires_at > now()` — rowcount "UPDATE 0" → 400. Updates bcrypt password hash. Fires send_password_changed_email (fail-open).
- **GET /auth/verify-email** — accepts token query param. Atomic single-use claim (same UPDATE pattern). Sets `users.email_verified_at = now()`. Returns 200 on success; 400 on invalid/expired.
- **POST /auth/resend-verification** — accepts email, always returns HTTP 200. If user exists and is unverified: invalidates existing unused tokens, creates new verification token (24h expiry), fires send_verify_email.
- Added `pydantic.BaseModel` import for the 3 new request model classes (ResetPasswordRequest, ResetPasswordConfirmRequest, ResendVerificationRequest).

### Task 2: Signup email wiring

- After workspace + user creation in `signup()`: creates `email_verification` auth_token row (INSERT into auth_tokens, fail-open with exception logging).
- Fires `send_welcome_email(email_norm, request.workspace_name)` and `send_verify_email(email_norm, verify_url)` as async calls.
- `SignupResponse(...)` return explicitly includes `email_verified=False`.

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add 4 new auth route handlers to auth.py | 61fc109 | burnlens_cloud/auth.py |
| 2 | Wire welcome + verify emails into signup() | cd3512e | burnlens_cloud/auth.py |

## Files Created/Modified

- `burnlens_cloud/auth.py` — 197 lines added: 4 new route handlers + 3 request model classes + pydantic import (Task 1); signup() email wiring + SignupResponse email_verified=False (Task 2)

## Decisions Made

- `pydantic.BaseModel` imported directly in auth.py (not via .models) so the 3 new request model classes colocate with their route handlers — consistent with how burnlens_cloud handles route-specific models.
- `signup()` email wiring wraps the `auth_tokens` INSERT in try/except so a DB failure creating the verification token doesn't block user signup — fail-open per plan must_haves.
- Explicit `email_verified=False` in `SignupResponse(...)` call site even though the model default is already False — intent is self-documenting.

## Deviations from Plan

None — plan executed exactly as written. The pydantic import was a necessary Rule 3 fix (missing dependency that would have caused NameError at runtime) but was anticipated by the plan's "ensure BaseModel is available" spirit.

## Known Stubs

None — all 4 endpoints are fully wired end-to-end. Email sends delegate to Plan 02's `send_*_email()` functions which are also fully wired.

## Threat Flags

None — all endpoints were specified in the plan's threat model. All HIGH threats mitigated:
- Anti-enumeration: both /auth/reset-password and /auth/resend-verification always return 200 with identical body
- Atomic single-use claim: UPDATE rowcount check enforced in both reset/confirm and verify-email
- Expiry enforced at DB level in WHERE clause
- 256-bit token entropy via secrets.token_urlsafe(32)
- Password length validation (8–128 chars)

## Self-Check: PASSED

- burnlens_cloud/auth.py: FOUND (modified)
- Commit 61fc109 exists: FOUND
- Commit cd3512e exists: FOUND
- `@router.post("/reset-password", status_code=200)`: FOUND (line 953)
- `@router.post("/reset-password/confirm", status_code=200)`: FOUND (line 1000)
- `@router.get("/verify-email", status_code=200)`: FOUND (line 1050)
- `@router.post("/resend-verification", status_code=200)`: FOUND (line 1085)
- `UPDATE auth_tokens SET used_at = now()`: 4 occurrences FOUND
- `result == "UPDATE 0"`: 2 occurrences FOUND
- `send_password_changed_email`: FOUND in confirm handler
- `send_welcome_email(email_norm, request.workspace_name)`: FOUND in signup()
- `INSERT INTO auth_tokens` in signup(): FOUND (line 787)
- `email_verified=False` in SignupResponse: FOUND (line 819)
- Python syntax: OK

---
*Phase: 11-auth-essentials*
*Completed: 2026-05-02*
