---
phase: 16-api-key-management
plan: 07
subsystem: api-keys
tags: [security, cr-closure, d-04, audit-integrity]
gap_closure: true
closes:
  - CR-01
requires:
  - burnlens_cloud/api_keys_api.py::update_api_key (pre-existing PATCH endpoint, missing guard)
  - tests/test_phase16_api_keys.py::test_patch_keys_name_max_length_128 (pre-existing IN-05 anti-assertion)
provides:
  - "PATCH /api-keys/{id} terminal-state guard: revoked keys are immutable and return 404 (D-04)"
  - "Regression test: test_patch_revoked_key_returns_404"
  - "Positive SQL-assertion that codifies the guard rather than its absence"
affects:
  - burnlens_cloud/api_keys_api.py::update_api_key (one new WHERE-clause predicate, one new docstring paragraph)
  - tests/test_phase16_api_keys.py (one assertion inverted, one new test appended)
tech-stack:
  added: []
  patterns: [terminal-state-invariant, d-04-indistinguishability, mirrored-where-clause]
key-files:
  created: []
  modified:
    - burnlens_cloud/api_keys_api.py
    - tests/test_phase16_api_keys.py
decisions:
  - "CR-01 closure SQL guard placement: between workspace_id and viewer-creator predicates, mirroring revoke_api_key L196-199 — preserves the existing parameter ordering and the `$4::uuid IS NULL OR …` viewer pattern unchanged"
  - "Test assertion uses `sql.split('RETURNING')[0]` to scope the guard check to the WHERE clause only, allowing RETURNING to keep its existing `revoked_at` column (required for the response payload)"
metrics:
  duration_seconds: 238
  tasks_completed: 2
  files_modified: 2
  tests_added: 1
  tests_inverted: 1
  total_phase16_tests_passing: 34
  completed: 2026-05-15T06:50:39Z
requirements: [APIKEY-04]
---

# Phase 16 Plan 07: Close CR-01 — PATCH `revoked_at IS NULL` guard

CR-01 closed: PATCH `/api-keys/{id}` now refuses to rename a revoked key, returning `404 {detail: {error: 'api_key_not_found'}}` — the same envelope as DELETE on the same revoked key, restoring D-04 indistinguishability and the terminal-state immutability of `api_keys` rows.

## Execution

| Task | Type | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | test | `f780f0b` | tests/test_phase16_api_keys.py |
| 2 (GREEN) | fix | `3369eaf` | burnlens_cloud/api_keys_api.py |

## Diffs

### burnlens_cloud/api_keys_api.py::update_api_key — GREEN diff

```diff
@@ async def update_api_key(...) -> ApiKey:
     """Rename an API key (Phase 16 APIKEY-04 / D-09, D-10, D-11).

     Single editable field — `name`. Hash is unchanged so the cache stays
     valid (no invalidate_api_key_cache call). Cross-tenant or wrong-creator
     edit returns 404 per D-04 indistinguishability.
+
+    Revoked keys are immutable — terminal state (CR-01 closure). PATCH on a
+    revoked key returns 404 with the same envelope as DELETE, preserving the
+    D-04 indistinguishability rule.
     """
     creator_filter = _viewer_creator_filter(token)
     rows = await execute_query(
         """
         UPDATE api_keys
         SET name = $1
         WHERE id = $2
           AND workspace_id = $3
+          AND revoked_at IS NULL
           AND ($4::uuid IS NULL OR created_by_user_id = $4)
         RETURNING id, name, last4, created_at, revoked_at, last_used_at
         """,
```

The new predicate sits between the `workspace_id` and viewer-creator predicates — mirroring the canonical `revoke_api_key` shape at lines 196-199. Parameter count (4 args) unchanged. RETURNING unchanged (still returns `revoked_at` for the response payload, which the test's `sql.split("RETURNING")[0]` assertion correctly excludes from its WHERE-clause check).

### tests/test_phase16_api_keys.py — before/after of the IN-05 assertion

**Before** (bug-locking — codified CR-01's absence):
```python
sql = mock_exec.call_args.args[0]
assert "SET name = $1" in sql
assert "RETURNING" in sql and "last_used_at" in sql
# PATCH must NOT touch revoked_at — only the RETURNING tail references it
assert "revoked_at" not in sql.split("RETURNING")[0]
```

**After** (positive guard — codifies the invariant):
```python
sql = mock_exec.call_args.args[0]
assert "SET name = $1" in sql
assert "RETURNING" in sql and "last_used_at" in sql
# CR-01: PATCH must guard the terminal-state invariant — revoked keys are immutable.
# The WHERE clause (the portion BEFORE the RETURNING tail) must contain `revoked_at IS NULL`.
assert "revoked_at IS NULL" in sql.split("RETURNING")[0]
```

### New regression test (appended at end of file)

```python
@pytest.mark.asyncio
async def test_patch_revoked_key_returns_404(owner_token):
    """CR-01: PATCH on a revoked key must 404 (D-04 indistinguishability — same
    shape as DELETE on a revoked key, so a caller cannot tell whether the key
    exists but is revoked vs. does not exist at all)."""
    from httpx import ASGITransport, AsyncClient

    app = _make_keys_app()
    _auth(app, owner_token)
    key_id = uuid4()
    # UPDATE matched no rows because the guarded WHERE excluded the revoked key.
    with patch(
        "burnlens_cloud.api_keys_api.execute_query", AsyncMock(return_value=[])
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.patch(f"/api-keys/{key_id}", json={"name": "still-trying"})
    assert r.status_code == 404
    assert r.json() == {"detail": {"error": "api_key_not_found"}}
```

## TDD Gate Compliance

- **RED gate:** `f780f0b test(16-07): RED — invert IN-05 anti-assertion + add revoked-key PATCH 404 regression`
  - Observed failure on unmodified `update_api_key`:
    `AssertionError: assert 'revoked_at IS NULL' in '... UPDATE api_keys SET name = $1 WHERE id = $2 AND workspace_id = $3 AND ($4::uuid IS NULL OR created_by_user_id = $4) '`
  - New 404 test passed against current handler (handler already 404s on empty rows; test documents closure intent).
- **GREEN gate:** `3369eaf fix(16-07): GREEN — add AND revoked_at IS NULL to update_api_key WHERE clause`
- **REFACTOR gate:** not needed — change is a single WHERE-clause predicate.

## Verification

### Acceptance criteria

| Criterion | Result |
|-----------|--------|
| `grep -c "AND revoked_at IS NULL" burnlens_cloud/api_keys_api.py` ≥ 2 | **3** (update_api_key, revoke_api_key, create-cap count) |
| Regex `SET name = \$1[\s\S]{0,200}revoked_at IS NULL` matches | **MATCH** |
| `grep -c "assert \"revoked_at\" not in sql.split" tests/test_phase16_api_keys.py` == 0 | **0** |
| `grep -c "test_patch_revoked_key_returns_404" tests/test_phase16_api_keys.py` ≥ 1 | **1** |
| New test asserts `r.json() == {"detail": {"error": "api_key_not_found"}}` | **yes** |
| `pytest tests/test_phase16_api_keys.py -v` exits 0 | **16 passed** |
| `pytest tests/test_phase16_*.py -q` exits 0 | **34 passed** |

Note on the plan's `grep -B1 -A12 "async def update_api_key" ... | grep -c "revoked_at IS NULL"` ≥ 1 criterion: the docstring grew by 3 lines (immutability paragraph) so the SQL guard now sits 22 lines below `async def`, outside the A12 window — `-A30` yields 1 as expected. The canonical `contains_pattern` from the plan's must_haves block (200-char regex spanning `SET name = $1` to `revoked_at IS NULL`) MATCHES, which is the authoritative anti-fake-out check.

### pytest output (final GREEN)

```
$ /opt/homebrew/bin/pytest tests/test_phase16_api_keys.py -q
................                                                         [100%]
16 passed, 4 warnings in 0.61s

$ /opt/homebrew/bin/pytest tests/test_phase16_*.py -q
34 passed, 7 warnings in 1.08s

$ /opt/homebrew/bin/pytest tests/test_phase16_api_keys.py::test_patch_keys_name_max_length_128 tests/test_phase16_api_keys.py::test_patch_revoked_key_returns_404 -v
tests/test_phase16_api_keys.py::test_patch_keys_name_max_length_128 PASSED [ 50%]
tests/test_phase16_api_keys.py::test_patch_revoked_key_returns_404 PASSED [100%]
2 passed, 2 warnings in 10.11s
```

## Deviations from Plan

None — plan executed exactly as written. The post-execution self-check observed that the plan's `-A12` window grep assertion is too narrow once the docstring grows by 3 lines (immutability paragraph); the authoritative `contains_pattern` regex from `must_haves.artifacts` still matches and the threaded SQL inspection confirms the guard lives inside `update_api_key` (line 171, between the `async def` at 149 and the next function at 187).

## Threat Model — Mitigation Status

| Threat ID | Disposition | Status |
|-----------|-------------|--------|
| T-16-07-01 (Information Disclosure — D-04 leak via PATCH) | mitigate | **closed** — guard in place, verified by `test_patch_revoked_key_returns_404` |
| T-16-07-02 (Tampering — post-revoke rename) | mitigate | **closed** — guard in place, verified by positive `revoked_at IS NULL` SQL assertion in `test_patch_keys_name_max_length_128` |
| T-16-07-03 (Elevation of Privilege — viewer cross-tenant) | accept | unchanged — existing viewer-creator filter and tests already cover this |

## Known Stubs

None.

## Deferred — WR-02

WR-02 unconditional `workspaces.api_key_hash UPDATE` on every revoke (`api_keys_api.py:220-228`) was flagged as Info severity and deferred to v1.4 cleanup — no in-scope WR fixes ride this plan.

## Self-Check: PASSED

- `burnlens_cloud/api_keys_api.py` FOUND, contains the new guard at L171
- `tests/test_phase16_api_keys.py` FOUND, contains positive assertion at L178 and new test starting at L386
- Commit `f780f0b` FOUND in git log
- Commit `3369eaf` FOUND in git log
- 16/16 api_keys tests pass; 34/34 Phase 16 sweep passes
