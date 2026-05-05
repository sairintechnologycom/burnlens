---
phase: 14
title: Budget-Aware Model Downgrade Routing
status: PASS
verified_at: "2026-05-05"
---

# Phase 14 Verification

## Phase Goal

Transparently downgrade expensive models to cheaper alternatives when a team or customer's
budget falls below configurable thresholds — with zero changes required by the user's
application code.

**Verdict: PASS — all 7 requirements met, 12/12 tests passing.**

---

## ROUTE-01 — Feature toggle + fail-open

- `burnlens/config.py`: `RoutingConfig(budget_downgrade=True, ...)` — toggle present, default enabled
- `burnlens/proxy/router.py` `decide_route()`: top-level `try/except` returns `RouteDecision(reason="error", downgraded=False)` on any exception — never raises
- Test 4 (`test_no_downgrade_when_feature_disabled`) and Test 8 (`test_decide_route_never_raises_on_db_error`) both PASS

**PASS**

## ROUTE-02 — Threshold-based downgrade trigger

- `_decide_route_inner()`: pct check runs first (`remaining_pct < downgrade_threshold_pct`), then USD check
- When both trigger, reason = `"budget_pct"` (D-03 decision honored)
- Defaults: 20% / $5.00
- Tests 1–3 cover pct trigger, USD trigger, and healthy budget pass-through — all PASS

**PASS**

## ROUTE-03 — Budget priority order

- `_resolve_budget()`: customer → team → global_usd → budget_limit_usd
- `CUSTOMER_SPEND_PATCH` targets `burnlens.storage.database.get_spend_by_customer_this_month`
- Tests 6 and 7 verify customer > team and team > global priorities — both PASS

**PASS**

## ROUTE-04 — Body rewrite before forwarding upstream

- `burnlens/proxy/interceptor.py`: after `decide_route()`, if `decision.downgraded`, body bytes are JSON-decoded, `model` field replaced with `decision.routed_model`, re-encoded
- Test 9 (`test_request_body_rewritten_with_routed_model`) validates the rewrite — PASS

**PASS**

## ROUTE-05 — Cost charged to routed model

- Interceptor sets `RequestRecord.model = decision.routed_model` when downgraded, so cost engine prices the cheaper model
- Test 10 (`test_cost_calculated_on_routed_model_not_original`) validates — PASS

**PASS**

## ROUTE-06 — /api/routing-stats endpoint

- `burnlens/dashboard/routes.py` line 494: `@router.get("/routing-stats")`
- Returns `downgrades_today` and `downgrades_this_month` from DB
- Dashboard `index.html` renders "Downgrades Today" KPI card; `app.js` fetches the endpoint
- Test 11 (`test_routing_stats_api_returns_correct_counts`) inserts 2 downgraded + 1 normal record, asserts `downgrades_today == 2` and `downgrades_this_month == 2` — PASS

**PASS**

## ROUTE-07 — DB persistence of routing metadata

- `burnlens/storage/database.py` `migrate_add_routing_columns()`: idempotent migration adds 4 columns
- `insert_request()`: binds `routed_model`, `downgrade_reason`, `budget_remaining_usd`, `budget_remaining_pct`
- Test 12 (`test_downgrade_reason_stored_in_db`) reads all 4 columns back from real SQLite — PASS

**PASS**

---

## Test gate

```
tests/test_router.py — 12 passed in 0.50s
Full suite — 1 pre-existing failure (test_api_phase3_validation.py), 192 passing
```

The pre-existing failure is unrelated to Phase 14.

---

## Zero-code-change invariant

The `decide_route()` call and body rewrite happen entirely inside `interceptor.py`. Users
set `BASE_URL` env vars and make normal SDK calls — the proxy handles model substitution
transparently. This satisfies the core BurnLens design principle.
