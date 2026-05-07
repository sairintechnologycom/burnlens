---
phase: "15-hard-ingest-quota-enforcement"
plan: "00"
subsystem: "cloud-ingest"
tags: ["tdd", "quota", "wave-0", "red-state", "tests-only"]
dependency_graph:
  requires: []
  provides:
    - "tests/test_phase15_quota_hard.py — 16-test RED scaffold for QUOTA-01 through QUOTA-05"
  affects:
    - "burnlens_cloud/ingest.py — target module for Plan 01 implementation"
tech_stack:
  added: []
  patterns:
    - "Env isolation header (pydantic-settings dotenv shim) — verbatim from test_phase09_quota.py"
    - "AsyncMock dispatcher pattern for SQL branch coverage"
    - "Closure-based query side effects for per-test count/spend state"
key_files:
  created:
    - tests/test_phase15_quota_hard.py
  modified: []
decisions:
  - "16 tests instead of minimum 12 — parametrized TestQuota05AllDimensions expands to 4 test IDs; covers all quota dimensions cleanly"
  - "200-path tests also RED — patch target burnlens_cloud.ingest._check_quota_or_raise does not exist; tests fail because ingest returns 200 without calling any quota check (correct RED)"
  - "_make_resolved_limits helper uses try/except setattr for monthly_token_cap and monthly_spend_cap_usd — these are Plan 01 fields; forward-compatible without breaking Plan 00 collection"
metrics:
  duration: "3m"
  completed_date: "2026-05-07"
  tasks_completed: 1
  tasks_total: 1
  files_changed: 1
---

# Phase 15 Plan 00: Hard Ingest Quota Enforcement — TDD Wave 0 Scaffold Summary

**One-liner:** RED TDD scaffold with 16 test cases covering all four quota dimensions (requests, tokens, spend_usd, seats) plus 429 body shape validation — all tests fail correctly because `_check_quota_or_raise` does not exist yet.

## Tasks Completed

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 1 | Write RED test stubs for all 12+ quota cases | f1af9b6 | tests/test_phase15_quota_hard.py |

## TDD Gate Compliance

- RED gate: `test(15-00)` commit f1af9b6 confirms all 16 tests fail before implementation
- GREEN gate: pending (Plan 01 will implement `_check_quota_or_raise`)
- REFACTOR gate: pending (Plan 02)

## RED State Confirmation

```
pytest tests/test_phase15_quota_hard.py --collect-only
# 16 tests collected, 0 collection errors

pytest tests/test_phase15_quota_hard.py
# 16 failed — RED state confirmed
```

All 16 tests assert `status_code == 429` (for quota-block tests) or behavior that requires `_check_quota_or_raise` to exist. Since the function is not yet implemented in `burnlens_cloud/ingest.py`, all tests fail correctly.

## Test Structure

| Class | Methods | Requirement |
|-------|---------|-------------|
| TestQuota01HardBlock | test_at_cap_returns_429, test_over_cap_returns_429 | QUOTA-01 |
| TestQuota01AllowedBeforeCap | test_below_cap_returns_200 | QUOTA-01 |
| TestQuota01NullCapAllowed | test_null_cap_always_200 | QUOTA-01 |
| TestQuota02TokenBlock | test_at_token_cap_returns_429, test_null_token_cap_always_200 | QUOTA-02 |
| TestQuota03SpendBlock | test_at_spend_cap_returns_429, test_null_spend_cap_always_200 | QUOTA-03 |
| TestQuota04SeatBlock | test_member_count_above_seat_cap_returns_429, test_member_count_within_seat_cap_returns_200 | QUOTA-04 |
| TestQuota05ResponseBody | test_429_body_has_required_fields | QUOTA-05 |
| TestQuota05AllDimensions | test_all_dimensions_produce_correct_body[4 params] | QUOTA-05 |
| TestNoRecordsOnBlock | test_execute_bulk_insert_not_called_on_429 | QUOTA-01 through 04 |

## Deviations from Plan

None — plan executed exactly as written. The only minor detail: 16 tests collected (vs. the plan's "12+" minimum) because the parametrized `TestQuota05AllDimensions` expands to 4 test IDs.

## Known Stubs

None. This plan is test-only (Wave 0). No production code stubs were created.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. Test file only — no production code modified.

## Self-Check

Files created:
- [x] tests/test_phase15_quota_hard.py exists

Commits:
- [x] f1af9b6 — test(15-00): add RED TDD scaffold for hard quota enforcement

## Self-Check: PASSED
