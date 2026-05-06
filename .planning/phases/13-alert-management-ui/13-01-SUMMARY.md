---
phase: "13-alert-management-ui"
plan: "01"
subsystem: "burnlens_cloud"
tags: ["alerts", "api", "fastapi", "security", "idor-protection"]
dependency_graph:
  requires:
    - "13-00"  # alert_rules DB schema + test file created by Wave 0
  provides:
    - "alerts_api.py — GET + PATCH /api/v1/alert-rules endpoints"
    - "main.py — alerts_router mounted"
  affects:
    - "burnlens_cloud/main.py"
tech_stack:
  added: []
  patterns:
    - "Dynamic SET clause with positional params for partial PATCH updates"
    - "IDOR protection: WHERE id=$N AND workspace_id=$N+1 (workspace from JWT not request)"
    - "execute_insert result string parsing: int(result.split()[-1]) → row count"
key_files:
  created:
    - "burnlens_cloud/alerts_api.py"
  modified:
    - "burnlens_cloud/main.py"
decisions:
  - "slack_webhook_url exposed as boolean has_slack (IS NOT NULL) — raw URL never returned (T-13-01-02)"
  - "threshold_pct validation (only 80 or 100) enforced at application layer before any DB touch (T-13-01-05)"
  - "IDOR protection via AND workspace_id=$N in UPDATE WHERE clause — 0 rows → 404 not 200 (T-13-01-04)"
  - "extra_emails uses full-replace semantics — no email format validation (T-13-01-06 accepted risk)"
metrics:
  duration_minutes: 5
  completed_date: "2026-05-06"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 1
  tests_passed: 8
---

# Phase 13 Plan 01: Alert Rules API Summary

## One-Liner

FastAPI router exposing GET + PATCH /api/v1/alert-rules with workspace-scoped IDOR protection and slack_webhook_url information disclosure prevention.

## What Was Built

- `burnlens_cloud/alerts_api.py` — new FastAPI router with two endpoints:
  - `GET /api/v1/alert-rules` — viewer-accessible, workspace-scoped list; returns `has_slack` boolean instead of raw webhook URL
  - `PATCH /api/v1/alert-rules/{rule_id}` — owner-only partial update with dynamic SET clause; 422 on invalid threshold_pct, 404 on IDOR attempt
- `burnlens_cloud/main.py` — two-line addition: import `alerts_router` and `include_router(alerts_router)` adjacent to `cron_router`

## Security Properties Implemented

| Threat ID | Mitigation |
|-----------|------------|
| T-13-01-01 | `require_role("viewer", token)` on GET; 403 for unauthenticated |
| T-13-01-02 | `slack_webhook_url IS NOT NULL AS has_slack` — raw URL never in SELECT list |
| T-13-01-03 | `require_role("owner", token)` on PATCH; viewer gets 403 |
| T-13-01-04 | `WHERE id = $N AND workspace_id = $N+1` — cross-workspace UPDATE returns 0 rows → 404 |
| T-13-01-05 | `threshold_pct not in (80, 100)` raises 422 before any DB call |

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1: Create alerts_api.py | 57f2aed | feat(13-01): add alerts_api.py — GET + PATCH /api/v1/alert-rules |
| Task 2: Register alerts_router | 49e451e | feat(13-01): register alerts_router in main.py |

## Test Results

All 8 Wave 0 tests pass green:

```
tests/test_phase13_alerts_api.py::TestAlertRulesGet::test_list_alert_rules_200 PASSED
tests/test_phase13_alerts_api.py::TestAlertRulesGet::test_list_rules_viewer_allowed PASSED
tests/test_phase13_alerts_api.py::TestAlertRulesGet::test_list_rules_scoped_to_workspace PASSED
tests/test_phase13_alerts_api.py::TestAlertRulesPatch::test_patch_toggle_enabled PASSED
tests/test_phase13_alerts_api.py::TestAlertRulesPatch::test_patch_idor_protection PASSED
tests/test_phase13_alerts_api.py::TestAlertRulesPatch::test_patch_invalid_threshold PASSED
tests/test_phase13_alerts_api.py::TestAlertRulesPatch::test_patch_extra_emails PASSED
tests/test_phase13_alerts_api.py::TestAlertRulesPatch::test_patch_viewer_forbidden PASSED
8 passed in 0.38s
```

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — both endpoints are fully wired to real DB helpers (execute_query, execute_insert).

## Threat Flags

None — no new network surface beyond the two endpoints specified in the plan's threat model.

## Self-Check: PASSED

- `burnlens_cloud/alerts_api.py` exists: FOUND
- `grep -c "def list_alert_rules\|def patch_alert_rule" burnlens_cloud/alerts_api.py` = 2: PASSED
- `grep -c "slack_webhook_url IS NOT NULL" burnlens_cloud/alerts_api.py` = 1: PASSED
- `grep -c "slack_webhook_url" burnlens_cloud/alerts_api.py` = 1 (only in SELECT, not returned): PASSED
- `grep -c "AND workspace_id" burnlens_cloud/alerts_api.py` = 1: PASSED
- `grep -c "alerts_router" burnlens_cloud/main.py` = 2: PASSED
- Commit 57f2aed: FOUND
- Commit 49e451e: FOUND
- 8/8 tests pass: PASSED
