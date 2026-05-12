---
phase: 16-api-key-management
plan: 03
status: complete
date: 2026-05-12
requirements: [APIKEY-01, APIKEY-02, APIKEY-03, APIKEY-04, APIKEY-05]
files_modified:
  - burnlens_cloud/api_keys_api.py
  - burnlens_cloud/auth.py
  - tests/test_phase09_quota.py  # Rule 1 auto-fix
---

# 16-03 — API Key Endpoints + Throttled last_used_at Writer

## Outcome

Backend lifecycle for API-key management complete. Four endpoints with role-aware
visibility, plus a fire-and-forget per-key last_used_at updater that costs ≤1
write per key per minute (SQL-side throttle).

## Route Signatures

| Method | Path | Auth | Body | Returns |
|--------|------|------|------|---------|
| POST   | /api-keys              | JWT | ApiKeyCreateRequest    | ApiKeyCreateResponse (plaintext once) |
| GET    | /api-keys              | JWT | —                      | list[ApiKey] (owner: all; viewer: own only) |
| PATCH  | /api-keys/{key_id}     | JWT | ApiKeyUpdateRequest    | ApiKey (renamed; cache untouched) |
| DELETE | /api-keys/{key_id}     | JWT | —                      | {ok, id} (revoked; cache invalidated) |

## PATCH UPDATE (verbatim SQL)

```sql
UPDATE api_keys
SET name = $1
WHERE id = $2
  AND workspace_id = $3
  AND ($4::uuid IS NULL OR created_by_user_id = $4)
RETURNING id, name, last4, created_at, revoked_at, last_used_at
```

Returns 404 with `detail.error == "api_key_not_found"` on cross-tenant or
wrong-creator (D-04 indistinguishability). Does not invalidate the api-key
cache — hash is unchanged (D-11).

## Throttled last_used_at UPDATE (verbatim SQL)

```sql
UPDATE api_keys
SET last_used_at = now()
WHERE id = $1
  AND (last_used_at IS NULL
       OR last_used_at < now() - interval '60 seconds')
```

Scheduled via `asyncio.create_task(_touch_last_used())` — never awaited
(D-07). Exceptions caught and WARNING-logged. SQL predicate enforces
≤1 write per key per 60 s regardless of QPS.

## Cache Shape Change

`_api_key_cache: dict[str, tuple[str, str, Optional[str], float]] = {}`

Tuple shape: **(workspace_id, plan, api_key_id, cached_at)** — was
`(workspace_id, plan, cached_at)` pre-16-03. `api_key_id` is `None` on
legacy `workspaces.api_key_hash` fallback rows so the writer is skipped
silently for those.

## Viewer-Creator Filter

```python
def _viewer_creator_filter(token: TokenPayload) -> Optional[str]:
    return str(token.user_id) if token.role == "viewer" else None
```

Used as the 4th SQL parameter in GET/PATCH/DELETE — pattern
`AND ($N::uuid IS NULL OR created_by_user_id = $N)` collapses to a no-op
for owner/admin and to a creator-only narrowing for viewer.

## Auto-Fix

`tests/test_phase09_quota.py::TestGate04ApiKeyEndpoints` mock matched the
old GET SELECT column list (`SELECT id, name, last4, created_at, revoked_at
FROM api_keys`). Updated to match the new SELECT including `last_used_at`,
plus added `"last_used_at": None` to the returned row dict. All 4 tests in
the gate still pass.

## Verification

- 4 routes registered (`@router.{get,post,patch,delete}`).
- `_viewer_creator_filter` referenced 4× (defn + GET + PATCH + DELETE).
- `_schedule_last_used_update` referenced 3× (defn + cache-hit + cache-miss).
- SQL predicate `last_used_at < now() - interval '60 seconds'` appears 1×.
- `asyncio.create_task(_touch_last_used` appears 1×.
- `ak.id AS api_key_id` in cache-miss SELECT.
- `_schedule_last_used_update(None)` runs without exception (legacy path).
- `pytest tests/test_phase15_quota_hard.py tests/test_phase16_auth08_resend.py
  tests/test_phase11_auth.py tests/test_phase09_quota.py::TestGate04ApiKeyEndpoints`
  → 50 passed (plus 4 phase09 GateE04 tests — all green after Rule 1 fix).

## Downstream

- **16-04** tests all four endpoint behaviors (owner GET, viewer GET filter,
  viewer DELETE 404 on others' keys, PATCH rename + 404 indistinguishability,
  throttled last_used_at write semantics).
- **16-05** consumes the GET/PATCH/DELETE responses (including `last_used_at`)
  to render the dedicated `/api-keys` route UI.

## Self-Check: PASSED

All success criteria met; no deviations.
