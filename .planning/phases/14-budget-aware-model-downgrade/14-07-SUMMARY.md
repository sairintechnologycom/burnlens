---
plan: 14-07
title: "Router Test Suite"
status: complete
completed_at: "2026-05-05"
---

# Plan 07 — Router Test Suite: Summary

## What was built

`tests/test_router.py` — 12 pytest tests covering all ROUTE requirements for the
budget-aware model downgrade routing system.

## Deliverables

| File | Change |
|------|--------|
| `tests/test_router.py` | Created — 12 test functions, 313 lines |

## Test coverage

| # | Test | Covers |
|---|------|--------|
| 1 | `test_downgrade_triggers_at_threshold_pct` | ROUTE-02 — pct trigger, `budget_pct` reason |
| 2 | `test_downgrade_triggers_at_threshold_usd` | ROUTE-02 — USD trigger, `budget_usd` reason |
| 3 | `test_no_downgrade_when_budget_healthy` | ROUTE-02 — healthy budget pass-through |
| 4 | `test_no_downgrade_when_feature_disabled` | ROUTE-01 — `budget_downgrade=False` guard |
| 5 | `test_no_alternative_model_passes_through_without_block` | ROUTE-01 — no DOWNGRADE_MAP entry |
| 6 | `test_customer_budget_takes_priority_over_team` | ROUTE-03 — priority: customer > team |
| 7 | `test_team_budget_takes_priority_over_global` | ROUTE-03 — priority: team > global |
| 8 | `test_decide_route_never_raises_on_db_error` | ROUTE-01 — fail-open on exception |
| 9 | `test_request_body_rewritten_with_routed_model` | ROUTE-04 — body rewrite logic |
| 10 | `test_cost_calculated_on_routed_model_not_original` | ROUTE-05 — cost on routed model |
| 11 | `test_routing_stats_api_returns_correct_counts` | ROUTE-06 — /api/routing-stats counts |
| 12 | `test_downgrade_reason_stored_in_db` | ROUTE-07 — DB persistence of all 4 columns |

## Key design decisions

- **autouse cache-clearing fixture** — clears `_team_spend_cache` before/after each test
  to prevent 60-second TTL bleed between tests during fast test runs
- **Mock targets** — patch `burnlens.storage.database.*` (where the functions are
  defined), not `burnlens.proxy.router.*` (where they're imported via deferred import)
- **Tests 9/10 simplified** — avoid full `handle_request()` mock chain; test
  `decide_route()` directly then simulate the interceptor body rewrite step
- **Tests 11/12 use tmp_path** — real SQLite DB with `asyncio.run()` for sync test 11,
  native `pytest.mark.asyncio` for test 12

## Result

12/12 tests pass. Committed: 6d52ff4
