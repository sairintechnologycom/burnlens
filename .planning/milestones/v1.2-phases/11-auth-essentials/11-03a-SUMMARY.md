---
phase: 11-auth-essentials
plan: "03a"
subsystem: cloud-backend
tags: [jwt, email-verification, rate-limiting, models, auth]

# Dependency graph
requires:
  - 11-01 (auth_tokens table + email_verified_at column)
  - 11-02 (email.py send functions)
provides:
  - burnlens_cloud/models.py::TokenPayload.email_verified
  - burnlens_cloud/models.py::LoginResponse.email_verified
  - burnlens_cloud/models.py::SignupResponse.email_verified
  - burnlens_cloud/auth.py::encode_jwt (email_verified parameter)
  - burnlens_cloud/auth.py login grandfathering logic
  - burnlens_cloud/rate_limit.py::DEFAULT_RULES /auth/reset-password entry
affects:
  - 11-03b (route handlers use encode_jwt + models with email_verified)
  - 11-05a (useAuth.ts reads email_verified from JWT/login response)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Grandfathering pattern: email_verified = bool(email_verified_at) OR NOT has_pending_token — pre-v1.2 users with no token row evaluate as verified"
    - "Default-True field in TokenPayload and LoginResponse for backward compat; SignupResponse default-False for new-user intent"

key-files:
  created: []
  modified:
    - burnlens_cloud/models.py
    - burnlens_cloud/auth.py
    - burnlens_cloud/rate_limit.py

key-decisions:
  - "email_verified defaults True in TokenPayload/LoginResponse (backward compat for existing sessions); False only in SignupResponse (explicit new-user intent)"
  - "Grandfathering: users with no pending email_verification token are treated as verified — avoids locking out pre-v1.2 users on deploy"
  - "LoginResponse propagates email_verified so frontend can gate /verify-email prompt without a second API call"

requirements-completed: [AUTH-05, AUTH-07]

# Metrics
duration: "30m"
completed: "2026-05-02"
---

# Phase 11 Plan 03a: email_verified in JWT, Models, and Rate Limit Summary

**JWT email_verified field added to TokenPayload + LoginResponse + SignupResponse; encode_jwt extended with grandfathering logic at login; /auth/reset-password rate-limit rule (3/900s) added to DEFAULT_RULES.**

## Performance

- **Duration:** 30 min
- **Started:** 2026-05-02T05:58:25Z
- **Completed:** 2026-05-02T06:28:00Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Added `email_verified: bool = True` to `TokenPayload` (JWT payload carries verification state; default True preserves backward compat for existing tokens)
- Added `email_verified: bool = True` to `LoginResponse` (frontend reads from login API response without re-decoding JWT)
- Added `email_verified: bool = False` to `SignupResponse` (new signups always start unverified)
- Extended `encode_jwt` signature with `email_verified: bool = True` parameter; passes field into `TokenPayload` construction
- Login call site: added grandfathering query (`SELECT 1 FROM auth_tokens WHERE user_id=$1 AND type='email_verification' AND used_at IS NULL AND expires_at > now()`); `email_verified = bool(email_verified_at) or not bool(has_pending_token)` — pre-v1.2 users with no pending token are grandfathered as verified
- Login call site: passes `email_verified=email_verified` to `encode_jwt` and to `LoginResponse` return
- Signup call site: passes `email_verified=False` to `encode_jwt` (new signups are unverified)
- `DEFAULT_RULES` in `rate_limit.py` gains `("/auth/reset-password", 3, 900)` — 3 requests per 15 minutes per IP (brute-force protection for password-reset token endpoint)

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add email_verified to TokenPayload, LoginResponse, SignupResponse | 793849e | burnlens_cloud/models.py |
| 2 | Update encode_jwt signature and both call sites | 612554e | burnlens_cloud/auth.py |
| 3 | Add /auth/reset-password rate-limit rule to DEFAULT_RULES | cb1ef0c | burnlens_cloud/rate_limit.py |

## Files Created/Modified

- `burnlens_cloud/models.py` — `email_verified` field added to TokenPayload, LoginResponse, SignupResponse
- `burnlens_cloud/auth.py` — `encode_jwt` extended; login grandfathering logic; signup passes False; LoginResponse propagates field
- `burnlens_cloud/rate_limit.py` — `/auth/reset-password` rate-limit rule added to DEFAULT_RULES

## Decisions Made

- `email_verified` defaults to `True` in `TokenPayload` and `LoginResponse` for backward compatibility: existing sessions (issued before this deploy) will decode with the default and not lock out users.
- `SignupResponse.email_verified` defaults to `False` because new signups are definitionally unverified — frontend can show the verification prompt immediately.
- Grandfathering condition `bool(email_verified_at) OR NOT bool(has_pending_token)` handles two cases: (a) user who explicitly verified gets `email_verified_at` set; (b) pre-v1.2 users have no `auth_tokens` row of type `email_verification`, so the OR branch fires and they're treated as verified without backfill.

## Deviations from Plan

None — plan executed exactly as written. The `LoginResponse` `email_verified` propagation was specified in the plan's action block (Task 2) and all three models changes were explicit.

## Verification Results

All plan verification checks passed:

1. `grep "email_verified" burnlens_cloud/models.py` → 3 lines (TokenPayload, LoginResponse, SignupResponse)
2. `grep -n "email_verified" burnlens_cloud/auth.py` → encode_jwt signature (179), TokenPayload construction (189), login grandfathering (684), login encode_jwt call (686), LoginResponse return (708), signup encode_jwt call (780)
3. `grep '"/auth/reset-password"' burnlens_cloud/rate_limit.py` → `("/auth/reset-password", 3, 900),`
4. `python3 -c "import ast; ast.parse(open('burnlens_cloud/models.py').read()); print('OK')"` → OK
5. `python3 -c "import ast; ast.parse(open('burnlens_cloud/auth.py').read()); print('OK')"` → OK
6. `python3 -c "import ast; ast.parse(open('burnlens_cloud/rate_limit.py').read()); print('OK')"` → OK

## Known Stubs

None — all changes are fully wired. The `email_verified` field flows from DB query through encode_jwt into JWT payload and into API response. No placeholder values.

## Threat Flags

None — no new network endpoints or trust boundaries. The `/auth/reset-password` rate-limit rule is a mitigation (closing the brute-force threat identified in the plan's threat model, not a new surface).

## Self-Check: PASSED

- burnlens_cloud/models.py: FOUND (modified)
- burnlens_cloud/auth.py: FOUND (modified)
- burnlens_cloud/rate_limit.py: FOUND (modified)
- Commit 793849e exists: FOUND
- Commit 612554e exists: FOUND
- Commit cb1ef0c exists: FOUND
