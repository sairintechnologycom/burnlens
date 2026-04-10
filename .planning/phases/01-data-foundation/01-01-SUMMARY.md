---
phase: 01-data-foundation
plan: 01
subsystem: database
tags: [sqlite, aiosqlite, dataclasses, python, triggers, indexes, seed-data]

# Dependency graph
requires: []
provides:
  - AiAsset dataclass (burnlens/storage/models.py)
  - ProviderSignature dataclass (burnlens/storage/models.py)
  - DiscoveryEvent dataclass (burnlens/storage/models.py)
  - ai_assets SQLite table with CHECK constraints and indexes
  - provider_signatures SQLite table seeded with 7 providers
  - discovery_events SQLite table with append-only triggers
affects: [02-detection-engine, 03-api-layer, 04-alerts, 05-dashboard]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - SQLite CHECK constraints for enum validation (status, risk_tier, event_type)
    - BEFORE UPDATE/DELETE triggers for append-only audit log
    - INSERT OR IGNORE with UNIQUE constraint for idempotent seed data
    - INTEGER autoincrement PKs (not UUIDs) for consistency with existing requests table
    - ISO timestamp TEXT columns matching existing requests table convention

key-files:
  created: []
  modified:
    - burnlens/storage/models.py
    - burnlens/storage/database.py
    - tests/test_storage.py

key-decisions:
  - "SQLite RAISE(ABORT) triggers raise IntegrityError (not OperationalError) via aiosqlite — tests use IntegrityError"
  - "Plain TEXT for owner_team and project (no FK) per CONTEXT.md — simple strings like 'ML Platform'"
  - "Every ai_asset starts as status=shadow and risk_tier=unclassified by default"
  - "INSERT OR IGNORE with UNIQUE constraint on provider column ensures idempotent seeding"

patterns-established:
  - "Append-only audit log via BEFORE UPDATE/DELETE triggers with RAISE(ABORT)"
  - "CHECK constraints on enum-valued TEXT columns for data integrity"
  - "Phase-grouped test sections marked with # --- Phase N: Name --- comments"

requirements-completed: [DATA-01, DATA-02, DATA-03, DATA-04]

# Metrics
duration: 3min
completed: 2026-04-10
---

# Phase 1 Plan 1: Data Foundation — Schema & Models Summary

**Three new SQLite tables (ai_assets, provider_signatures, discovery_events) with append-only triggers, CHECK constraints, 7 seeded providers, and matching Python dataclasses**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-04-10T12:15:46Z
- **Completed:** 2026-04-10T12:18:23Z
- **Tasks:** 2 (1 direct, 1 TDD)
- **Files modified:** 3

## Accomplishments
- Added AiAsset, ProviderSignature, and DiscoveryEvent dataclasses following existing RequestRecord conventions
- Extended init_db() with 3 new tables, 6 indexes, 2 append-only triggers, and 7 seeded provider signatures
- All 46 tests pass (29 existing + 17 new) with zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Add AiAsset, ProviderSignature, DiscoveryEvent dataclasses** - `2579644` (feat)
2. **Task 2 RED: Failing tests for new tables** - `a6e9a2c` (test)
3. **Task 2 GREEN: Extend init_db with tables, triggers, indexes, seed data** - `39286a7` (feat)

_Note: TDD task produced two commits (test RED → feat GREEN)_

## Files Created/Modified
- `burnlens/storage/models.py` — Three new dataclasses: AiAsset, ProviderSignature, DiscoveryEvent
- `burnlens/storage/database.py` — New SQL constants, extended init_db() with Phase 1 tables
- `tests/test_storage.py` — 17 new tests for Phase 1 schema (phase-grouped section)

## Decisions Made
- SQLite RAISE(ABORT) triggers raise IntegrityError (not OperationalError) via aiosqlite — tests corrected to match actual behavior
- Followed existing pattern: TEXT for timestamps (ISO format), JSON-encoded TEXT for dict fields
- INSERT OR IGNORE with UNIQUE constraint chosen for idempotent seed data (not ON CONFLICT DO NOTHING — same semantics, cleaner syntax)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Trigger exception type mismatch in tests**
- **Found during:** Task 2 (discovery_events trigger tests)
- **Issue:** Tests expected `aiosqlite.OperationalError` but SQLite's `RAISE(ABORT, ...)` in triggers raises `IntegrityError` via aiosqlite
- **Fix:** Changed `pytest.raises(aiosqlite.OperationalError)` to `pytest.raises(aiosqlite.IntegrityError)` in both trigger tests
- **Files modified:** tests/test_storage.py
- **Verification:** Both trigger tests now pass
- **Committed in:** `39286a7` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug)
**Impact on plan:** Trivial correction to test assertion type. Implementation behavior is correct; tests now accurately assert actual SQLite behavior.

## Issues Encountered
None beyond the auto-fixed trigger exception type above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All three tables ready for Phase 2 (Detection Engine) to write ai_assets and discovery_events rows
- provider_signatures seeded and queryable for endpoint pattern matching
- DiscoveryEvent append-only constraint enforced at DB level — Phase 2 can write events, never modify
- Phase 3 (API Layer) can begin in parallel — tables and models are ready for CRUD endpoints

---
*Phase: 01-data-foundation*
*Completed: 2026-04-10*

## Self-Check: PASSED

- models.py: FOUND
- database.py: FOUND
- test_storage.py: FOUND
- SUMMARY.md: FOUND
- Commit 2579644 (feat: dataclasses): FOUND
- Commit a6e9a2c (test: failing tests): FOUND
- Commit 39286a7 (feat: init_db extended): FOUND
