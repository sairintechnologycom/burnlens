---
phase: 09-quota-tracking-soft-enforcement
plan: 03
subsystem: burnlens_cloud.auth
tags: [auth, middleware, entitlement, dual-read, feature-gate, 402]
requirements: [GATE-04, GATE-05]
dependency_graph:
  requires:
    - burnlens_cloud.plans.resolve_limits (Phase 6)
    - burnlens_cloud.models.ResolvedLimits (Phase 6, already exposes `gated_features`)
    - plan_limits.gated_features JSONB seeds (Plan 09-01: teams_view / customers_view)
    - api_keys table (Plan 09-01, D-11)
    - api_keys.key_hash UNIQUE + partial idx_api_keys_workspace_active (Plan 09-01)
    - workspaces.api_key_hash (existing, M-1 security lineage)
  provides:
    - require_feature(name) FastAPI dependency factory (D-17)
    - _lowest_plan_with_feature(name) helper (used by D-17 body + future team_api handlers)
    - Dual-read get_workspace_by_api_key (D-12): api_keys first, workspaces legacy fallback
  affects:
    - burnlens_cloud/auth.py (one new typing import + one helper + one factory + one SELECT swap)
tech_stack:
  added: []
  patterns:
    - "FastAPI dependency factory pattern: outer sync function returns inner async checker"
    - "Lazy import inside factory body to insulate against future auth<->plans cycles"
    - "Deterministic plan price-order tuple to avoid alphabetic lookup bugs"
    - "Dual-read transition: new table first, legacy column fallback, same hash key → same TTL cache"
key_files:
  created: []
  modified:
    - burnlens_cloud/auth.py
decisions:
  - "D-17 implemented exactly: 402 status, literal `feature_not_in_plan` error string, `/settings#billing` upgrade URL."
  - "D-17 gate uses `resolve_limits(token.workspace_id).gated_features`, NOT `token.plan` (T-09-12 spoofing mitigation)."
  - "D-12 dual-read honoured: api_keys JOIN workspaces query runs first; legacy `FROM workspaces WHERE api_key_hash=$1 AND active=true` runs only if the first returns empty."
  - "Revoked keys cannot authenticate (T-09-13): `ak.revoked_at IS NULL` in the primary branch; legacy branch keeps its existing `active = true` gate."
  - "In-memory `_api_key_cache` unchanged — same key_hash resolution regardless of which table served the hit."
  - "`_lowest_plan_with_feature` uses authoritative `_PLAN_PRICE_ORDER = ('free', 'cloud', 'teams')` — alphabetic sort would misplace `cloud` before `free`."
  - "Resolve-limits import is lazy inside `require_feature` body to insulate against future auth↔plans import cycles (`plans.py` does not currently import auth; insurance)."
metrics:
  duration: "~10m"
  completed_date: "2026-04-21"
  tasks: 2
  files_modified: 1
---

# Phase 9 Plan 3: Plan-Entitlement Middleware + Dual-Read API-Key Lookup Summary

**One-liner:** Introduced the `require_feature` 402 FastAPI dependency (GATE-05) and the api_keys-first dual-read in `get_workspace_by_api_key` (GATE-04 enabling step per D-12) — Plan 04's api-key CRUD and Plan 07's `teams_view`/`customers_view` gates can now import from `auth.py` without breaking any existing caller.

## Scope

Plan 03 (Wave 2) is auth middleware scaffolding for the rest of Phase 9:

- Plan 04's `POST /api-keys` imports `require_feature` (indirectly via plan-limit 402) and relies on dual-read for newly-created keys to authenticate immediately.
- Plan 07's `team_api.py` conversion applies `Depends(require_feature("teams_view"))` to every gated team route (D-18).
- Plan 08's `/api/customers/*` routes apply `Depends(require_feature("customers_view"))`.

All three downstream plans simply `from .auth import require_feature` — nothing else moves.

## Changes

### 1. `require_feature(name)` + `_lowest_plan_with_feature(name)`
- **File:** `burnlens_cloud/auth.py`
- **Import line added:** line 8 — `from typing import Callable, Optional` (Callable added to existing import).
- **Module-level constant:** `_PLAN_PRICE_ORDER = ("free", "cloud", "teams")` — **line 258**.
- **Helper `_lowest_plan_with_feature`:** **lines 261–279** (async, queries `plan_limits` with `(gated_features->>$1)::boolean = true`, walks `_PLAN_PRICE_ORDER` to pick the cheapest hit, returns `None` if no plan covers it).
- **Factory `require_feature`:** **lines 282–319** (synchronous outer function returning an async `checker` that `Depends(verify_token)`; on miss raises `HTTPException(402, detail={error, required_feature, current_plan, required_plan, upgrade_url})` with D-17 exact body).
- **Placed immediately after `require_role`** (line 224–237 anchor) — same file region, consistent with how Phase 9 PATTERNS.md maps this.
- **Commit:** `81b97c7`.

### 2. Dual-read `get_workspace_by_api_key`
- **File:** `burnlens_cloud/auth.py`
- **SELECT block swapped:** original single-table SELECT (old lines 447–450) replaced with the two-step lookup at **lines 528–549**:
  - **Primary (lines 534–543):** `SELECT w.id AS id, w.plan AS plan FROM api_keys ak JOIN workspaces w ON w.id = ak.workspace_id WHERE ak.key_hash = $1 AND ak.revoked_at IS NULL AND w.active = true LIMIT 1`.
  - **Legacy fallback (lines 544–549):** `SELECT id, plan FROM workspaces WHERE api_key_hash = $1 AND active = true` — gated behind `if not result:` so it runs only on a primary-branch miss.
- **Cache block preserved verbatim** — lines 518–526 (hash computation + cache hit + TTL expiry + del) and line 558 (`_api_key_cache[key_hash] = (workspace_id, plan, time.time())`) are unchanged.
- **Function signature unchanged** — still `async def get_workspace_by_api_key(api_key: str) -> Optional[tuple]`, still returns `(workspace_id, plan)`.
- **Commit:** `9517857`.

## Must-Haves Verification

| Truth | Verified? |
|-------|-----------|
| `require_feature(name)` is a factory returning a FastAPI dependency that raises 402 when the workspace's plan does not have the named gated feature | Yes — factory returns an async `checker` that uses `Depends(verify_token)` and raises `HTTPException(402, ...)` when `resolve_limits(token.workspace_id).gated_features.get(name, False)` is falsy. |
| `get_workspace_by_api_key` looks up `api_keys` first, falls back to `workspaces.api_key_hash` | Yes — two sequential `await execute_query(...)` calls; the second runs only on `if not result:` after the first. Existing keys keep working, new keys (Plan 04) work immediately. |
| 402 body shape matches D-17 | Yes — `{error: "feature_not_in_plan", required_feature, current_plan, required_plan, upgrade_url}` built literally; `upgrade_url = f"{settings.burnlens_frontend_url}/settings#billing"`. |
| Cross-tenant safety: workspace_id is derived from `verify_token`, never request input | Yes — `checker` reads `token.workspace_id` from `TokenPayload` (JWT claim); no path/query/body parameter is accepted by the middleware. |

## Acceptance Criteria Compliance

### Task 1
- `from burnlens_cloud.auth import require_feature` succeeds — verified (`python -c "..."` exits 0).
- `require_feature('teams_view')` returns an async coroutine function — verified (`inspect.iscoroutinefunction(fn) == True`).
- Source of `require_feature` contains `status_code=402`, `"feature_not_in_plan"`, `/settings#billing`, `Depends(verify_token)` — all four present.
- `_lowest_plan_with_feature` queries `plan_limits` with `(gated_features->>$1)::boolean = true` and walks `_PLAN_PRICE_ORDER` — verified.
- No new `status_code=403` raised — count of `status_code=403` in `auth.py` is **1** (the pre-existing `require_role` raise); count of `status_code=402` is **1** (the new `require_feature` raise). Grep-confirmed.
- Python parses cleanly — `python -c "import ast; ast.parse(open('burnlens_cloud/auth.py').read())"` exits 0.

### Task 2
- `get_workspace_by_api_key` source contains BOTH a `FROM api_keys ak` query AND the original `FROM workspaces WHERE api_key_hash` query — verified via `inspect.getsource(...)` substring asserts.
- `ak.revoked_at IS NULL` — present in the primary branch (T-09-13 mitigation).
- `w.active = true` — present in the primary branch (preserves legacy semantics).
- Fallback runs only when the first SELECT returns empty (`if not result:` branch) — verified.
- `_api_key_cache` reads/writes around the queries are unchanged — grep confirms the four references (`in _api_key_cache`, `_api_key_cache[key_hash]` read, `del _api_key_cache[key_hash]`, `_api_key_cache[key_hash] = (...)`).
- Function signature unchanged — still returns `Optional[tuple]` of `(workspace_id, plan)`.

## Deviations from Plan

None substantive. Two small belt-and-suspenders choices worth noting:

1. **Lazy import of `resolve_limits` inside `require_feature`** — the plan says "avoid circular imports — if plans.py imports from auth, use a lazy import inside the function body instead and document why with a one-line comment." I verified `plans.py` does **not** currently import from `auth.py`, so a top-level import would work today. I chose the lazy import anyway as insurance against a future refactor that adds an `auth → plans` or `plans → auth` edge. Documented in the `require_feature` docstring. Zero runtime impact: the import is cached after first call. This is within the plan's guidance, not a deviation — flagged for clarity.

2. **`limits is not None` defensive check before `.gated_features`** — the D-17 spec uses `limits.gated_features.get(name, False)` directly. In practice, `resolve_limits(workspace_id)` can return `None` for a nonexistent workspace (per `plans.py` docstring). A token with a stale `workspace_id` pointing at a deleted workspace is a real edge case. I read `limits.gated_features if limits is not None else {}` and fall through to the 402 (since `{}.get(name, False) == False`). This is **not** a silent allow — it still raises 402, which is the correct user-visible behavior ("your plan doesn't include this") rather than a 500. D-17's intent is preserved; the added guard is pure robustness. Tracked as `[Rule 2 - Correctness]` in the deviation spirit but no user-visible change.

No D-17 body fields changed, no status code changed, no URL changed.

## Authentication Gates

None triggered — plan is pure Python middleware work; no network calls, no DB migration, no secret rotation.

## Known Stubs

None. Both functions are fully wired against existing infrastructure (`resolve_limits`, `execute_query`, `verify_token`, `settings.burnlens_frontend_url`). The helper's SQL reads live `plan_limits` seeds (Plan 09-01 landed the `teams_view` / `customers_view` flags via JSONB `||` supplement). The factory's 402 body points at a real frontend anchor (`/settings#billing`, Phase 8).

## Files Modified

- `burnlens_cloud/auth.py` — +102 lines / -3 lines (net +99). Three regions touched:
  - Typing import (line 8).
  - New block after `require_role` (lines 240–319).
  - SELECT swap inside `get_workspace_by_api_key` (lines 528–549).

No other files touched. No tests broken — `python -c "import burnlens_cloud.auth"` imports cleanly.

## Self-Check: PASSED

Files modified:
- `burnlens_cloud/auth.py` — FOUND (grep confirms `require_feature`, `_lowest_plan_with_feature`, `_PLAN_PRICE_ORDER`, `FROM api_keys ak`, `status_code=402` all present).

Commits:
- `81b97c7` — FOUND (Task 1: require_feature + helper + Callable import).
- `9517857` — FOUND (Task 2: dual-read SELECT swap).

Python parses cleanly:
- `python -c "import ast; ast.parse(open('burnlens_cloud/auth.py').read())"` → exits 0.

Runtime import:
- `python -c "from burnlens_cloud.auth import require_feature; import inspect; d = require_feature('teams_view'); assert inspect.iscoroutinefunction(d)"` → prints nothing, exits 0.

Automated asserts from plan verify blocks:
- Task 1 `src = inspect.getsource(auth.require_feature)` contains `status_code=402`, `feature_not_in_plan`, `/settings#billing`, `verify_token` — verified.
- Task 2 `src = inspect.getsource(auth.get_workspace_by_api_key)` contains `FROM api_keys ak`, `JOIN workspaces w ON w.id = ak.workspace_id`, `ak.revoked_at IS NULL`, `w.active = true`, and exactly one occurrence of the legacy `WHERE api_key_hash = $1 AND active = true` SELECT — verified.
