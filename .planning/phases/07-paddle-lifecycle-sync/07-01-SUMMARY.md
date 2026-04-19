---
phase: 07-paddle-lifecycle-sync
plan: 01
subsystem: burnlens_cloud.database
status: complete
tags: [schema, migration, paddle, webhooks, postgres]
requirements:
  - PDL-01
  - PDL-02
  - BILL-01
  - BILL-02
dependency_graph:
  requires:
    - burnlens_cloud/database.py:init_db  # extended, not replaced
    - workspaces table (existing, from Phase 0)
  provides:
    - workspaces.trial_ends_at (TIMESTAMPTZ NULL)
    - workspaces.current_period_ends_at (TIMESTAMPTZ NULL)
    - workspaces.cancel_at_period_end (BOOLEAN NOT NULL DEFAULT false)
    - workspaces.price_cents (INTEGER NULL)
    - workspaces.currency (TEXT NULL)
    - paddle_events table (event_id PK, event_type, received_at, payload JSONB, processed_at, error)
    - idx_paddle_events_received_at (received_at DESC)
  affects:
    - Phase 7 Plan 02 (Paddle webhook handler) — will INSERT INTO paddle_events ... ON CONFLICT (event_id) DO NOTHING and UPDATE workspaces SET trial_ends_at/current_period_ends_at/cancel_at_period_end/price_cents/currency
    - Phase 7 Plan 03 (/billing/summary endpoint) — will SELECT these columns for dashboard rendering without round-tripping to Paddle API
tech_stack:
  added: []
  patterns:
    - Idempotent DDL via DO $$ BEGIN ... END $$ blocks with information_schema.columns guards
    - Idempotent CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS
    - PRIMARY KEY on TEXT event_id to enable free webhook dedup via ON CONFLICT DO NOTHING
key_files:
  created: []
  modified:
    - burnlens_cloud/database.py  # +55 lines inside init_db()
decisions:
  - "D-04..D-08 applied: five new workspaces columns, types and defaults locked (trial_ends_at + current_period_ends_at + cancel_at_period_end + price_cents + currency)"
  - "D-09: paddle_events is a standalone top-level table (no FK to workspaces) — events may arrive before workspace row exists; workspace resolution happens via payload.custom_data.workspace_id in Plan 02"
  - "D-10: event_id as PRIMARY KEY gives webhook replay dedup for free via ON CONFLICT (event_id) DO NOTHING"
  - "D-11: processed_at + error columns provide debug surface for stuck events without needing replays"
  - "No GIN index on paddle_events.payload — no Phase 7 query needs it; revisit if admin UI ever reads by payload shape"
  - "cancel_at_period_end is NOT NULL DEFAULT false so Postgres back-fills existing rows deterministically; the other four new columns are nullable (unknown until first Paddle webhook)"
metrics:
  duration: ~5 minutes
  completed_date: 2026-04-19
  tasks_completed: 2
  commits: 2
  lines_added: 55
  lines_removed: 0
---

# Phase 7 Plan 01: Paddle Lifecycle Schema Summary

Extended `burnlens_cloud/database.py::init_db()` with the storage substrate that Phase 7's webhook handler (Plan 02) and `/billing/summary` endpoint (Plan 03) will write to and read from. Two idempotent migration blocks were added — five new columns on `workspaces` and a new `paddle_events` table + index — placed between the Phase 6 `limit_overrides` migration and the `resolve_limits` function definition. Zero new dependencies, zero data rewrites, pure DDL.

## What Was Built

### Task 1 — Five new `workspaces` columns (commit `cc0a202`)

One `await conn.execute("""DO $$ BEGIN ... END $$;""")` block with five `IF NOT EXISTS → ALTER TABLE workspaces ADD COLUMN` guards, one per column:

| Column                     | Type        | Nullability              | Purpose                                                             |
| -------------------------- | ----------- | ------------------------ | ------------------------------------------------------------------- |
| `trial_ends_at`            | TIMESTAMPTZ | NULL                     | Paddle trial window end; cached from subscription payload          |
| `current_period_ends_at`   | TIMESTAMPTZ | NULL                     | Next billing date; drives "Next billing: May 19, 2026" UI string   |
| `cancel_at_period_end`     | BOOLEAN     | NOT NULL DEFAULT `false` | True when user hits "Cancel" but still in current period            |
| `price_cents`              | INTEGER     | NULL                     | Cached plan price for display (`$29/mo`), avoids API round-trip    |
| `currency`                 | TEXT        | NULL                     | ISO-4217 code accompanying `price_cents`                            |

`cancel_at_period_end` is the only column with a non-null default so existing rows back-fill deterministically. The other four stay NULL until the first Paddle webhook populates them.

### Task 2 — `paddle_events` dedup + audit table (commit `8455b0f`)

Two statements immediately after the Task 1 block:

1. **`paddle_events` table**
   - `event_id TEXT PRIMARY KEY` — Paddle's event-envelope id; PK enables `INSERT ... ON CONFLICT (event_id) DO NOTHING` dedup in Plan 02
   - `event_type TEXT NOT NULL`
   - `received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
   - `payload JSONB NOT NULL` — raw signed webhook body (HMAC verified upstream in Plan 02)
   - `processed_at TIMESTAMPTZ` (nullable) — set after handler dispatch; NULL signals stuck/unprocessed events
   - `error TEXT` (nullable) — populated if handler dispatch raised; enables prod debug without replays

2. **`idx_paddle_events_received_at`** on `paddle_events(received_at DESC)` for audit queries by arrival time.

Intentionally omitted: no GIN index on `payload` (no Phase 7 query needs it) and no foreign key to `workspaces` (events may arrive before workspace row exists in edge-case orderings — workspace resolution is via `payload.custom_data.workspace_id` in Plan 02, not via FK).

## Ordering Verification

`grep -n "limit_overrides\|trial_ends_at\|resolve_limits" burnlens_cloud/database.py` confirms the sequence:

- Line 308: `limit_overrides` migration (Phase 6)
- Line 327: `trial_ends_at` migration (this plan, Task 1)
- Line ~355: `paddle_events` CREATE TABLE (this plan, Task 2)
- Line ~368: `CREATE OR REPLACE FUNCTION resolve_limits`

Order matches the plan's placement requirement — all Phase 7 DDL lives strictly between the Phase 6 column migration and the `resolve_limits` function.

## Verification Commands Run

Static / structural (all passed):

- `python -c "import ast; ast.parse(open('burnlens_cloud/database.py').read())"` → exit 0
- Task 1 string asserts (`trial_ends_at TIMESTAMPTZ`, `current_period_ends_at TIMESTAMPTZ`, `cancel_at_period_end BOOLEAN NOT NULL DEFAULT false`, `price_cents INTEGER`, `currency TEXT`) → all present
- `grep -c "CREATE TABLE IF NOT EXISTS paddle_events"` → `1`
- `grep -c "event_id TEXT PRIMARY KEY"` → `1`
- `grep -c "event_type TEXT NOT NULL"` → `1`
- `grep -c "received_at TIMESTAMPTZ NOT NULL DEFAULT NOW"` → `2` (workspace baseline + paddle_events)
- `grep -c "payload JSONB NOT NULL"` → `1`
- `grep -c "idx_paddle_events_received_at"` → `1`
- `grep -c "ON paddle_events(received_at DESC)"` → `1`
- `grep -c "USING GIN"` → `1` (pre-existing `request_records` GIN only; no new GIN introduced)

Runtime idempotency check against live Postgres NOT run locally (no DB on executor host). Structural idempotency is guaranteed by the `IF NOT EXISTS` / DO-block guards; Plan 02/03 work against a real Postgres instance and will prove runtime correctness.

## Deviations from Plan

**1. [Note – Plan text discrepancy] `processed_at TIMESTAMPTZ` grep count**
- **Found during:** Task 2 verification.
- **Issue:** The plan's Task 2 acceptance criterion states `grep -c "processed_at TIMESTAMPTZ" burnlens_cloud/database.py` should return "at least 2 (once here, once in workspaces migrations already)". The actual count is `1` — `processed_at` is a column introduced by this plan and does not exist anywhere else in `database.py` (neither in workspaces nor in any prior migration).
- **Resolution:** No code change needed. The true behavior requirement — `processed_at TIMESTAMPTZ` exists nullable inside the `paddle_events` table — is satisfied (count = 1, inside the new table). The plan's acceptance-criterion comment "once in workspaces migrations already" was a plan-authoring error (there is no such pre-existing column). All `must_haves.truths` are satisfied.
- **Files modified:** None.
- **Commit:** N/A.

No code deviations — plan DDL executed exactly as specified.

## Threat Flags

None — all surface added by this plan (five workspaces columns, `paddle_events` table, one index) is fully captured in the plan's threat register (T-07-01 through T-07-05). Mitigations applied:

- **T-07-01 (Tampering on payload):** `payload JSONB NOT NULL` stored as raw signed body; no mutation path created by this plan (only Plan 02 writes).
- **T-07-02 (Repudiation):** `event_id` PK + `received_at DEFAULT NOW()` form an append-only audit trail; no DELETE pathway exists in this plan.
- **T-07-03 (Replay-flood DoS):** `event_id` PRIMARY KEY enables `ON CONFLICT DO NOTHING` dedup in Plan 02 at a single indexed lookup.
- **T-07-04 (Cross-tenant IDOR via admin read):** Accepted — no read API introduced in this plan; only Plan 02's webhook handler has write access.
- **T-07-05 (EoP via hostile re-migration):** All DDL uses `IF NOT EXISTS` / DO-block guards — re-runs cannot clobber existing schema or change column types.

## Known Stubs

None. This plan is DDL-only; there is no handler, no UI, and no read path introduced. Stub surface is zero.

## Self-Check: PASSED

- [x] `burnlens_cloud/database.py` modified (+55 lines across 2 commits)
- [x] Commit `cc0a202` exists: `feat(phase-7-01): add paddle lifecycle columns to workspaces`
- [x] Commit `8455b0f` exists: `feat(phase-7-01): add paddle_events dedup and audit table`
- [x] Python AST parse of `burnlens_cloud/database.py` succeeds (exit 0)
- [x] All Task 1 `acceptance_criteria` grep strings present
- [x] All Task 2 `acceptance_criteria` grep strings present (except the `processed_at ≥ 2` sub-criterion — documented as a plan-text discrepancy above; true behavioral requirement satisfied)
- [x] No new GIN index introduced (`USING GIN` count still `1`)
- [x] New DO-block appears between `limit_overrides` (line 308) and `resolve_limits` (line ~368)
- [x] No files outside `burnlens_cloud/database.py` were modified by this plan
- [x] `.planning/STATE.md` and `.planning/ROADMAP.md` untouched (orchestrator owns those)
