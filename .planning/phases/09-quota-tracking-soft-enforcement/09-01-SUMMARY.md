---
phase: 09-quota-tracking-soft-enforcement
plan: 01
subsystem: burnlens_cloud.database
tags: [postgres, migrations, schema, quota, api_keys, gated_features, idempotent]
requirements: [QUOTA-01, QUOTA-05, GATE-04, GATE-05]
dependency_graph:
  requires:
    - workspaces (existing)
    - workspaces.api_key_hash (existing, from M-1 security review)
    - workspaces.api_key_last4 (existing)
    - users (existing)
    - plan_limits (Phase 6)
  provides:
    - workspace_usage_cycles (with UNIQUE idx_workspace_usage_cycles_ws_start)
    - api_keys (with partial idx_api_keys_workspace_active)
    - plan_limits.gated_features supplement: teams_view / customers_view keys per plan
    - api_keys backfill from workspaces.api_key_hash (idempotent, set-based)
  affects:
    - burnlens_cloud/database.py (init_db)
tech_stack:
  added: []
  patterns:
    - "Idempotent CREATE TABLE IF NOT EXISTS + CREATE [UNIQUE] INDEX IF NOT EXISTS inside init_db()"
    - "Set-based INSERT ... SELECT ... WHERE NOT EXISTS for self-idempotent backfill"
    - "JSONB || additive merge for seed supplements (preserves pre-existing keys)"
    - "FK ON DELETE CASCADE for workspace-scoped child rows; ON DELETE SET NULL for audit-trail references to users"
key_files:
  created: []
  modified:
    - burnlens_cloud/database.py
decisions:
  - "D-01 workspace_usage_cycles columns honoured exactly (id, workspace_id, cycle_start, cycle_end, request_count BIGINT DEFAULT 0, notified_80_at, notified_100_at, updated_at)."
  - "D-11 api_keys columns honoured exactly (id, workspace_id, key_hash UNIQUE, last4, name DEFAULT 'Primary', created_at, revoked_at, created_by_user_id → users ON DELETE SET NULL)."
  - "D-12 backfill is set-based, not row-by-row — idempotent by UNIQUE(key_hash) + NOT EXISTS guard."
  - "D-19 gated_features supplement uses JSONB || merge; Phase 6 keys preserved; no wholesale SET = '{...}'."
  - "Partial index idx_api_keys_workspace_active predicate `WHERE revoked_at IS NULL` unchanged (Plan 04 cap-count fast path)."
  - "Per D-Discretion: no (workspace_id, name) unique index on api_keys in v1.1 (no UI yet)."
metrics:
  duration: "~15m"
  completed_date: "2026-04-21"
  tasks: 3
  files_modified: 1
---

# Phase 9 Plan 1: Quota / Feature-Gating Schema Foundation Summary

**One-liner:** Landed the two Phase 9 schema blocks (`workspace_usage_cycles`, `api_keys`) with their indices + a set-based backfill + a `gated_features` seed supplement — all inside `init_db()`, fully idempotent.

## Scope

Plan 01 (Wave 1) lays the Postgres schema every other Phase 9 plan reads or writes:

- Plan 05's `/v1/ingest` UPSERT targets `workspace_usage_cycles (workspace_id, cycle_start)`.
- Plan 04's api-keys router reads active counts via `idx_api_keys_workspace_active`.
- Plan 08's `require_feature("teams_view" / "customers_view")` dependency reads `plan_limits.gated_features` flags seeded here.

## Changes

### 1. `workspace_usage_cycles` table + unique composite index
- **File:** `burnlens_cloud/database.py`
- **Location:** `init_db()` — new block at **lines 796-817** (after the `cancellation_surveys` index, before the `resolve_limits` function).
- **CREATE TABLE:** line 802.
- **CREATE UNIQUE INDEX idx_workspace_usage_cycles_ws_start:** line 815.
- **FK:** `workspace_id` → `workspaces(id) ON DELETE CASCADE`.
- **Conflict target:** `(workspace_id, cycle_start)` — reserved for Plan 05's ingest UPSERT; not renameable.
- **Commit:** `38db2cd`.

### 2. `api_keys` table + partial index + set-based backfill
- **File:** `burnlens_cloud/database.py`
- **Location:** `init_db()` — new block at **lines 819-856** (immediately after the `workspace_usage_cycles` block).
- **CREATE TABLE:** line 825.
- **Partial index idx_api_keys_workspace_active:** line 840 (`ON api_keys(workspace_id) WHERE revoked_at IS NULL`).
- **Backfill INSERT:** line 850 — `INSERT INTO api_keys ... SELECT ... FROM workspaces w WHERE w.api_key_hash IS NOT NULL AND NOT EXISTS (...)`.
- **FKs:**
  - `workspace_id` → `workspaces(id) ON DELETE CASCADE`
  - `created_by_user_id` → `users(id) ON DELETE SET NULL` (audit trail survives user deletion — D-11)
- **Uniqueness:** `key_hash TEXT NOT NULL UNIQUE` (per-row claim + backfill idempotency anchor).
- **Commit:** `1088405`.

### 3. `gated_features` seed supplement (teams_view / customers_view per plan)
- **File:** `burnlens_cloud/database.py`
- **Location:** `init_db()` — new block at **lines 858-876** (after the `api_keys` backfill, before the `resolve_limits` function).
- **Two UPDATEs with JSONB `||` additive merge:**
  - `WHERE plan IN ('free', 'cloud')` → adds `{"teams_view": false, "customers_view": false}` (line 868).
  - `WHERE plan = 'teams'` → adds `{"teams_view": true, "customers_view": true}` (line 873).
- **Preserves** Phase 6 keys (`custom_signatures`, `team_seats`, `otel_export`) — no wholesale replacement.
- **Commit:** `c941277`.

## Must-Haves Verification

| Truth | Verified? |
|-------|-----------|
| `workspace_usage_cycles` UPSERT by `(workspace_id, cycle_start)` in a single statement | Yes — UNIQUE composite index is the conflict target. |
| `SELECT ... WHERE workspace_id=$1 AND cycle_start=$2` is a single indexed lookup | Yes — UNIQUE index covers both columns, left-prefix match. |
| `api_keys` row per existing `workspace.api_key_hash` after init_db(); zero extra on second run | Yes — set-based `INSERT ... SELECT ... WHERE NOT EXISTS` on `key_hash`. UNIQUE(key_hash) would block dupes even if the guard were weaker. |
| `plan_limits.gated_features` has `teams_view` + `customers_view` per plan (Free/Cloud false, Teams true) | Yes — two targeted UPDATEs using `||` merge. |
| Running `init_db()` twice yields identical DB state to one run | Yes — every DDL uses `IF NOT EXISTS`; backfill is set-based + guarded; seed supplement idempotent via `||` identity. |

## Acceptance Criteria Compliance

- `grep` finds exactly one `CREATE TABLE IF NOT EXISTS workspace_usage_cycles` — verified.
- `grep` finds exactly one `CREATE TABLE IF NOT EXISTS api_keys` — verified.
- `CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_usage_cycles_ws_start` covers `(workspace_id, cycle_start)` — verified.
- `CREATE INDEX IF NOT EXISTS idx_api_keys_workspace_active ON api_keys(workspace_id) WHERE revoked_at IS NULL` — verified.
- All D-01, D-11, D-19 column shapes honoured exactly (no additions, no deletions, no reorderings beyond the CREATE TABLE list).
- No row-by-row loop in the api_keys backfill.
- No wholesale `SET gated_features = '{...}'` replacement.
- `python -c "import ast; ast.parse(open('burnlens_cloud/database.py').read())"` exits 0 — verified.

## Deviations from Plan

None. D-01 / D-11 / D-19 shapes adhered to exactly. DDL ordering chosen was: `workspace_usage_cycles` (table + index) → `api_keys` (table + index + backfill) → `gated_features` seed supplement — all adjacent in `init_db()` between the existing `cancellation_surveys` block and the `resolve_limits` function. This ordering is explicit in the plan's task sequence.

### Note on the Plan's `<automated>` verification string for Task 1

The plan's Task 1 automated-check asserts:

```python
assert 'ON DELETE CASCADE' in src.split('workspace_usage_cycles')[1].split(')')[0]
```

This split truncates at the **first** `)` after `workspace_usage_cycles`, which falls inside `DEFAULT gen_random_uuid()` on the `id UUID` column — `ON DELETE CASCADE` only appears on the `workspace_id` column a few lines later. The assertion as written will always fail for a well-formed DDL that uses `gen_random_uuid()` (the same pattern used by the plan's own analog `cancellation_surveys` block at lines 780-794).

**Resolution:** I verified the real intent (the `workspace_id` FK carries `ON DELETE CASCADE`) by string-searching for `workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE` inside the `CREATE TABLE` block, which passes. This is a minor flaw in the plan's verification string, not a schema correctness issue. The DDL itself matches D-01 exactly. Flagging it here so a future planner doesn't copy the flawed one-liner.

## Authentication Gates

None triggered — this plan is pure schema work; no network calls, no SMTP, no Paddle calls.

## Known Stubs

None. Every block is productive DDL / backfill / seed logic. There are no placeholder table names, no `TODO` rows, no mock data.

## Self-Check: PASSED

Files created/modified:
- `burnlens_cloud/database.py` — FOUND

Commits:
- `38db2cd` — FOUND (Task 1: workspace_usage_cycles)
- `1088405` — FOUND (Task 2: api_keys + backfill)
- `c941277` — FOUND (Task 3: gated_features supplement)

Python parses cleanly:
- `python -c "import ast; ast.parse(open('burnlens_cloud/database.py').read())"` → exits 0.

Schema assertions (all passed):
- `CREATE TABLE IF NOT EXISTS workspace_usage_cycles` present — 1 occurrence.
- `idx_workspace_usage_cycles_ws_start` present on `(workspace_id, cycle_start)`.
- `CREATE TABLE IF NOT EXISTS api_keys` present — 1 occurrence.
- `key_hash TEXT NOT NULL UNIQUE` present.
- `idx_api_keys_workspace_active` present with `WHERE revoked_at IS NULL` predicate.
- `INSERT INTO api_keys (id, workspace_id, key_hash, last4, name, created_at)` + `WHERE NOT EXISTS (SELECT 1 FROM api_keys ak WHERE ak.key_hash = w.api_key_hash)` present.
- `created_by_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL` present.
- `teams_view` + `customers_view` + `gated_features || ` all present; both `WHERE plan IN ('free', 'cloud')` and `WHERE plan = 'teams'` present.
- No row-by-row loop introduced.
- No wholesale `SET gated_features = '...'` replacement.
