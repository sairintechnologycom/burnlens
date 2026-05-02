---
phase: 12
plan: "03"
subsystem: burnlens_cloud
tags: [cron, alerts, slack, settings, tests]
dependency_graph:
  requires: ["12-01", "12-02"]
  provides: ["cron-endpoint", "slack-webhook-settings", "phase-12-test-suite"]
  affects: ["burnlens_cloud/main.py", "burnlens_cloud/config.py"]
tech_stack:
  added: ["fastapi.security.HTTPBearer", "secrets.compare_digest"]
  patterns: ["fail-open cron", "SSRF guard on webhook URL", "bearer secret auth"]
key_files:
  created:
    - burnlens_cloud/cron_api.py
    - tests/test_phase12_alerts.py
  modified:
    - burnlens_cloud/config.py
    - burnlens_cloud/main.py
    - burnlens_cloud/settings_api.py
decisions:
  - "Used secrets.compare_digest for constant-time cron secret comparison (timing-safe)"
  - "Cron endpoint fail-open: unhandled exceptions from evaluate_all_workspaces return {evaluated:0, fired:0}"
  - "Test cron endpoint with minimal FastAPI app (no lifespan) to avoid DB dependency in unit tests"
  - "SSRF guard on Slack webhook: rejects any URL not starting with https://hooks.slack.com/"
metrics:
  duration: "~8 minutes"
  completed: "2026-05-02"
  tasks_completed: 3
  files_created: 2
  files_modified: 3
---

# Phase 12 Plan 03: Wire Phase 12 Summary

**One-liner:** Railway cron endpoint (CRON_SECRET bearer auth) + Slack webhook settings endpoint wired into main.py with 13-test suite covering SSRF guard, dedup, fail-open, and 401/200 auth flows.

## Tasks Completed

| Task | Description | Status |
|------|-------------|--------|
| 1A | Add `cron_secret` to `Settings` in config.py | Done |
| 1B | Create `burnlens_cloud/cron_api.py` | Done |
| 2A | Append `PUT /settings/slack-webhook` to settings_api.py | Done |
| 2B | Mount `cron_router` in main.py | Done |
| 3  | Write `tests/test_phase12_alerts.py` (13 tests) | Done |

## Files Modified

- **burnlens_cloud/config.py** — Added `cron_secret: str = os.getenv("CRON_SECRET", "")` after `sendgrid_api_key`
- **burnlens_cloud/cron_api.py** (created) — `POST /cron/evaluate-alerts` with `HTTPBearer` + `secrets.compare_digest`, fail-open wrapper around `evaluate_all_workspaces`
- **burnlens_cloud/settings_api.py** — Added `from pydantic import BaseModel` import + `SlackWebhookRequest` model + `PUT /settings/slack-webhook` endpoint (owner-only, SSRF-guarded, updates `alert_rules`)
- **burnlens_cloud/main.py** — Added `from .cron_api import router as cron_router` import and `app.include_router(cron_router)` call
- **tests/test_phase12_alerts.py** (created) — 13 tests

## Test Results

```
13 passed, 1 warning in 0.36s
```

All 13 tests pass. Tests cover:
- `_should_fire`: returns True (no prior alert row) and False (dedup row found)
- `_dispatch_slack`: SSRF guard rejects non-hooks.slack.com URLs and empty URLs; success path verifies "80%" in payload; HTTP error returns False
- `evaluate_workspace`: fires and records alert on threshold; skips on dedup; returns [] on exception (fail-open)
- `evaluate_all_workspaces`: returns `{evaluated:0, fired:0}` when no non-free workspaces
- Cron endpoint: 401 with no header, 401 with wrong secret, 200 with correct secret + correct JSON response

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Cron endpoint tests used full app with lifespan — triggered real DB connection**
- **Found during:** Task 3 test run
- **Issue:** Original test helper called `burnlens_cloud.main.app` (the module-level singleton with full lifespan), which ran `init_db()` and tried to connect to a Postgres DB that does not exist in the test environment
- **Fix:** Replaced `_make_app_with_mock_pool()` (which imported the full app) with `_make_cron_app()` which builds a minimal `FastAPI()` instance with only `cron_router` mounted — same pattern as `test_phase11_auth.py`'s `_make_app(*routers)` helper
- **Files modified:** `tests/test_phase12_alerts.py`
- **Commit:** c9e2a52

## Commit

`c9e2a52` — `feat(phase-12): add cron endpoint, slack-webhook settings, tests — wire Phase 12 (Plan 03)`

## Self-Check: PASSED

- `burnlens_cloud/cron_api.py`: FOUND
- `tests/test_phase12_alerts.py`: FOUND
- Commit `c9e2a52`: FOUND
- All 13 tests: PASSED
