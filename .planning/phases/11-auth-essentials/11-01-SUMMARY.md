---
phase: 11-auth-essentials
plan: "01"
subsystem: database
tags: [postgres, asyncpg, schema-migration, auth-tokens, email-verification]

# Dependency graph
requires: []
provides:
  - auth_tokens Postgres table with UUID PK, user_id FK ON DELETE CASCADE, type CHECK constraint (password_reset/email_verification), token_hash UNIQUE, expires_at, used_at, created_at
  - idx_auth_tokens_user_active partial index on (user_id, type) WHERE used_at IS NULL for fast active-token lookups
  - email_verified_at TIMESTAMPTZ column on users (NULL = grandfathered verified for pre-v1.2 users)
affects:
  - 11-03a (models.py + encode_jwt email_verified field)
  - 11-03b (POST /auth/reset-password endpoints, token_hash lookup)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CREATE TABLE IF NOT EXISTS inside init_db() — idempotent schema migration pattern (follows api_keys precedent from Phase 9)"
    - "ALTER TABLE users ADD COLUMN IF NOT EXISTS — safe column addition without backfill"
    - "Partial index WHERE used_at IS NULL — efficient active-token query pattern"

key-files:
  created: []
  modified:
    - burnlens_cloud/database.py

key-decisions:
  - "auth_tokens inserted after api_keys backfill INSERT and before plan_limits UPDATE blocks — preserves migration sequence integrity"
  - "email_verified_at NULL semantics: absence of timestamp means grandfathered-verified (no backfill required for existing users)"
  - "token_hash UNIQUE constraint enforces collision resistance at DB level; paired with secrets.token_urlsafe(32) in Plan 03"

patterns-established:
  - "Partial index pattern: CREATE INDEX IF NOT EXISTS ... WHERE used_at IS NULL for soft-delete style token invalidation"

requirements-completed: [AUTH-07]

# Metrics
duration: 5min
completed: "2026-05-02"
---

# Phase 11 Plan 01: Auth Tokens Schema Summary

**auth_tokens Postgres table with single-use token storage (password_reset/email_verification) and email_verified_at column on users — idempotent init_db() migrations following Phase 9 api_keys pattern**

## Performance

- **Duration:** 5 min
- **Started:** 2026-05-02T05:25:00Z
- **Completed:** 2026-05-02T05:30:38Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Added `auth_tokens` table to `init_db()` with all required constraints: UUID PK, user_id FK with ON DELETE CASCADE, type CHECK for password_reset/email_verification, token_hash UNIQUE, expires_at NOT NULL, used_at nullable for single-use tracking
- Added `idx_auth_tokens_user_active` partial index on `(user_id, type) WHERE used_at IS NULL` for efficient active-token lookups without scanning used/expired tokens
- Added `email_verified_at TIMESTAMPTZ` column to `users` via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` — NULL values for existing users are treated as grandfathered-verified (no backfill migration needed)

## Task Commits

1. **Task 1: Add auth_tokens table and email_verified_at column in init_db()** - `6ec71b0` (feat)

## Files Created/Modified

- `burnlens_cloud/database.py` - Added auth_tokens CREATE TABLE, idx_auth_tokens_user_active CREATE INDEX, and email_verified_at ALTER TABLE inside init_db()

## Decisions Made

None - followed plan as specified. DDL matches the exact spec in 11-CONTEXT.md §D-01 and plan acceptance criteria verbatim.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. Schema changes are applied automatically on next Railway deploy via `init_db()`.

## Next Phase Readiness

- `auth_tokens` table ready for Plan 03b's token insert/claim endpoints
- `email_verified_at` column ready for Plan 03a's `encode_jwt()` extension
- Both changes are fully idempotent — safe to deploy alongside Wave 1 Plan 02 (email.py) without coordination

## Known Stubs

None — this plan is purely DDL with no application logic.

## Threat Flags

None — DDL-only changes with no new network endpoints or request-handling surface.

## Self-Check: PASSED

- `burnlens_cloud/database.py` modified: FOUND
- Commit `6ec71b0` exists: FOUND
- `grep -c "CREATE TABLE IF NOT EXISTS auth_tokens"` = 1: PASSED
- `grep -c "idx_auth_tokens_user_active"` = 1: PASSED
- `python3 -c "import ast; ast.parse(...)"` = OK: PASSED

---
*Phase: 11-auth-essentials*
*Completed: 2026-05-02*
