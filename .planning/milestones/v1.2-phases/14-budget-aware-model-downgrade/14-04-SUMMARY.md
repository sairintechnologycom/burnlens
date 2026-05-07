---
plan: 14-04
phase: 14-budget-aware-model-downgrade
status: complete
tasks_completed: 2
commits:
  - cdc2d49: "feat(14-04): extend handle_request() with routing in interceptor.py"
  - 8248a66: "feat(14-04): wire config through server.py to handle_request()"
subsystem: proxy/interceptor
tags: [routing, downgrade, budget-aware, proxy]
dependency-graph:
  requires: [14-02, 14-03]
  provides: [ROUTE-04]
  affects: [burnlens/proxy/interceptor.py, burnlens/proxy/server.py]
tech-stack:
  added: []
  patterns: [fail-open body rewrite, TYPE_CHECKING deferred import, async decide_route call]
key-files:
  created: []
  modified:
    - burnlens/proxy/interceptor.py
    - burnlens/proxy/server.py
decisions:
  - "Google URL-path model routing deferred to v2 — body rewrite has no effect for Google; documented with comment per spec/14-CONTEXT.md"
  - "config param added as last keyword arg (after api_key_budgets) with None default to preserve backward compatibility"
metrics:
  duration: "~15 minutes"
  completed: "2026-05-05"
---

# Phase 14 Plan 04: Interceptor Routing Integration Summary

## What Was Built

Wired the budget-aware routing engine into the live proxy request path by extending `handle_request()` with a `config: BurnLensConfig | None = None` parameter and inserting a `decide_route()` call that fires after tag/model extraction but before customer budget enforcement. When a downgrade decision is made, the request body is rewritten with the cheaper model name (fail-open with try/except), the `model` variable is updated, and all four routing fields (`routed_model`, `downgrade_reason`, `budget_remaining_usd`, `budget_remaining_pct`) are persisted on `RequestRecord` in both streaming and non-streaming paths. `server.py` passes the full `BurnLensConfig` instance via `config=_config` to every `handle_request()` call site.

## Key Files Changed

- `burnlens/proxy/interceptor.py` — added `config` param to `handle_request()`; inserted `decide_route()` call with body rewrite on downgrade; set routing fields on `RequestRecord` in both `_handle_non_streaming()` and `_log_streaming_usage()`; added TYPE_CHECKING imports for `BurnLensConfig` and `RouteDecision`; documented Google URL-path limitation in a code comment
- `burnlens/proxy/server.py` — added `config=_config` keyword argument to the single `handle_request()` call site in `proxy_handler()`

## Must-Have Verification

- [x] `handle_request()` accepts `config: BurnLensConfig | None = None` parameter
- [x] When config is provided, `decide_route()` is called after tag extraction and before customer budget check
- [x] When `decision.downgraded` is True, `body_bytes` is rewritten with routed model name (fail-open)
- [x] `model` variable is updated to `decision.routed_model` after rewrite
- [x] `logger.info` line is emitted when downgrade occurs and `config.routing.log_downgrades` is True
- [x] `record.routed_model = decision.routed_model` (always set, even when not downgraded)
- [x] `record.downgrade_reason = decision.reason` when downgraded, else None
- [x] `record.budget_remaining_usd = decision.budget_remaining_usd` when downgraded, else None
- [x] `record.budget_remaining_pct = decision.budget_remaining_pct` when downgraded, else None
- [x] If `config` is None, routing is skipped and existing behavior is unchanged
- [x] `server.py` passes the full config object to `handle_request()`
- [x] Google URL-path routing limitation is documented in a comment in `interceptor.py`

## Deviations from Plan

None — plan executed exactly as written. Task 1 was cherry-picked from the parallel worktree branch where it was originally committed.

## Known Stubs

None.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes introduced beyond what the plan's threat model covers (T-14-04-01 through T-14-04-03 all addressed: body rewrite is fail-open, routing fields are persisted as audit trail).

## Self-Check: PASSED

- `burnlens/proxy/interceptor.py` modified: confirmed (commit cdc2d49)
- `burnlens/proxy/server.py` modified: confirmed (commit 8248a66)
- Commits present: `git log --oneline | grep 14-04` shows both hashes
- 54 proxy tests pass: `pytest tests/test_proxy.py -q` → 54 passed, 4 warnings
- `grep -n "decide_route" interceptor.py` → lines 440-441
- `grep -n "config=" server.py` → line 160 (within handle_request() call)
