---
phase: 13-alert-management-ui
plan: "00"
subsystem: testing
tags: [pytest, fastapi, httpx, asyncio, tdd, alerts-api]

# Dependency graph
requires:
  - phase: 12-cloud-alert-engine
    provides: alert_engine, alert_rules schema, execute_query/execute_insert DB helpers
provides:
  - 8 failing pytest stubs specifying GET /api/v1/alert-rules and PATCH /api/v1/alert-rules/{id} behaviour
  - _make_alerts_app() factory pattern for isolated FastAPI testing
  - RED state: ModuleNotFoundError confirms alerts_api.py not yet written
affects:
  - 13-01-PLAN (implementation plan must satisfy all 8 test cases)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_make_alerts_app() factory: mounts only the router under test, no lifespan/DB"
    - "dependency_overrides[_verify_token] for auth isolation in unit tests"
    - "patch('burnlens_cloud.alerts_api.execute_query/execute_insert') for DB mocking"

key-files:
  created:
    - tests/test_phase13_alerts_api.py
  modified: []

key-decisions:
  - "Test-only plan (wave 0) isolates RED state from GREEN — prevents false-green tests by writing tests and code together"
  - "viewer role allowed for GET /api/v1/alert-rules, forbidden for PATCH (role-based access control specification)"
  - "IDOR protection: UPDATE 0 rows => 404 rule_not_found (workspace_id scoping enforced at DB level)"
  - "threshold_pct=50 triggers 422 with execute_insert not called (validation must happen before DB)"

patterns-established:
  - "_make_alerts_app pattern: exact analog of _make_cron_app from test_phase12_alerts.py"
  - "Mock target strings: 'burnlens_cloud.alerts_api.execute_query' and 'burnlens_cloud.alerts_api.execute_insert'"

requirements-completed:
  - ALERT-08
  - ALERT-09

# Metrics
duration: 5min
completed: 2026-05-06
---

# Phase 13 Plan 00: Alert Management UI — Test Scaffold Summary

**8 async pytest stubs (RED) specifying GET /api/v1/alert-rules + PATCH /{id} with workspace-scoped IDOR protection and role-based access control**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-05-06T00:02:00Z
- **Completed:** 2026-05-06T00:07:29Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Created `tests/test_phase13_alerts_api.py` with 8 async test stubs in RED state
- Tests fail with `ModuleNotFoundError: No module named 'burnlens_cloud.alerts_api'` as expected
- Fully specifies behaviour of GET (list, viewer-allowed, workspace-scoped) and PATCH (toggle, IDOR, invalid-threshold, extra-emails, viewer-forbidden) endpoints
- Established `_make_alerts_app()` factory and `_auth()` helper patterns matching the project's existing test conventions

## Task Commits

1. **Task 1: Write failing test stubs for alerts_api.py (RED state)** - `8156c0b` (test)

**Plan metadata:** _(docs commit to follow)_

## Files Created/Modified
- `tests/test_phase13_alerts_api.py` - 8 async test stubs covering all ALERT-08 and ALERT-09 cases; fails with ImportError (RED state)

## Decisions Made
- Followed plan exactly as written — no deviations

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- RED state established; Plan 01 can now implement `burnlens_cloud/alerts_api.py` to drive tests GREEN
- All 8 test names and behaviours are precisely specified; no ambiguity for the implementation agent

---
*Phase: 13-alert-management-ui*
*Completed: 2026-05-06*
