---
phase: 16-api-key-management
plan: 02
subsystem: auth

tags: [jwt, fastapi, pii-encryption, email-verification, regression-test]

requires:
  - phase: 11-auth-essentials
    provides: verify_token dependency, TokenPayload(user_id, role, plan, iat, exp), session-cookie + Bearer dual transport, email_verified_at column, pii_crypto.decrypt_pii
  - phase: 02c-pii-hardening
    provides: email_encrypted column on users, decrypt_pii helper

provides:
  - JWT-driven /auth/resend-verification endpoint with empty body
  - 5-case regression test suite (tests/test_phase16_auth08_resend.py)
  - Phase 11 A7 test contract updated to match the new D-12 shape

affects: [16-06 (frontend BillingStatusBanner strips email body), 17, 18]

tech-stack:
  added: []
  patterns:
    - "Session-JWT-as-identity for state-mutating auth-adjacent endpoints (replaces client-supplied identifiers)"
    - "Always-200 enumeration-safe response preserved across contract change"

key-files:
  created:
    - "tests/test_phase16_auth08_resend.py — 5-case regression test for D-12/D-14/D-15"
  modified:
    - "burnlens_cloud/auth.py — resend_verification rewritten to take Depends(verify_token); ResendVerificationRequest commented out as deprecation marker"
    - "tests/test_phase11_auth.py — TestA7ResendVerification updated to new JWT contract (Rule 1 auto-fix)"

key-decisions:
  - "D-12: drop email body, take TokenPayload via Depends(verify_token), lookup by users.id"
  - "D-14: preserve always-200 enumeration-safe response shape"
  - "D-15: regression test must cover the null-localStorage-owner_email path"
  - "Phase 11 TestA7 tests were updated in-place (Rule 1) because they asserted the now-removed body contract — keeping them green prevents a false-positive in the next CI run"

patterns-established:
  - "Patch target convention: mock burnlens_cloud.email.send_verify_email (module where the symbol lives) since the handler does a lazy import (`from .email import send_verify_email`)"
  - "Mock execute_query with side_effect=callable when SELECT/UPDATE/INSERT need distinguishing by SQL fragment"

requirements-completed: [AUTH-08]

duration: ~13 min
completed: 2026-05-12
---

# Phase 16 Plan 02: AUTH-08 Resend-Verification Fix Summary

**resend-verification now reads identity from the session JWT instead of a client-supplied email, unblocking API-key signup users whose localStorage has no owner_email**

## Performance

- **Duration:** ~13 min
- **Started:** 2026-05-12T06:00:55Z
- **Completed:** 2026-05-12T06:13:23Z
- **Tasks:** 2/2 complete
- **Files modified:** 3 (1 backend, 1 new test file, 1 existing test contract update)

## Accomplishments
- Replaced body-based email lookup with `Depends(verify_token)` + `WHERE id = $1` against `users.email_encrypted`
- Preserved the entire token-invalidate + insert + send_verify_email tail verbatim (Phase 11 owns it)
- Held the always-200 enumeration-safe contract across the rewrite
- Added 5 regression tests covering: JWT-driven path, already-verified, missing user, empty body, 401-without-session
- Updated the 3 Phase 11 A7 tests to the new contract so the broader auth test suite stays green

## Task Commits

Atomic per-task commits on `worktree-agent-abfe620deeb9832a3`:

1. **Task 1: Rewrite resend_verification to use session JWT** — `1519018` (fix)
2. **Task 2: Add regression test + update Phase 11 A7 contract** — `cba8968` (test)

_Note: TDD here followed the plan's two-task split. Task 1 was implementation-first because the verification gates in the plan asserted the *signature* via grep/inspect; Task 2 codified the behavioural surface in pytest._

## Files Created/Modified

- `burnlens_cloud/auth.py` — `resend_verification` signature now `(token: TokenPayload = Depends(verify_token))`; lookup is `SELECT id, email_encrypted, email_verified_at FROM users WHERE id = $1` with `str(token.user_id)`; tail unchanged.
- `tests/test_phase16_auth08_resend.py` — new file, 5 tests, ~135 LOC.
- `tests/test_phase11_auth.py` — `TestA7ResendVerification` rewritten to override `verify_token` via `app.dependency_overrides` and POST with empty body; SQL match string changed from `FROM users WHERE email_hash` to `FROM users WHERE id`.

## Patch Targets (codified in test docstrings)

- `burnlens_cloud.auth.execute_query` — handler's local reference to `execute_query` (imported at module top).
- `burnlens_cloud.auth.execute_insert` — same.
- `burnlens_cloud.pii_crypto.decrypt_pii` — handler does a lazy `from .pii_crypto import decrypt_pii as _dec` inside the function body; patching the source module is the correct level.
- `burnlens_cloud.email.send_verify_email` — handler does a lazy `from .email import send_verify_email`; mock at the module where the symbol lives.

## Decisions Made

- Kept the old `ResendVerificationRequest` as a commented deprecation marker rather than deleting it outright — leaves a grep-able audit trail for archaeologists.
- Did NOT touch frontend code (BillingStatusBanner.tsx) — that lives in plan 16-06 of this phase.
- Updated Phase 11 A7 tests in-place rather than deleting them — same behavioural assertions (always-200, no-leak), new transport (JWT not body).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated stale Phase 11 A7 tests asserting the old (now-removed) body contract**
- **Found during:** Task 2 verification sweep (`pytest -k "auth or verification"`).
- **Issue:** `tests/test_phase11_auth.py::TestA7ResendVerification` (3 tests) sent `{"email": ...}` bodies and expected the handler to look up `WHERE email_hash`. The D-12 rewrite intentionally removes that contract, so these tests returned 401 (no session) under the new shape.
- **Fix:** Added a `self._auth(app)` helper that injects an `app.dependency_overrides[verify_token]` for a fixed `USER_ID`; switched POST calls to empty body; flipped the SQL-fragment match in the side_effect from `FROM users WHERE email_hash` to `FROM users WHERE id`.
- **Files modified:** `tests/test_phase11_auth.py`
- **Verification:** `pytest tests/test_phase11_auth.py::TestA7ResendVerification tests/test_phase16_auth08_resend.py` → 8 passed.
- **Committed in:** `cba8968` (Task 2 commit).

---

**Total deviations:** 1 auto-fixed (1 bug — stale contract assertions).
**Impact on plan:** Necessary to keep the auth test suite green under the new contract. No scope creep — same behavioural envelope (always-200, no-leak), only the transport changed.

## Issues Encountered

- **Worktree vs. main-repo path confusion:** the Bash tool's cwd is the worktree by default, but `cd /Users/bhushan/Documents/Projects/burnlens` (without the worktree suffix) lands in the main repo. The first Edit attempt landed in the main repo file and the first commit attempt failed the HEAD assertion (HEAD on `main`). Recovered by reverting main repo and applying the edit via the worktree's absolute path. No work lost. All commits live on `worktree-agent-abfe620deeb9832a3`.

## Pre-existing Failures Logged (Out of Scope)

Two test failures are pre-existing and unrelated to this plan — logged to `deferred-items.md` for triage by the orchestrator:

- `tests/test_session_cookie.py::test_login_sets_httponly_cookie_and_authorizes_subsequent_request` (login path, not resend)
- `tests/test_teams.py::test_invitation_token_generation` (teams, not auth)

Both fail on the base commit `2487dce` as well — verified by stash-and-rerun.

## Verification

- `pytest tests/test_phase16_auth08_resend.py -x` → 5 passed.
- `pytest tests/test_phase11_auth.py::TestA7ResendVerification tests/test_phase16_auth08_resend.py` → 8 passed.
- `pytest tests/ -k "auth or verification or token"` → 98 passed, 2 pre-existing failures (logged above).
- `grep "Depends(verify_token)" burnlens_cloud/auth.py | grep -c resend_verification` → 1.
- `grep -E "class ResendVerificationRequest|request: ResendVerificationRequest" burnlens_cloud/auth.py` → only commented deprecation marker, no live usage.

## Next Phase Readiness

- AUTH-08 closed. Frontend plan 16-06 can now strip `body: JSON.stringify({email})` from `BillingStatusBanner.tsx` (line 39) and the resend path will work for null-`owner_email` localStorage users.
- No blockers for the wave-2 api-keys CRUD plans (16-03, 16-04, 16-05). This plan is in wave 1 and independent.

## Self-Check

- [x] `burnlens_cloud/auth.py` modified — verified via `grep`.
- [x] `tests/test_phase16_auth08_resend.py` created — verified `ls`.
- [x] Commit `1519018` exists — verified `git log --oneline`.
- [x] Commit `cba8968` exists — verified `git log --oneline`.
- [x] All 5 new tests pass.
- [x] All 3 updated Phase 11 A7 tests pass.

## Self-Check: PASSED

---
*Phase: 16-api-key-management*
*Completed: 2026-05-12*
