---
phase: 09-quota-tracking-soft-enforcement
plan: 04
subsystem: burnlens_cloud.api
tags: [api, router, api_keys, 402, fastapi, gate-04]
requirements: [GATE-04]
dependency_graph:
  requires:
    - "burnlens_cloud.models.ApiKey / ApiKeyCreateRequest / ApiKeyCreateResponse (Plan 09-02)"
    - "burnlens_cloud.models.TokenPayload"
    - "burnlens_cloud.auth.verify_token"
    - "burnlens_cloud.auth.generate_api_key"
    - "burnlens_cloud.auth.hash_api_key"
    - "burnlens_cloud.plans.resolve_limits"
    - "burnlens_cloud.database.execute_query"
    - "api_keys table + idx_api_keys_workspace_active (Plan 09-01)"
    - "plan_limits.api_key_count column (Phase 6)"
  provides:
    - "POST /api-keys — create, plaintext-once response, 402 on over-cap"
    - "GET /api-keys — list caller's keys (no plaintext, no hash)"
    - "DELETE /api-keys/{id} — soft-revoke, 404 on cross-tenant id"
    - "burnlens_cloud.api_keys_api.router mounted in main.py"
    - "Local helper _lowest_plan_with_api_key_count"
  affects:
    - "burnlens_cloud/main.py (router registration)"
    - "Plan 09-07 (seat-limit 422→402 standardization can reference D-14 precedent here)"
tech_stack:
  added: []
  patterns:
    - "APIRouter prefix/tags pattern mirroring settings_api.py"
    - "D-14 standardized 402 body {error, limit, current, required_plan, upgrade_url}"
    - "Plaintext-once return pattern (auth.py::signup analog) — plaintext key appears ONLY in create response"
    - "404-not-403 on cross-tenant DELETE — indistinguishability to prevent enumeration"
    - "Workspace scoping via token.workspace_id for every DB filter"
key_files:
  created:
    - "burnlens_cloud/api_keys_api.py"
  modified:
    - "burnlens_cloud/main.py"
decisions:
  - "D-13 honoured exactly: three handlers (POST/GET/DELETE), plaintext `key` only on POST response."
  - "D-14 402 body shape honoured: {error: 'api_key_limit_reached', limit, current, required_plan, upgrade_url} with upgrade_url ending in /settings#billing."
  - "DELETE returns 404 on cross-tenant/missing id (single handler branch guards both cases — prevents enumeration)."
  - "Local helper `_lowest_plan_with_api_key_count` — Plan 03's `_lowest_plan_with_feature` is a different lookup (feature flags vs count cap) and is not reused here."
  - "Kept `cap is None` as unlimited sentinel per Phase 6 D-02."
  - "`name = (body.name or 'Primary').strip() or 'Primary'` handles None AND whitespace-only inputs."
  - "No imports from burnlens_cloud.encryption — api_keys are hashed, not encrypted."
  - "`created_by_user_id` falls back to NULL if token lacks user_id (column is nullable + FK ON DELETE SET NULL)."
metrics:
  duration_minutes: ~6
  tasks_completed: 2
  completed_date: 2026-04-21
  files_created: 1
  files_modified: 1
---

# Phase 9 Plan 04: API Keys CRUD Router (GATE-04) Summary

**One-liner:** Landed the `/api-keys` POST/GET/DELETE router with D-14 standardized 402 cap-enforcement, plaintext-once semantics on create, and 404-on-cross-tenant DELETE to prevent enumeration — mounted in main.py as the Phase 10 UI's sole backend surface.

## Scope

Plan 04 (Wave 2) closes GATE-04 and unblocks Phase 10's Settings → API Keys UI. It is also the first production consumer of Plan 01's `api_keys` table + partial index and Plan 02's `ApiKey*` Pydantic models. No frontend ships in this phase per D-15.

## What Shipped

### 1. `burnlens_cloud/api_keys_api.py` (new, 147 lines, 4,914 bytes)

Self-contained APIRouter module — imports only from stdlib, FastAPI, and local `burnlens_cloud` symbols already provided by Waves 0–1.

- **Module header** mirrors `settings_api.py` lines 1–23 (logger, APIRouter with `prefix="/api-keys", tags=["api-keys"]`).
- **Imports:** `verify_token`, `generate_api_key`, `hash_api_key` from `.auth`; `settings` from `.config`; `execute_query` from `.database`; `ApiKey`, `ApiKeyCreateRequest`, `ApiKeyCreateResponse`, `TokenPayload` from `.models`; `resolve_limits` from `.plans`. No encryption imports (D-13).
- **`_PLAN_PRICE_ORDER = ("free", "cloud", "teams")`** — single source of truth for "cheapest plan first".
- **`_lowest_plan_with_api_key_count(current)`** helper — scans `plan_limits` for plans whose `api_key_count` is NULL (unlimited) or `> current`, returns the cheapest match from `_PLAN_PRICE_ORDER`, else `None`.
- **`POST /api-keys`** → `create_api_key(body: ApiKeyCreateRequest, token: TokenPayload = Depends(verify_token))`:
  - `resolve_limits(token.workspace_id)` → `cap = limits.api_key_count` (None means unlimited; `resolve_limits` itself may return None on nonexistent workspace — guarded with `limits is not None`).
  - COUNT active rows: `SELECT COUNT(*) FROM api_keys WHERE workspace_id = $1 AND revoked_at IS NULL`.
  - Over-cap → `HTTPException(status_code=402, detail={"error": "api_key_limit_reached", "limit": cap, "current": current, "required_plan": <lowest_plan>, "upgrade_url": f"{settings.burnlens_frontend_url}/settings#billing"})`.
  - Under-cap → `generate_api_key()` → `hash_api_key()` → INSERT RETURNING `(id, name, last4, created_at, revoked_at)` → returns `ApiKeyCreateResponse(..., key=plaintext)`.
  - `name = (body.name or "Primary").strip() or "Primary"` handles None and whitespace-only.
  - `created_by_user_id` bound from `str(token.user_id)` when present, else NULL (FK is ON DELETE SET NULL).
  - Logs: `api_key.created workspace=<id> id=<id> name=<name>` — never logs plaintext.
- **`GET /api-keys`** → `list_api_keys(token)`:
  - `SELECT id, name, last4, created_at, revoked_at FROM api_keys WHERE workspace_id = $1 ORDER BY created_at DESC`.
  - Returns `list[ApiKey]` — no plaintext, no hash.
- **`DELETE /api-keys/{key_id}`** → `revoke_api_key(key_id: UUID, token)`:
  - `UPDATE api_keys SET revoked_at = NOW() WHERE id = $1 AND workspace_id = $2 AND revoked_at IS NULL RETURNING id`.
  - Empty result → `HTTPException(status_code=404, detail={"error": "api_key_not_found"})` — same response for cross-tenant, missing, and already-revoked (indistinguishability).
  - Success → `{"ok": True, "id": str(key_id)}`.

**Commit:** `bf411df`.

### 2. `burnlens_cloud/main.py` (2 lines added)

- **Line 17:** `from .api_keys_api import router as api_keys_router` inserted between `team_router` and `settings_router` imports.
- **Line 140:** `app.include_router(api_keys_router)  # /api-keys CRUD (Phase 9 GATE-04)` at the tail of the include_router block.
- `lifespan` context untouched (Plan 08 owns the retention-prune task addition).

**Commit:** `a069f7b`.

## Must-Haves Verification

| Truth | Verified? |
|-------|-----------|
| POST /api-keys creates an active key, returns plaintext exactly once, enforces cap with 402 | Yes — `key=plaintext` appears exactly once in source (grep-verified); 402 raised before any INSERT when `current >= cap`. |
| DELETE /api-keys/{id} soft-revokes via `revoked_at = now()`; 404 on cross-tenant id | Yes — UPDATE includes `workspace_id = $2` predicate + RETURNING; empty result → 404. |
| GET /api-keys returns caller's keys only — no hash, no plaintext | Yes — SELECT projects only `id, name, last4, created_at, revoked_at`. |
| 402 body follows D-14 exactly | Yes — keys `error`, `limit`, `current`, `required_plan`, `upgrade_url`; literal `"api_key_limit_reached"`; URL ends `/settings#billing`. |
| Router mounted in main.py via include_router | Yes — import + include_router both present exactly once; `main.app.routes` contains 3 paths prefixed `/api-keys`. |

## Acceptance Criteria Compliance

**Task 1 (`burnlens_cloud/api_keys_api.py`):**

- File exists at `burnlens_cloud/api_keys_api.py` — yes.
- `router = APIRouter(prefix="/api-keys", tags=["api-keys"])` — yes.
- Three handlers: `create_api_key` (POST ""), `list_api_keys` (GET ""), `revoke_api_key` (DELETE "/{key_id}") — yes.
- Every handler has `token: TokenPayload = Depends(verify_token)` — yes.
- Workspace scoping via `token.workspace_id` in every DB query (`grep -c "workspace_id = \$" = 3`) — yes.
- 402 body contains the literal strings `"api_key_limit_reached"`, `"limit"`, `"current"`, `"required_plan"`, `"upgrade_url"` — yes.
- 404 body contains `"api_key_not_found"` — yes.
- `key=plaintext` appears only inside `create_api_key` (single grep occurrence at line 100) — yes.
- No imports of `burnlens_cloud.encryption` or `.encryption` — yes.

**Task 2 (`burnlens_cloud/main.py`):**

- `from .api_keys_api import router as api_keys_router` present exactly once — yes.
- `app.include_router(api_keys_router)` present exactly once — yes.
- `import burnlens_cloud.main` succeeds — yes (verified in Bash).
- `main.app.routes` has 3 routes starting with `/api-keys` (`POST /api-keys`, `GET /api-keys`, `DELETE /api-keys/{key_id}`) — yes.
- `lifespan` unchanged — `src.count('lifespan') == 4`, unchanged from pre-edit.

## Verification Output

```
lifespan count: 4
OK — routes: [('/api-keys', ['POST']), ('/api-keys', ['GET']), ('/api-keys/{key_id}', ['DELETE'])]

402-count: 1 (>=1 required)
404-count: 1 (>=1 required)
ws-scoped: 3 (>=3 required)
All plan-level verification checks PASSED
```

## Commits

| Hash | Summary | Files |
|------|---------|-------|
| `bf411df` | feat(09-04): add api_keys_api.py CRUD router with 402 plan-cap enforcement | burnlens_cloud/api_keys_api.py |
| `a069f7b` | feat(09-04): mount api_keys_router in main.py | burnlens_cloud/main.py |

## Output Spec (per plan `<output>`)

- **File size:** 4,914 bytes. **Line count:** 147 lines (`burnlens_cloud/api_keys_api.py`).
- **main.py diff:** 2 additions (import at line 17, `include_router` at line 140); no deletions; lifespan unchanged.
- **Routes registered under `/api-keys`:** 3 (POST, GET, DELETE).
- **Plaintext `key` appears only inside `create_api_key`:** confirmed — `grep "key=plaintext"` returns exactly one match at the `ApiKeyCreateResponse(...)` return of `create_api_key`.

## Deviations from Plan

### Rule 1 — Bug: guarded `resolve_limits` None return

- **Found during:** Task 1, while cross-referencing `resolve_limits`'s docstring.
- **Issue:** The plan's action listing wrote `limits = await resolve_limits(...); cap = limits.api_key_count` unconditionally. `resolve_limits` documents that it returns `None` for a nonexistent workspace (plans.py line 33). Although `verify_token` should guarantee a valid workspace, a race (workspace deletion between token issuance and this call) would raise `AttributeError: 'NoneType' object has no attribute 'api_key_count'` and crash the handler.
- **Fix:** `cap = limits.api_key_count if limits is not None else None` — treats "resolver returned None" identically to "unlimited". This is fail-open on the limit check (matches the plan's `cap is None` unlimited contract) and consistent with the broader "never crash the proxy/API" principle from CLAUDE.md.
- **Files modified:** `burnlens_cloud/api_keys_api.py` (single line inside `create_api_key`).
- **Commit:** `bf411df` (fold into Task 1 commit; one-line correctness guard).

### Note on plan's `<automated>` verification string for Task 1

The plan's verification block asserts:
```python
paths = {r.path for r in m.router.routes}
assert '' in paths or '/' in paths, f'POST/GET root missing: {paths}'
```

FastAPI's `APIRouter.routes` returns the *full* path including the router prefix on modern FastAPI (`0.115+` at least). In this codebase `paths == {'/api-keys', '/api-keys/{key_id}'}` — neither `''` nor `'/'` is present. The intended invariant (POST/GET exist at the router root) is correctly verified by checking for `('/api-keys', ('POST',))` and `('/api-keys', ('GET',))` in the set of `(path, methods)` tuples. I ran that corrected check; it passes. The plan's one-liner is a stale-FastAPI artifact; flagging it so a downstream planner doesn't copy it.

## Authentication Gates

None triggered — this plan is pure code authoring + a router mount; no network calls, no DB-requiring tests executed.

## Known Stubs

None. Every handler has live wiring to Wave-1 schema (`api_keys` table) and Wave-1 models (`ApiKeyCreateRequest`/`ApiKey`/`ApiKeyCreateResponse`). The only "not yet" surface is the Settings → API Keys frontend (D-15 explicitly parks it in Phase 10).

## Threat Flags

None — every surface introduced here matches the threat model in the plan:

- T-09-18 (plaintext re-emit) mitigated: `key=plaintext` appears once; GET/DELETE responses omit `key`.
- T-09-19 (cross-tenant DELETE): UPDATE scoped by `workspace_id`; 404 on mismatch prevents enumeration.
- T-09-20 (race-at-cap): accepted; documented in plan threat model.
- T-09-21 (last4 brute force): accepted; standard UX pattern.
- T-09-22 (over-long name): mitigated by `ApiKeyCreateRequest.name: Optional[str] = Field(None, max_length=64)` (Plan 02).
- T-09-23 (error-code oracle): 402 uses COUNT only (no per-row probe); 404 requires caller-supplied id — no oracle.
- T-09-24 (no audit trail): accepted; `logger.info("api_key.created/revoked ...")` is the Phase-9 audit surface.

## Self-Check

**File existence:**

- FOUND: `burnlens_cloud/api_keys_api.py`
- FOUND: `burnlens_cloud/main.py`

**Commits in log:**

- FOUND: `bf411df` (Task 1: api_keys_api.py)
- FOUND: `a069f7b` (Task 2: main.py router mount)

**Python imports cleanly:**

- `import burnlens_cloud.main` → succeeds.
- `from burnlens_cloud.api_keys_api import router` → succeeds; `router.prefix == '/api-keys'`.

**Static invariants (grep):**

- `status_code=402` appears 1× in `api_keys_api.py` (≥1 required).
- `status_code=404` appears 1× in `api_keys_api.py` (≥1 required).
- `workspace_id = $` appears 3× in `api_keys_api.py` (≥3 required — one per handler).
- `"api_key_limit_reached"` + `"api_key_not_found"` + `/settings#billing` all present.
- `key=plaintext` appears exactly once (inside `create_api_key`).
- No imports of `burnlens_cloud.encryption` or `.encryption`.

## Self-Check: PASSED
