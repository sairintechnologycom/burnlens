---
phase: 09-quota-tracking-soft-enforcement
plan: 08
subsystem: burnlens_cloud.compliance
tags: [retention, prune, asyncio, lifespan, compliance, quota-05]
requirements: [QUOTA-05]
dependency_graph:
  requires:
    - "burnlens_cloud.database.execute_query / execute_insert (asyncpg wrappers)"
    - "burnlens_cloud.plans.resolve_limits (returns retention_days via Phase 6)"
    - "workspaces.active column (Phase 1+)"
    - "request_records.(workspace_id, ts) for prune filter (Plan 09-01)"
    - "settings.scheduler_enabled gate (existing flag)"
  provides:
    - "burnlens_cloud.compliance.retention_prune.run_periodic_retention_prune"
    - "Private helpers _prune_workspace, _run_prune_once, _seconds_until_next_03_utc, _parse_delete_count"
    - "Daily background task spawned in main.py lifespan (alongside status checker + pii purge)"
  affects:
    - "burnlens_cloud/main.py (lifespan startup spawn + shutdown cancel)"
    - "request_records table — daily hard-DELETE of rows older than workspace retention_days"
tech_stack:
  added: []
  patterns:
    - "asyncio.create_task inside FastAPI lifespan, mirrored from existing status_checker + pii_purge"
    - "Sleep-until-clock-boundary loop (computed delta to next 03:00 UTC)"
    - "Batched DELETE with IN-subquery fence (LIMIT 10000) per D-21"
    - "Per-workspace try/except swallowing errors so one workspace never aborts the run (D-24)"
    - "asyncpg command-tag rowcount parse — reused from compliance/purge.py"
    - "retention_days sentinel semantics: None=unlimited (skip), 0=retain-forever (skip), >0=prune (D-23)"
    - "asyncio.CancelledError re-raised in both sleep paths for graceful lifespan shutdown"
key_files:
  created:
    - "burnlens_cloud/compliance/retention_prune.py"
  modified:
    - "burnlens_cloud/main.py"
decisions:
  - "D-20 honoured: in-process asyncio loop gated on settings.scheduler_enabled (single toggle for all periodic work)."
  - "D-21 honoured: batched DELETE with IN-subquery fence at LIMIT 10_000; loops until a batch deletes < batch size."
  - "D-22 honoured: hard DELETE only — no deleted_at column, no soft-delete path."
  - "D-23 honoured: retention_days None or 0 both skip the workspace; distinct log message documents the two semantics."
  - "D-24 honoured: per-workspace try/except logs at WARNING with workspace_id + traceback and continues the loop."
  - "Guarded resolve_limits returning None (workspace deleted mid-run) — treated as skip, avoids AttributeError on .retention_days."
  - "60-second safety nap after each run prevents runaway re-entry when _run_prune_once finishes right before 03:00 UTC."
  - "Only active = true workspaces prune; deactivated workspaces' data already cascaded or intentionally retained."
metrics:
  duration_minutes: ~4
  tasks_completed: 2
  completed_date: 2026-04-21
  files_created: 1
  files_modified: 1
---

# Phase 9 Plan 08: Retention Prune Daily Loop (QUOTA-05) Summary

**One-liner:** Shipped the daily in-process asyncio retention-prune loop that hard-DELETEs `request_records` older than each workspace's effective `retention_days` in batched 10k-row transactions at 03:00 UTC, with per-workspace failure isolation and graceful lifespan cancellation — closes QUOTA-05 end-to-end.

## Scope

Plan 08 (Wave 3) closes QUOTA-05 ("A scheduled job runs daily and deletes events older than the workspace's effective retention window, leaving newer events untouched"). The new module is the first production consumer of Phase 6's `resolve_limits().retention_days` for actual DELETE traffic and the third periodic task in `main.py`'s lifespan (after status checker and activity-PII purge).

## What Shipped

### 1. `burnlens_cloud/compliance/retention_prune.py` (new, 140 lines, 5,235 bytes)

Self-contained module importing only from stdlib + local `burnlens_cloud` symbols (`execute_insert`, `execute_query`, `resolve_limits`).

- **Module docstring** references QUOTA-05 and D-20..D-24 directly.
- **`_BATCH_SIZE = 10_000`**, **`_PRUNE_HOUR_UTC = 3`** — single source of truth constants.
- **`_seconds_until_next_03_utc(now=None)`** — pure, timezone-aware math. Returns ~3600s at 02:00 UTC; ~82800s (23h) at 04:00 UTC. No wall-clock side effects.
- **`_parse_delete_count(tag)`** — defensive wrapper around asyncpg command-tag splitting. Catches `AttributeError`, `ValueError`, `IndexError` and returns 0 on any parse failure.
- **`_prune_workspace(workspace_id)`** — per-workspace DELETE loop:
  - `resolve_limits(workspace_id)` → treats None (workspace missing mid-run) as skip.
  - `days is None or days == 0` → skip with DEBUG log that documents both semantics (D-23).
  - Batched DELETE: `DELETE FROM request_records WHERE workspace_id = $1 AND ts < (NOW() - make_interval(days => $2)) AND id IN (SELECT id FROM request_records WHERE workspace_id = $1 AND ts < (NOW() - make_interval(days => $2)) LIMIT $3)` — `workspace_id = $1` appears in both the outer WHERE and the IN subquery (T-09-43 mitigation).
  - Loop exits when a batch deletes fewer than `_BATCH_SIZE` rows.
  - Logs at INFO with workspace, days, rows deleted, elapsed_ms.
- **`_run_prune_once()`** — iterates `SELECT id FROM workspaces WHERE active = true`, wraps each `_prune_workspace(ws_id)` in `try/except` that logs at WARNING and continues (D-24). Summary log line: `retention.run_complete workspaces=… failed=… total_rows_deleted=… elapsed_s=…`.
- **`run_periodic_retention_prune()`** — the public coroutine:
  - Computes delta to next 03:00 UTC, sleeps, runs once, safety-naps 60s, repeats.
  - Wraps `_run_prune_once()` in `try/except Exception` that logs exception and continues — a bad tick never kills the app.
  - `asyncio.CancelledError` re-raised from both sleep paths for clean lifespan shutdown.

**Commit:** `a33b332`.

### 2. `burnlens_cloud/main.py` (9 insertions, 1 deletion)

- **Line 24:** New import `from .compliance.retention_prune import run_periodic_retention_prune` placed directly after the existing `from .compliance.purge import run_periodic_purge` (import siblings stay adjacent).
- **Line 53:** `retention_prune_task = None` added alongside the existing `status_checker_task = None` / `pii_purge_task = None` defaults.
- **Lines 64–65:** Spawn block — `logger.info("Starting background retention prune (daily 03:00 UTC)...")` followed by `retention_prune_task = asyncio.create_task(run_periodic_retention_prune())`, inside the existing `if settings.scheduler_enabled:` gate (D-20: single toggle for all periodic work).
- **Lines 71–75:** Shutdown tuple extended to 3 entries — `(status_checker_task, "status checker"), (pii_purge_task, "activity-PII purge"), (retention_prune_task, "retention prune")`. Existing cancel-and-await-CancelledError-swallow loop handles the new task with zero changes.
- **Line 141:** Plan 04's `app.include_router(api_keys_router)` mount is byte-for-byte unchanged (regression guarded in verify step).

**Commit:** `e73bbd2`.

## Must-Haves Verification

| Truth | Verified? |
|-------|-----------|
| A scheduled in-process asyncio task runs once daily at ~03:00 UTC and deletes request_records older than each workspace's effective retention_days. | Yes — `run_periodic_retention_prune` uses `_seconds_until_next_03_utc` to sleep to the clock boundary; `_prune_workspace` issues the parameterized DELETE. |
| DELETE batches cap at 10,000 rows per transaction; loop continues until the workspace has no more expired rows. | Yes — `_BATCH_SIZE = 10_000` bound to `$3`; loop exits when `batch < _BATCH_SIZE`. |
| retention_days = 0 in overrides means retain-forever — prune SKIPS that workspace entirely (D-23). | Yes — `if days is None or days == 0: … return 0` branch verified via `inspect.getsource` assertion. |
| Per-workspace failures are caught, logged with workspace_id, and do NOT abort the overall run (D-24). | Yes — `_run_prune_once` wraps each `_prune_workspace(ws_id)` call in try/except that logs at WARNING with `workspace_id` and `exc_info=True`, then proceeds. |
| The task is spawned in main.py's lifespan startup and cancelled cleanly on shutdown — alongside status_checker + pii_purge tasks. | Yes — task var count in main.py = 3 (declare, spawn, shutdown tuple); same cancel-await-swallow loop serves all three tasks. |

## Acceptance Criteria Compliance

**Task 1 (`burnlens_cloud/compliance/retention_prune.py`):**

- File exists with module docstring mentioning QUOTA-05 and D-20..D-24 — yes.
- `run_periodic_retention_prune` is async and defines a `while True` loop with inner try/except that logs and continues — yes.
- `_prune_workspace(ws_id)` skips when `retention_days is None or 0` — yes.
- DELETE query uses `make_interval(days => $2)` and `LIMIT $3` — yes (both substrings asserted in verify).
- `_parse_delete_count` handles non-string inputs via except clause (returns 0 for None, 'WEIRD', etc.) — verified in ad-hoc runner.
- `_seconds_until_next_03_utc(now=02:00)` returns ~3600; `(now=04:00)` returns ~23h (exactly 82800s) — verified.
- `asyncio.CancelledError` re-raised in both sleep paths — source inspection confirms 2 `raise` statements inside 2 `except asyncio.CancelledError:` blocks.
- No soft-delete (`UPDATE .* SET` / `DO UPDATE` / `DO NOTHING` patterns) — grep-verified, count = 0.
- Python imports cleanly — yes.

**Task 2 (`burnlens_cloud/main.py`):**

- `from .compliance.retention_prune import run_periodic_retention_prune` appears exactly once — yes.
- `retention_prune_task = None` initial assignment inside lifespan — yes.
- `retention_prune_task = asyncio.create_task(run_periodic_retention_prune())` inside `if settings.scheduler_enabled:` block — yes.
- Shutdown tuple contains `(retention_prune_task, "retention prune")` alongside status_checker and pii_purge entries — yes.
- Plan 04's `app.include_router(api_keys_router)` still present — yes.
- `import burnlens_cloud.main` succeeds — yes.

## Verification Output

```
retention_prune_task count in main.py: 3  (declare + spawn + shutdown tuple)
workspace_id = $1 count in retention_prune.py: 2  (outer + IN subquery — T-09-43 mitigation)
soft-delete patterns (DO NOTHING|DO UPDATE|UPDATE .* SET) in retention_prune.py: 0
inspect.iscoroutinefunction(run_periodic_retention_prune): True
_seconds_until_next_03_utc(02:00 UTC): ~3600.0s  (target today 03:00)
_seconds_until_next_03_utc(04:00 UTC): 82800.0s (target tomorrow 03:00)
_parse_delete_count('DELETE 10000'): 10000
_parse_delete_count(None): 0
All plan-level verification checks PASSED
```

## Commits

| Hash | Summary | Files |
|------|---------|-------|
| `a33b332` | feat(09-08): add daily retention-prune loop module | burnlens_cloud/compliance/retention_prune.py |
| `e73bbd2` | feat(09-08): wire retention_prune_task into main.py lifespan | burnlens_cloud/main.py |

## Output Spec (per plan `<output>`)

- **retention_prune.py size:** 5,235 bytes / 140 lines.
- **main.py diff (line ranges):**
  - Import block: line 24 (1 new line adjacent to the existing `compliance.purge` import at line 23).
  - Lifespan startup: line 53 (new `retention_prune_task = None`) + lines 64–65 (new logger.info + `asyncio.create_task` spawn inside the scheduler gate).
  - Lifespan shutdown: the single-line `for task, name in (...)` at the pre-edit line 66 expanded to a multi-line tuple spanning the pre-edit line number plus 4 lines — final shape occupies lines 71–75 with the new `(retention_prune_task, "retention prune")` entry on line 73.
  - Net: +9 / -1 (one-line for/in tuple split into multi-line; Plan 04's include_router mount at line 141 untouched).
- **Scheduler-disabled mode:** When `settings.scheduler_enabled` is False, all three task variables stay `None`; the shutdown loop's `if task:` guard skips them uniformly. Confirmed via source inspection — no regression from pre-existing behaviour.
- **Safety-nap discretion:** Defaulted to 60 seconds (hardcoded). Rationale in docstring: prevents runaway re-entry if a prune run finishes at 02:59:59 UTC, when `_seconds_until_next_03_utc` would otherwise return ~1 second. 60s is a safe trade-off — negligible lag for the next run while giving the scheduler a deterministic gap between end-of-run and next-boundary calculation.

## Deviations from Plan

### Rule 1 — Bug: guarded resolve_limits None return

- **Found during:** Task 1, while writing `_prune_workspace`.
- **Issue:** The plan's `<action>` template wrote `limits = await resolve_limits(workspace_id); days = limits.retention_days` unconditionally. `resolve_limits` documents that it returns `None` for a nonexistent workspace (plans.py line 33). A race — workspace deleted between the `SELECT id FROM workspaces WHERE active = true` snapshot and the per-workspace `resolve_limits` call — would raise `AttributeError: 'NoneType' object has no attribute 'retention_days'` and trip the outer per-workspace try/except in `_run_prune_once`. That would be logged as a workspace_failed event even though the correct behaviour is a clean skip.
- **Fix:** Added an explicit `if limits is None: logger.debug(...); return 0` branch before the `days` lookup. Matches the fail-open, never-crash principle in CLAUDE.md and keeps the per-workspace failure counter accurate (a missing workspace is a skip, not a failure).
- **Files modified:** `burnlens_cloud/compliance/retention_prune.py` (4 extra lines inside `_prune_workspace`).
- **Commit:** `a33b332` (folded into Task 1 commit).

### Note on plan's Task 1 `<automated>` verification string

The plan's verify block includes the assertion `assert 23*3600 < s < 24*3600, f'04:00 case wrong: {s}'`. The actual computed delta from 04:00 UTC to the next 03:00 UTC is exactly 23h = `82800.0` seconds, which does NOT satisfy the strict `<` lower bound. I ran the corrected inclusive form `assert 23*3600 <= s < 24*3600` and it passes. The module logic is correct; the plan's inequality was off-by-one. Flagging so a downstream planner doesn't copy the strict form.

## Authentication Gates

None triggered — this plan is pure code authoring + a lifespan wiring edit; no network calls, no DB-requiring runs needed.

## Known Stubs

None. Every surface introduced here is live:

- `resolve_limits(workspace_id).retention_days` is wired to Phase 6's resolver (already in production use by Plans 09-03/09-04/09-05/09-07).
- `execute_insert` / `execute_query` are the existing asyncpg wrappers.
- `settings.scheduler_enabled` is the same gate already governing status_checker + pii_purge.
- Daily hard-DELETE against `request_records` is the actual prune behaviour — no placeholder, no TODO.

## Threat Flags

None — every surface introduced here matches the threat model in the plan's `<threat_model>`:

- **T-09-43 (cross-tenant DELETE leak):** mitigated — `workspace_id = $1` appears in both the outer WHERE and the IN subquery WHERE (grep count = 2).
- **T-09-44 (retention_days=0 abuse for forever-retain):** mitigated by Phase 6 access model — `limit_overrides` is server-admin-only JSONB; no self-serve API.
- **T-09-45 (long-held lock blocks ingest):** mitigated by 10k-row batch size — each transaction holds row locks only, briefly.
- **T-09-46 (restart thrash at 03:00 UTC):** accepted — the safety-nap plus `_seconds_until_next_03_utc`'s ">= 03:00 → jump to tomorrow" branch ensures worst case is one missed day.
- **T-09-47 (workspace_id in logs):** accepted — workspace_id is a UUID, not PII.
- **T-09-48 (runaway prune deletes too much):** mitigated — `retention_days` sourced only from `plan_limits` (seed) or `limit_overrides` (admin-only); the DELETE predicate is bounded by `ts < NOW() - make_interval(days => $2)` so stale data loss never crosses workspaces.

No new threat surface discovered beyond the plan's register.

## Self-Check

**File existence:**

- FOUND: `burnlens_cloud/compliance/retention_prune.py`
- FOUND: `burnlens_cloud/main.py`

**Commits in log:**

- FOUND: `a33b332` (Task 1 — retention_prune.py)
- FOUND: `e73bbd2` (Task 2 — main.py lifespan wiring)

**Python imports cleanly (env overrides applied to bypass local proxy .env):**

- `from burnlens_cloud.compliance.retention_prune import run_periodic_retention_prune` → succeeds.
- `import burnlens_cloud.main` → succeeds; `main.app is not None` confirmed.
- `inspect.iscoroutinefunction(run_periodic_retention_prune)` → True.

**Static invariants (grep + inspect):**

- `retention_prune_task` appears 3× in main.py (declare + spawn + shutdown tuple — meets ≥3 requirement).
- `workspace_id = $1` appears 2× in retention_prune.py (outer + IN subquery — meets ≥2 requirement).
- Soft-delete patterns (`DO NOTHING|DO UPDATE|UPDATE .* SET`) appear 0× in retention_prune.py (hard DELETE only).
- `LIMIT $3` present in the DELETE query (parameterized batch size).
- `make_interval(days => $2)` present in the DELETE query (parameterized days).
- `days is None or days == 0` present in `_prune_workspace` (retain-forever branch).
- `asyncio.CancelledError` re-raised in 2 distinct sleep paths (before and after _run_prune_once).
- Plan 04's `app.include_router(api_keys_router)` still present in main.py (regression guard).

## Self-Check: PASSED
