---
phase: 16-api-key-management
plan: 04
status: complete
date: 2026-05-12
requirements: [APIKEY-01, APIKEY-03, APIKEY-04, APIKEY-05]
files_modified:
  - tests/test_phase16_api_keys.py  # NEW
  - burnlens_cloud/auth.py          # Rule 1 fix (dropped redundant local import)
---

# 16-04 — Backend Test Coverage for Phase 16 API Key Endpoints

## Outcome

15 tests passing in `tests/test_phase16_api_keys.py`. Locks in viewer-role
scoping, 404 indistinguishability, PATCH contract (max_length=128, no
revoked_at touch, no cache invalidation), and throttled last_used_at writer
semantics (SQL predicate, None skip, exception swallow) — exceeds the
plan's ≥10 test target.

## Test Map (by requirement)

| Requirement | Tests |
|-------------|-------|
| APIKEY-01 (last_used_at surface) | `test_list_keys_response_includes_last_used_at`, `test_last_used_at_throttled_sql_predicate`, `test_last_used_at_skips_when_api_key_id_none`, `test_last_used_at_swallows_exceptions` |
| APIKEY-03 (revoke + indistinguishability) | `test_owner_can_revoke_any_key`, `test_delete_keys_viewer_404_on_other_creator` |
| APIKEY-04 (PATCH rename) | `test_patch_keys_name_max_length_128`, `test_patch_keys_name_too_long_422`, `test_patch_keys_name_empty_422`, `test_patch_keys_missing_name_422`, `test_patch_keys_does_not_invalidate_cache`, `test_patch_keys_viewer_404_on_other_creator`, `test_patch_keys_cross_tenant_404` |
| APIKEY-05 (viewer scoping) | `test_list_keys_owner_returns_all`, `test_list_keys_viewer_returns_only_own` |

## Rule 1 Auto-Fix in 16-03 Code

Discovered while writing the throttle-SQL test:
`_schedule_last_used_update._touch_last_used` had a redundant local import of
`execute_query`. The module-level import on `burnlens_cloud/auth.py:106`
already binds `execute_query` into the module namespace, but the local
`from .database import execute_query` inside `_touch_last_used` re-bound the
symbol at call time, so `patch("burnlens_cloud.auth.execute_query", ...)`
did not intercept the call. Dropped the inner import (no functional change
to production behavior — the symbol is identical to what's already in scope).

Without this fix, `test_last_used_at_throttled_sql_predicate` would assert
`call_count == 1` against an unmocked execute_query that hit the real
DB pool (None in tests) and raised — masked by the swallow-except.

## Patch Target Notes

- `burnlens_cloud.api_keys_api.execute_query` — patched directly (module-level
  import already binds it).
- `burnlens_cloud.api_keys_api.invalidate_api_key_cache` — patched directly.
- `burnlens_cloud.auth.execute_query` — patched directly (after the Rule 1
  fix above; previously the local import made this a no-op).

## Verification

- `pytest tests/test_phase16_api_keys.py -q` → 15 passed, 0 failed.
- `pytest --collect-only -q tests/test_phase16_api_keys.py | grep -cE '::test_'`
  → 15 (≥10 target met).
- `pytest tests/test_phase15_quota_hard.py tests/test_phase11_auth.py
  tests/test_phase16_auth08_resend.py tests/test_phase16_models.py` →
  50 passed (cross-phase regression check, no new failures).

## Self-Check: PASSED
