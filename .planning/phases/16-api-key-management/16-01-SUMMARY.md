---
phase: 16-api-key-management
plan: 01
subsystem: cloud-backend
tags: [models, migration, api-keys, pydantic, schema]
requires:
  - "Phase 9 api_keys table (id, workspace_id, key_hash, last4, name, created_at, revoked_at, created_by_user_id)"
  - "Phase 11 TokenPayload role claim (consumed downstream in 16-03, not here)"
provides:
  - "burnlens_cloud.models.ApiKey now exposes last_used_at: Optional[datetime] (default None)"
  - "burnlens_cloud.models.ApiKeyCreateRequest.name max_length=128 (raised from 64)"
  - "burnlens_cloud.models.ApiKeyUpdateRequest (new) — required name, min_length=1, max_length=128"
  - "init_db migration: ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMPTZ"
affects:
  - "burnlens_cloud/api_keys_api.py — 16-03 will consume ApiKeyUpdateRequest in new PATCH endpoint"
  - "burnlens_cloud/auth.py — 16-02 will fire throttled UPDATE on api_keys.last_used_at"
  - "frontend/src/components/ApiKeysTable.tsx — 16-05 will render last_used_at via formatRelativeTime"
tech-stack:
  added: []
  patterns:
    - "Idempotent in-place migration via ALTER TABLE ... ADD COLUMN IF NOT EXISTS (mirrors Phase 11 email_verified_at)"
    - "Single-field Pydantic PATCH body with required name (diverges from AlertRulePatch optional-all pattern by design — D-10)"
key-files:
  created:
    - "tests/test_phase16_models.py — 13 model-level tests covering D-05, D-09, D-10"
  modified:
    - "burnlens_cloud/database.py — init_db migration (line 899–904)"
    - "burnlens_cloud/models.py — ApiKeyCreateRequest, ApiKey, +ApiKeyUpdateRequest (lines 504–545)"
decisions:
  - "D-05 honored: last_used_at is Optional[datetime], NULL = never used (no default timestamp)"
  - "D-09 honored: name max_length unified to 128 across ApiKeyCreateRequest and ApiKeyUpdateRequest"
  - "D-10 honored: ApiKeyUpdateRequest.name is REQUIRED (not Optional), diverging from AlertRulePatch — single-field PATCH where None is meaningless"
  - "Migration placed BEFORE the Phase-11 email_verified_at ALTER (chronological by phase number)"
  - "No backfill: NULL is the correct 'never used' value per D-08"
  - "No new index: read-mostly column queried only via id PK"
metrics:
  duration: "~10 min (foundational schema/model edit, no integration logic)"
  tasks_completed: 2
  files_modified: 2
  files_created: 1
  commits: 3
  tests_added: 13
  tests_passing: 13
  regression_tests_passing: 16  # tests/test_phase15_quota_hard.py
  completed: 2026-05-12
---

# Phase 16 Plan 01: Foundational Schema + Pydantic Model Extensions Summary

**One-liner:** Adds `api_keys.last_used_at TIMESTAMPTZ` migration and three Pydantic model edits (bump `ApiKeyCreateRequest.name` to 128, add `ApiKey.last_used_at`, introduce `ApiKeyUpdateRequest`) so plans 16-02/16-03/16-05 can wire the throttled write, PATCH handler, and UI without re-touching the schema layer.

## What Changed

### `burnlens_cloud/database.py` — migration block (lines 899–904)

Inserted between the existing `idx_api_keys_workspace_active` partial-index block (lines 894–897) and the Phase-11 `email_verified_at` ALTER (lines 935–937). Verbatim:

```python
# Phase 16 (D-05): per-key last-used tracking.
# NULL = never used. Updated at most once per minute via throttled UPDATE
# in auth.get_workspace_by_api_key (D-06/D-07).
await conn.execute("""
    ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMPTZ
""")
```

Migration ordering: chronological by phase number (Phase 16 lands between Phase 9 partial index and Phase 11 user-column ALTER). `IF NOT EXISTS` makes re-runs no-ops.

### `burnlens_cloud/models.py` — three classes (lines 504–545)

Final committed signatures (verbatim):

```python
class ApiKeyCreateRequest(BaseModel):
    """Request body for POST /api-keys.

    `name` is optional; defaults to "Primary" server-side if omitted.
    Phase 16 D-09: max_length raised from 64 to 128 to match the new
    "Label or note" UI field and align with `ApiKeyUpdateRequest`.
    """
    name: Optional[str] = Field(None, max_length=128)


class ApiKey(BaseModel):
    """One row in GET /api-keys list response.

    Never contains plaintext or hash — only the last-4 suffix for UI disambiguation.
    Phase 16 D-05: `last_used_at` surfaces the throttled per-key activity stamp
    (NULL = never used).
    """
    id: UUID
    name: str
    last4: str
    created_at: datetime
    revoked_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None  # Phase 16 D-05


class ApiKeyCreateResponse(ApiKey):
    """Response body for POST /api-keys.

    Extends `ApiKey` with the plaintext `key`. This field is emitted EXACTLY ONCE
    at key-creation time and is never stored server-side or re-emitted on any
    subsequent request. Callers must capture it on the create-response.
    """
    key: str


class ApiKeyUpdateRequest(BaseModel):
    """Request body for PATCH /api-keys/{key_id} (Phase 16 D-09, D-10).

    Single editable field — `name` (label or note). Required (not Optional)
    because this is a single-field PATCH; passing None is meaningless.
    Max length matches `ApiKeyCreateRequest` (128).
    """
    name: str = Field(..., min_length=1, max_length=128)
```

`ApiKeyCreateResponse` was NOT touched — it inherits the new `last_used_at` automatically through `class ApiKeyCreateResponse(ApiKey)`. This is intentional: the create-response always carries `last_used_at=None` (a freshly-issued key has never been used). No call-sites needed updating in this plan because every reader builds `ApiKey` from a SELECT that will now include the column.

### `tests/test_phase16_models.py` — new file (128 LOC, 13 tests)

Pure model-level Pydantic tests, no FastAPI/asyncpg fixtures needed. Coverage:

| Group | Tests | Asserts |
|-------|-------|---------|
| `ApiKeyCreateRequest` | 3 | 128 accepted, 129 rejected, name still Optional |
| `ApiKey.last_used_at` | 3 | constructs without it (defaults None), accepts datetime, field declared in `model_fields` |
| `ApiKeyUpdateRequest` | 7 | class exists, valid name, 128 accepted, empty rejected, missing rejected, 129 rejected, JSON schema marks `name` required |

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `d1e6988` | feat(16-01) | add last_used_at column to api_keys via init_db (Task 1) |
| `edaeefb` | test(16-01) | add failing tests for ApiKey model extensions (Task 2 RED) |
| `ddb645a` | feat(16-01) | extend ApiKey models for last_used_at and label edits (Task 2 GREEN) |

TDD gate sequence honored on Task 2: `test(...)` commit precedes the `feat(...)` commit. RED phase confirmed 11 failures (2 negative-case tests passed coincidentally — empty/oversize names rejected by the pre-existing max_length=64). GREEN phase: all 13 tests pass.

## Verification

| Check | Result |
|-------|--------|
| `grep -c 'ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMPTZ' burnlens_cloud/database.py` | `1` |
| `ApiKeyUpdateRequest.model_json_schema()['required']` | `['name']` |
| `ApiKey.model_fields['last_used_at']` | `annotation=Union[datetime, NoneType] required=False default=None` |
| `ApiKeyCreateRequest.model_fields['name'].metadata` | `[MaxLen(max_length=128)]` |
| `pytest tests/test_phase16_models.py` | 13 passed |
| `pytest tests/test_phase15_quota_hard.py` (regression) | 16 passed, 0 regressions |
| Plan verify snippet 1 (positive cases) | `OK` |
| Plan verify snippet 2 (4 negative ValidationErrors) | `all 4 negative cases raised` |
| `grep -nP 'class ApiKeyUpdateRequest\|max_length=128\|last_used_at: Optional\[datetime\]' burnlens_cloud/models.py \| wc -l` | `4` (≥4 required) |

## Deviations from Plan

None — plan executed exactly as written. No deviation rules triggered.

## Threat Coverage

| Threat ID | Status | Notes |
|-----------|--------|-------|
| T-16-01-01 (Tampering on PATCH body) | Mitigated | `Field(..., min_length=1, max_length=128)` rejects empty/oversize input at the Pydantic boundary before any SQL touches it. Exercised by `test_update_request_rejects_empty_name`, `test_update_request_rejects_129_char_name`, `test_update_request_rejects_missing_name`. |
| T-16-01-02 (Info disclosure via ApiKey response) | Mitigated | `ApiKey` base model still carries no plaintext key/hash. `last_used_at` is a non-PII timestamp. `ApiKeyCreateResponse` inherits `last_used_at` but only ever returns the plaintext `key` once (POST), never echoed by PATCH (PATCH endpoint in 16-03 returns `ApiKey`, not `ApiKeyCreateResponse`). |
| T-16-01-03 (DoS on last_used_at writes) | Deferred to 16-02 | Column-add is read-side concern only; the 1-write-per-minute throttle lands with the auth-path hook. |

No new threat surface introduced beyond the plan's threat register.

## Downstream Consumers

- **16-02** will hook the throttled `UPDATE api_keys SET last_used_at = now() WHERE id = $1 AND (last_used_at IS NULL OR last_used_at < now() - interval '60 seconds')` into `auth.get_workspace_by_api_key`'s success branch (fire-and-forget via `asyncio.create_task`).
- **16-03** will consume `ApiKeyUpdateRequest` as the body type for `PATCH /api-keys/{key_id}` and SELECT `last_used_at` in the new viewer-aware GET handler.
- **16-05** will surface `last_used_at` as a "Last used" column on `/api-keys` via the new `formatRelativeTime(iso)` helper ("Never used" when null).

## Known Stubs

None. This plan ships data-only contracts — no UI/handler stubs introduced. Downstream plans wire consumers.

## Self-Check: PASSED

- `burnlens_cloud/database.py` — FOUND (modified, ALTER block at lines 899–904)
- `burnlens_cloud/models.py` — FOUND (modified, classes at lines 504–545)
- `tests/test_phase16_models.py` — FOUND (created, 128 LOC)
- Commit `d1e6988` — FOUND in `git log`
- Commit `edaeefb` — FOUND in `git log`
- Commit `ddb645a` — FOUND in `git log`
