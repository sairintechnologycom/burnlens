---
phase: 14-budget-aware-model-downgrade
plan: "02"
subsystem: storage
tags: [sqlite, migration, dataclass, routing, budget]
dependency_graph:
  requires: []
  provides: [ROUTE-05]
  affects: [burnlens/storage/models.py, burnlens/storage/database.py]
tech_stack:
  added: []
  patterns: [idempotent-pragma-migration, nullable-dataclass-fields]
key_files:
  created: []
  modified:
    - burnlens/storage/models.py
    - burnlens/storage/database.py
decisions:
  - "Routing fields appended after `id` field in RequestRecord to preserve positional arg ordering in existing tests"
  - "No index added on routing columns — low cardinality, full-scan acceptable at current volume"
  - "Used PRAGMA table_info() idempotency pattern (same as existing migrations) rather than ALTER TABLE IF NOT EXISTS"
metrics:
  duration: "~3 minutes"
  completed: "2026-05-05T05:08:26Z"
  tasks_completed: 2
  tasks_total: 2
---

# Phase 14 Plan 02: Storage Layer Extension Summary

Extended the SQLite storage layer to record routing decisions made by the budget-aware model downgrade engine — 4 nullable columns added via idempotent migration, RequestRecord updated with matching optional fields, and insert_request() extended from 21 to 25 columns.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add routing fields to RequestRecord | e146a60 | burnlens/storage/models.py |
| 2 | Add migrate_add_routing_columns + extend insert_request | dfbd491 | burnlens/storage/database.py |

## What Was Built

### burnlens/storage/models.py

Added four optional fields to `RequestRecord` after the `id` field:

- `routed_model: str | None = None` — the model the router actually used (may differ from requested model)
- `downgrade_reason: str | None = None` — why the downgrade occurred (e.g. `budget_pct`, `budget_abs`)
- `budget_remaining_usd: float | None = None` — USD remaining at routing time
- `budget_remaining_pct: float | None = None` — percentage of budget remaining at routing time

All four default to `None` — all existing call sites (proxy, scan importers) continue to work without modification.

### burnlens/storage/database.py

Three changes:

1. **`migrate_add_routing_columns(db_path)`** — new idempotent migration function. Uses `PRAGMA table_info(requests)` to detect existing columns before issuing `ALTER TABLE ... ADD COLUMN`. Adds `routed_model TEXT`, `downgrade_reason TEXT`, `budget_remaining_usd REAL`, `budget_remaining_pct REAL`.

2. **`init_db()` call** — `await migrate_add_routing_columns(db_path)` appended after `migrate_add_source_column`, consistent with the established migration chain.

3. **`insert_request()` extended** — INSERT column list extended from 21 to 25, VALUES placeholder count updated to 25. Existing `None` routing field values insert as SQL NULL, preserving backward compatibility.

## Verification Results

- `RequestRecord()` instantiates without routing fields; all four default to `None` — OK
- `RequestRecord(routed_model='gpt-4o-mini', ...)` sets all fields correctly — OK
- `init_db()` on fresh DB creates all four routing columns — OK
- Running migration twice on the same DB does not error (idempotent) — OK
- `insert_request()` with routing fields set persists correct values — OK
- `insert_request()` with routing fields=None persists NULL — OK
- All 72 existing storage tests pass — OK

## Deviations from Plan

None — plan executed exactly as written.

## Threat Surface Scan

No new network endpoints, auth paths, or trust boundaries introduced. Routing fields are written server-side only from `RouteDecision` (set in interceptor, never from user-controlled request input). T-14-02-01 and T-14-02-02 mitigations are in place as designed.

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| burnlens/storage/models.py exists | FOUND |
| burnlens/storage/database.py exists | FOUND |
| 14-02-SUMMARY.md exists | FOUND |
| Commit e146a60 exists | FOUND |
| Commit dfbd491 exists | FOUND |
