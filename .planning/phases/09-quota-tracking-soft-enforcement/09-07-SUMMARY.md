---
phase: 09-quota-tracking-soft-enforcement
plan: 07
subsystem: burnlens_cloud.team_api + burnlens_cloud.dashboard_api
tags: [team, invite, 402, seat-limit, feature-gate, customers-view, teams-view, D-14, D-16, D-18]
requirements: [QUOTA-04, GATE-05]
dependency_graph:
  requires:
    - burnlens_cloud.auth.require_feature (Plan 09-03)
    - burnlens_cloud.plans.resolve_limits (Phase 6)
    - plan_limits.gated_features (teams_view / customers_view per Plan 09-01)
    - plan_limits.seat_count (Phase 6)
    - workspace_members (existing)
  provides:
    - POST /team/invite → 402 with D-14 body at seat cap (QUOTA-04)
    - All /team/* member-management endpoints gated by require_feature('teams_view') at FastAPI dep layer (GATE-05, team half)
    - /api/v1/usage/by-customer + /api/v1/customers gated by require_feature('customers_view') (GATE-05, customer half)
    - /api/v1/usage/by-team gated by require_feature('teams_view') (GATE-05, team-attribution half)
  affects:
    - burnlens_cloud/team_api.py (+60/-20 Task 1; +22/-5 Task 2)
    - burnlens_cloud/dashboard_api.py (+19/-7 Task 3)
tech_stack:
  added: []
  patterns:
    - "FastAPI dependencies=[...] decorator-level Depends pattern for pure middleware gating (no handler-body changes)"
    - "Plan-price-order tuple (_PLAN_PRICE_ORDER = ('free','cloud','teams')) for deterministic required_plan selection — mirrors Plan 03"
    - "resolve_limits-backed seat-limit lookup replacing settings.seat_limits static config"
    - "Sentinel 10**9 for 'unlimited' seat_count (None) so `current >= limit` comparison holds"
    - "Legacy parameter preserved on check_seat_limit for API stability even though internally unused"
key_files:
  created: []
  modified:
    - burnlens_cloud/team_api.py
    - burnlens_cloud/dashboard_api.py
decisions:
  - "D-14 body shape honoured exactly: error='seat_limit_reached', limit, current, required_plan, upgrade_url"
  - "D-16 conversion: 422 → 402; upgrade_url moved from /upgrade to /settings#billing (Phase 8 billing anchor)"
  - "D-18 inventory applied: every /team/* member-management endpoint + both customer-attribution endpoints + /usage/by-team; base dashboard routes (summary/by-model/by-tag/by-feature/timeseries/requests/waste-alerts/budget) explicitly NOT gated"
  - "D-19 feature strings used as literal lowercase snake_case: 'teams_view', 'customers_view'"
  - "Preferred gating style: decorator-level `dependencies=[Depends(require_feature(...))]` — keeps handler signatures untouched, consistent across both files"
  - "get_seat_limit refactored to accept workspace_id (not plan); settings.seat_limits no longer consulted; returns 10**9 sentinel when resolved seat_count is None"
  - "check_seat_limit keeps its `plan` parameter for API compatibility — grep confirms no external caller depends on the signature, but preserving the parameter is a zero-cost hedge"
  - "accept_invitation is not in team_api.py (lives in auth.py) and was not touched — gating that path would break the signup loop for invitees who are not yet workspace members"
  - "Activity endpoint (GET /team/activity) treated as part of team management surface and gated under teams_view — D-18's '/api/teams/*' covers audit trails of team activity"
metrics:
  duration: "~20m"
  completed_date: "2026-04-22"
  tasks: 3
  files_modified: 2
---

# Phase 9 Plan 7: Team Invite 402 + require_feature Gate Inventory Summary

**One-liner:** Converted `POST /team/invite`'s seat-limit 422 → 402 with the D-14 body, swapped `settings.seat_limits` for `resolve_limits(workspace_id).seat_count`, attached `require_feature("teams_view")` to every member-management endpoint in `team_api.py`, and gated the three attribution routes in `dashboard_api.py` (`/usage/by-customer`, `/customers`, `/usage/by-team`) — fully closes QUOTA-04 and GATE-05.

## Scope

Plan 07 (Wave 3) closes two phase-level requirements:

- **QUOTA-04** (seat-limit 402): `POST /team/invite` now responds `402 seat_limit_reached` with `{limit, current, required_plan, upgrade_url: /settings#billing}` when the workspace is at seat cap.
- **GATE-05** (middleware on every gated route): Every D-18-inventoried route now passes through `require_feature(...)` at the FastAPI dependency layer BEFORE the handler body runs. Team half lives in `team_api.py`, customer/attribution half lives in `dashboard_api.py`.

## Endpoints Gated

### `burnlens_cloud/team_api.py` → `require_feature("teams_view")`

| Method | Path | Handler | Gated? |
|--------|------|---------|--------|
| GET    | `/team/members`            | `list_members`       | Yes |
| DELETE | `/team/members/{member_id}`| `remove_member`      | Yes |
| PATCH  | `/team/members/{member_id}`| `update_member_role` | Yes |
| POST   | `/team/invite`             | `invite_member`      | Yes |
| GET    | `/team/activity`           | `get_activity`       | Yes |

All via decorator-level `dependencies=[Depends(require_feature("teams_view"))]`. Handler bodies unchanged (only `invite_member` lost its inline 422 plan-gate, because the middleware now covers that case).

### `burnlens_cloud/dashboard_api.py` → `require_feature("customers_view")`

| Method | Path | Handler |
|--------|------|---------|
| GET | `/api/v1/usage/by-customer` | `get_costs_by_customer` |
| GET | `/api/v1/customers`         | `get_customers`         |

### `burnlens_cloud/dashboard_api.py` → `require_feature("teams_view")`

| Method | Path | Handler |
|--------|------|---------|
| GET | `/api/v1/usage/by-team` | `get_costs_by_team` |

## Endpoints Explicitly NOT Gated

### In `burnlens_cloud/team_api.py`
- `accept_invitation` — not in this file (lives in auth.py). Per D-18, gating it would break the signup loop for invitees who are not yet workspace members.

### In `burnlens_cloud/dashboard_api.py` (base dashboard surface — every plan, including Free, must reach these)
- `/api/v1/usage/summary`
- `/api/v1/usage/by-model`
- `/api/v1/usage/by-tag`
- `/api/v1/usage/by-feature`
- `/api/v1/usage/timeseries`
- `/api/v1/requests`
- `/api/v1/waste-alerts`
- `/api/v1/budget`

Grep-verified: none of these eight decorators have `require_feature` in their window.

## Before/After Diff (team_api.py 422 blocks)

### Block 1 — `plan_does_not_support_teams` (DELETED)

**Before** (lines ~292-300):
```python
if plan not in ["teams", "enterprise"]:
    raise HTTPException(
        status_code=422,
        detail={
            "error": "plan_does_not_support_teams",
            "message": f"Plan '{plan}' does not support Teams. Upgrade to Teams plan.",
            "upgrade_url": f"{settings.burnlens_frontend_url}/upgrade",
        },
    )
```

**After:** Deleted entirely. The `Depends(require_feature("teams_view"))` on the `POST /team/invite` decorator now raises 402 (`feature_not_in_plan`) BEFORE `invite_member` runs. A short comment replaces the block pointing future readers at D-18.

### Block 2 — seat-limit 422 (CONVERTED → 402)

**Before** (lines ~319-328):
```python
if await check_seat_limit(token.workspace_id, plan):
    limit = await get_seat_limit(plan)
    raise HTTPException(
        status_code=422,
        detail={
            "error": "seat_limit_reached",
            "limit": limit,
            "upgrade_url": f"{settings.burnlens_frontend_url}/upgrade",
        },
    )
```

**After:**
```python
if await check_seat_limit(token.workspace_id, plan):
    limit = await get_seat_limit(token.workspace_id)
    current = await _current_seat_count(token.workspace_id)
    required = await _lowest_plan_with_seat_count(current)
    raise HTTPException(
        status_code=402,
        detail={
            "error": "seat_limit_reached",
            "limit": limit,
            "current": current,
            "required_plan": required,
            "upgrade_url": f"{settings.burnlens_frontend_url}/settings#billing",
        },
    )
```

Four changes: status 422 → 402, `get_seat_limit(plan)` → `get_seat_limit(token.workspace_id)`, new `current` + `required_plan` fields, upgrade_url anchor moved to `/settings#billing`.

## New Helpers (team_api.py)

- `_PLAN_PRICE_ORDER = ("free", "cloud", "teams")` — module constant; matches Plan 03's `auth.py` tuple; enterprise intentionally absent until priced publicly.
- `async def _current_seat_count(workspace_id) -> int` — COUNT(*) on active workspace_members; drives D-14 `current` field.
- `async def _lowest_plan_with_seat_count(current: int) -> Optional[str]` — queries `plan_limits WHERE seat_count IS NULL OR seat_count > $1`; walks `_PLAN_PRICE_ORDER`; returns the cheapest plan whose seat_count covers `current+1`, or None if no plan covers it (Phase 10's contact-sales affordance).

## Refactor: `get_seat_limit` (team_api.py)

**Before:**
```python
async def get_seat_limit(plan: str) -> int:
    return settings.seat_limits.get(plan, 1)
```

**After:**
```python
async def get_seat_limit(workspace_id) -> int:
    limits = await resolve_limits(workspace_id)
    return limits.seat_count if limits is not None and limits.seat_count is not None else 10**9
```

`settings.seat_limits` is no longer referenced anywhere in `team_api.py`. `check_seat_limit(workspace_id, plan)` keeps `plan` for API stability but internally calls the new `get_seat_limit(workspace_id)`.

## Must-Haves Verification

| Truth | Verified? |
|-------|-----------|
| POST /team/invite seat-limit branch returns 402 with D-14 body | Yes — status_code=402, error="seat_limit_reached", limit + current + required_plan + upgrade_url (/settings#billing) all present in `invite_member` source |
| POST /team/invite gated by require_feature('teams_view') at FastAPI dep layer | Yes — decorator-level `dependencies=[Depends(require_feature("teams_view"))]` on `@router.post("/invite", ...)` |
| get_seat_limit reads from resolve_limits(workspace_id).seat_count | Yes — new body is `await resolve_limits(workspace_id)`; `settings.seat_limits` no longer appears in team_api.py |
| Every other team endpoint (list/update/remove members) dep-gated by teams_view | Yes — all 5 router decorators (members GET, members DELETE, members PATCH, invite POST, activity GET) carry the dependency |
| Old 422 plan_does_not_support_teams branch deleted | Yes — `grep plan_does_not_support_teams burnlens_cloud/team_api.py` returns 0 |
| Customer-attribution routes gated by require_feature('customers_view') | Yes — 2 occurrences on `/usage/by-customer` and `/customers` decorators |
| /usage/by-team gated by require_feature('teams_view') | Yes — 1 occurrence on the decorator |

## Acceptance Criteria Compliance

### Task 1
- `plan_does_not_support_teams` string no longer appears anywhere in team_api.py — verified (grep count 0).
- `invite_member`'s seat-limit raise uses `status_code=402` with all required body fields — verified.
- `_current_seat_count` and `_lowest_plan_with_seat_count` exist and are async — verified via AST.
- `_PLAN_PRICE_ORDER = ("free", "cloud", "teams")` tuple exists — verified.
- File parses cleanly — `python -c "import ast; ast.parse(open('burnlens_cloud/team_api.py').read())"` exits 0.

### Task 2
- `get_seat_limit` signature accepts `workspace_id`; body calls `await resolve_limits(workspace_id)` — verified.
- `settings.seat_limits` no longer appears in team_api.py — verified (grep count 0).
- `require_feature` imported from `.auth` — verified.
- `require_feature("teams_view")` appears 5 times in decorators (+ 1 in a docstring comment, total 6) — verified.
- `accept_invitation` does not exist in team_api.py; cannot be accidentally gated.

### Task 3
- `require_feature` imported from `.auth` (single-line, comma-separated) — verified.
- `require_feature("customers_view")` appears on both `/usage/by-customer` and `/customers` decorators (count 2) — verified.
- `require_feature("teams_view")` appears on `/usage/by-team` decorator (count 1) — verified.
- Ungated routes (`/usage/summary`, `/usage/by-model`, `/usage/by-tag`, `/usage/by-feature`, `/usage/timeseries`, `/requests`, `/waste-alerts`, `/budget`) carry no `require_feature` in their decorator windows — verified for all eight.
- File parses cleanly — AST check exits 0.
- No handler bodies modified — only decorator signatures + one docstring line per gated route.

## Deviations from Plan

### Auto-decisions (no user intervention)

**1. [Rule 2 - Correctness] Kept `plan` parameter on `check_seat_limit` for API stability**

- **Found during:** Task 2 planning.
- **Issue:** The plan's Task 2 Part A says "if check_seat_limit has `plan` as a parameter that is now unused, keep the parameter for API stability OR remove it if no external callers exist."
- **Decision:** Kept the parameter. Grep across `burnlens_cloud/` shows `check_seat_limit` is only called from within `team_api.py` itself, so removal would have been safe. Retaining it is a zero-cost hedge against any test fixture or future external caller that might rely on the signature. Added a docstring note explaining the parameter is retained for compat.
- **Files modified:** `burnlens_cloud/team_api.py`.
- **Commit:** `785d3e9`.

**2. [Rule 2 - Correctness] Gated `GET /team/activity` under teams_view**

- **Found during:** Task 2 endpoint enumeration.
- **Issue:** The plan's Task 2 lists members-CRUD + invitations endpoints. `GET /team/activity` is the audit-log of team actions (invite sent, role changed, member removed). It is part of the team-management surface and D-18 says "all existing team endpoints beyond /invite".
- **Decision:** Gated under teams_view. A Free/Cloud workspace has no team activity by construction (no members beyond the owner, no invites possible), so this endpoint serves no useful data on those plans and its entitlement boundary matches team-management semantically.
- **Files modified:** `burnlens_cloud/team_api.py`.
- **Commit:** `2cc71f1`.

**3. [Rule 3 - Blocker-avoidance] Added `resolve_limits` import + `require_feature` in a single auth-import line rather than a new import line**

- **Found during:** Task 1 scope (the plan's Task 2 said to "add if missing"; Task 1's seat-limit conversion needs `get_seat_limit(workspace_id)` which needs `resolve_limits` in scope). Since Task 1 and Task 2 share the same function definition touch, the refactor of `get_seat_limit` happened during Task 1's edit chain.
- **Decision:** Merged the `get_seat_limit` refactor into the Task 1 commit (which also converts the 422 to 402) because the new body of the 402 raise uses `get_seat_limit(token.workspace_id)` (workspace-id based, not plan). Keeping them in separate commits would have meant Task 1 shipped a `get_seat_limit(plan)` → `get_seat_limit(workspace_id)` call-site mismatch. This is not a divergence from plan intent — the plan's Task 1 action block literally writes `limit = await get_seat_limit(token.workspace_id)`.
- **Commits:** Task 1 = `785d3e9` (422 conversion + new helpers + get_seat_limit refactor). Task 2 = `2cc71f1` (require_feature attachments only).
- **Net impact:** Zero. Same code, same file, cleaner commits.

### Noted, not a deviation

No divergence from D-18 inventory. Every route named in D-18 is gated; every route outside D-18 is not.

## Authentication Gates

None triggered — this is pure Python middleware wiring; no migrations, no Paddle calls, no email sends, no SMTP.

## Known Stubs

None. Every gate is backed by live infrastructure: `require_feature` reads live `plan_limits.gated_features` (Plan 09-01 seeded teams_view/customers_view per plan). `_current_seat_count` and `_lowest_plan_with_seat_count` query live `plan_limits.seat_count` (Phase 6). `upgrade_url` points at `/settings#billing` which is a live Phase 8 billing-card anchor.

## Threat Flags

No new security-relevant surface introduced beyond what the plan's `<threat_model>` already covered (T-09-37 through T-09-45 — all mitigated by `require_feature` running at the FastAPI dependency layer before handler bodies).

Omitted: no threat flag entries needed.

## Files Modified

- `burnlens_cloud/team_api.py` — +82 / -25 across 2 commits:
  - Task 1 (`785d3e9`): typing Optional import, resolve_limits import, require_feature import from .auth, `get_seat_limit` refactor, `check_seat_limit` docstring, `_PLAN_PRICE_ORDER` tuple, `_current_seat_count` helper, `_lowest_plan_with_seat_count` helper, deletion of `plan_does_not_support_teams` 422 block, conversion of seat-limit 422 → 402 with D-14 body.
  - Task 2 (`2cc71f1`): 5 decorator signatures rewritten to multi-line with `dependencies=[Depends(require_feature("teams_view"))]`.
- `burnlens_cloud/dashboard_api.py` — +19 / -7 in 1 commit:
  - Task 3 (`07ddf7a`): auth import extended with `require_feature`; 3 decorator signatures rewritten to multi-line with `dependencies=[Depends(require_feature(...))]` on `/usage/by-customer`, `/usage/by-team`, `/customers`.

No other files touched.

## Self-Check: PASSED

Files modified:
- `burnlens_cloud/team_api.py` — FOUND (AST parses; `plan_does_not_support_teams` absent; `seat_limit_reached` + `status_code=402` + `/settings#billing` + `_current_seat_count` + `_lowest_plan_with_seat_count` + `_PLAN_PRICE_ORDER` + `resolve_limits` all present; `settings.seat_limits` absent; `require_feature("teams_view")` appears 5× in decorators).
- `burnlens_cloud/dashboard_api.py` — FOUND (AST parses; `from .auth import ...require_feature` present; `require_feature("customers_view")` appears 2× at correct anchors; `require_feature("teams_view")` appears 1× at `/usage/by-team`; eight base-dashboard decorators ungated).

Commits:
- `785d3e9` — FOUND (Task 1).
- `2cc71f1` — FOUND (Task 2).
- `07ddf7a` — FOUND (Task 3).

Python parses cleanly:
- `python -c "import ast; ast.parse(open('burnlens_cloud/team_api.py').read())"` → exits 0.
- `python -c "import ast; ast.parse(open('burnlens_cloud/dashboard_api.py').read())"` → exits 0.

Automated plan verify asserts — all three `<automated>` blocks in the plan were run and returned `OK`:
- Task 1: plan_does_not_support_teams absent; status_code=402 in invite_member; D-14 fields present; helpers exist.
- Task 2: resolve_limits in get_seat_limit; settings.seat_limits absent; require_feature imported; teams_view gate count = 6 (5 decorators + 1 docstring).
- Task 3: require_feature imported; customers_view count = 2; teams_view count = 1; has_gate_near checks pass for 3 gated decorators; has_any_gate_near returns False for all 8 ungated decorators.
