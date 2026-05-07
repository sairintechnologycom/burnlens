---
phase: 14-budget-aware-model-downgrade
plan: "03"
subsystem: proxy/routing
tags: [routing, budget, downgrade, async, caching]
dependency_graph:
  requires:
    - "14-01: RoutingConfig + DOWNGRADE_MAP"
    - "14-02: storage spend query functions"
  provides:
    - "burnlens.proxy.router.RouteDecision"
    - "burnlens.proxy.router.decide_route"
  affects:
    - "14-04: interceptor integration will import decide_route"
tech_stack:
  added: []
  patterns:
    - "60-second TTL module-level dict cache for team spend"
    - "Fail-open async wrapper: try/except around inner async fn"
    - "Deferred in-function imports to avoid circular dependencies"
    - "Budget priority chain: customer > team > global_usd > budget_limit_usd"
key_files:
  created:
    - burnlens/proxy/router.py
  modified: []
decisions:
  - "Used 6-field RouteDecision dataclass (original_model, routed_model, downgraded, reason, budget_remaining_usd, budget_remaining_pct) matching task acceptance criteria over the 4-field shorthand in plan summary section"
  - "decide_route() signature uses (model, tag_team, tag_customer, config, db_path) matching the verify block and interceptor integration pattern"
  - "pct threshold evaluated before usd threshold; when both trigger, reason=budget_pct per D-03"
  - "Customer spend: direct DB call (no local cache) per D-10 guidance — router path is low-frequency"
  - "Team spend: module-level _team_spend_cache with 60s TTL mirrors _customer_spend_cache in interceptor.py"
metrics:
  duration: "~20 minutes"
  completed: "2026-05-05T06:24:39Z"
  tasks_completed: 1
  tasks_total: 1
  files_created: 1
  files_modified: 0
---

# Phase 14 Plan 03: Router Logic Summary

**One-liner:** Async fail-open routing engine that resolves budget priority (customer > team > global) and returns a RouteDecision dataclass indicating whether to downgrade the model and to which alternative.

## What Was Built

Created `burnlens/proxy/router.py` (~240 lines) — the budget-aware model downgrade routing engine that centralises all budget lookup and downgrade decision logic, isolated from the proxy interceptor.

### Key Symbols Exported

| Symbol | Type | Description |
|--------|------|-------------|
| `RouteDecision` | dataclass | 6-field result of a routing decision |
| `decide_route()` | async fn | Public API — never raises, fail-open |
| `_decide_route_inner()` | async fn | Core logic, may raise; wrapped by decide_route |
| `_resolve_budget()` | async fn | Budget priority resolution: customer > team > global |
| `_get_team_spend()` | async fn | Team spend with 60s TTL cache |
| `_team_spend_cache` | dict | Module-level cache for team spend |

### RouteDecision Fields

```python
@dataclass
class RouteDecision:
    original_model: str        # model as received from caller
    routed_model: str          # model forwarded upstream (may differ when downgraded=True)
    downgraded: bool           # True iff a cheaper model was substituted
    reason: str                # "budget_pct" | "budget_usd" | "no_downgrade_needed" |
                               # "no_alternative" | "no_budget" | "disabled" | "error"
    budget_remaining_usd: float
    budget_remaining_pct: float
```

### Decision Flow

```
decide_route()
  └─ try/except wraps _decide_route_inner()
       ├─ config.routing.budget_downgrade == False → reason="disabled"
       ├─ _resolve_budget() → (limit, spent)
       │    ├─ tag_customer + customer budget configured → get_spend_by_customer_this_month()
       │    ├─ tag_team + team budget configured → _get_team_spend() [cached 60s]
       │    └─ global_usd or budget_limit_usd → sum of all team spend
       ├─ limit is None → reason="no_budget"
       ├─ remaining_pct < threshold_pct → trigger_reason="budget_pct"
       ├─ remaining_usd < threshold_usd → trigger_reason="budget_usd"
       ├─ above both thresholds → reason="no_downgrade_needed"
       ├─ get_downgrade_model(model) → None → reason="no_alternative"
       └─ cheaper model found → downgraded=True, routed_model=cheaper
  └─ except Exception → reason="error", routed_model=original_model (fail-open)
```

## Verification Results

```
router.py structure OK
params: ['model', 'tag_team', 'tag_customer', 'config', 'db_path']
RouteDecision fields: ['original_model', 'routed_model', 'downgraded', 'reason', 'budget_remaining_usd', 'budget_remaining_pct']

grep -c "class RouteDecision" → 1
grep -c "async def decide_route" → 1
grep -c "async def _decide_route_inner" → 1
grep -c "async def _resolve_budget" → 1
grep -c "async def _get_team_spend" → 1
grep -c "_team_spend_cache" → 3 (declaration, read, write)
grep -c "try:" → 1 (fail-open wrapper)
```

## Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create router.py with RouteDecision + decide_route() | 6f6e1bd | burnlens/proxy/router.py |

## Deviations from Plan

None — plan executed exactly as specified. The 6-field RouteDecision form was the task body's definitive spec; the plan summary's 4-field shorthand was treated as illustrative only.

## Threat Surface Scan

No new network endpoints, auth paths, or file access patterns introduced. `router.py` reads from SQLite via existing `get_spend_by_*` functions. No new threat surface beyond what the plan's threat model already registers (T-14-03-01, T-14-03-02, T-14-03-03).

## Self-Check: PASSED

- [x] burnlens/proxy/router.py created and verified present
- [x] Commit 6f6e1bd verified in git log
- [x] No unexpected file deletions
- [x] Import `from burnlens.proxy.router import RouteDecision, decide_route` confirmed working
- [x] All 5 acceptance criteria grep checks pass
