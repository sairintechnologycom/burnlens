---
phase: 09-quota-tracking-soft-enforcement
plan: 05
subsystem: burnlens_cloud.ingest
tags: [ingest, upsert, quota, email, threshold, soft-enforcement]
requirements: [QUOTA-01, QUOTA-02, QUOTA-03]
dependency_graph:
  requires:
    - "workspace_usage_cycles table (09-01)"
    - "idx_workspace_usage_cycles_ws_start UNIQUE index (09-01)"
    - "burnlens_cloud.email.send_usage_warning_email (09-02)"
    - "burnlens_cloud/emails/templates/usage_{80,100}_percent.html (09-02)"
    - "burnlens_cloud.plans.resolve_limits (Phase 6)"
    - "workspaces.current_period_started_at / current_period_ends_at (Phase 7)"
  provides:
    - "POST /v1/ingest QUOTA-03 soft-accept contract (no 429 branch)"
    - "QUOTA-01 per-cycle counter via single-statement UPSERT with RETURNING"
    - "QUOTA-02 80%/100% warning email firing exactly once per cycle"
    - "_record_usage_and_maybe_notify module helper (async, fire-and-forget, never raises)"
  affects:
    - "burnlens_cloud/ingest.py (net +115 lines: -38 deletions, +153 additions)"
tech_stack:
  added: []
  patterns:
    - "Postgres single-statement UPSERT with RETURNING for atomic counter + inline threshold read (one round-trip)"
    - "Atomic check-and-set via UPDATE ... WHERE notified_*_at IS NULL RETURNING id (race-safe threshold claim, T-09-25 mitigation)"
    - "Crossing predicate pct_prev < threshold <= pct_new (not pct_new >= threshold) to prevent re-fire after cross"
    - "100%-before-80% precedence guards against double-send in single batch"
    - "Double try/except (inner swallow + outer guard) hardens fire-and-forget against programmer error"
    - "Platform-safe cycle-end formatting: f\"{cycle_end:%B} {cycle_end.day}, {cycle_end.year}\" (no GNU-only %-d)"
    - "asyncio.create_task(send_usage_warning_email(...)) — ingest 200 never waits on SMTP"
key_files:
  created: []
  modified:
    - "burnlens_cloud/ingest.py"
decisions:
  - "Helper is module-level, not a closure over the handler — easier to unit-test and keeps the handler body lean."
  - "prev_count = new_count - records_count (subtraction trick) — avoids extra SELECT round-trip to read the pre-UPSERT value (D-04)."
  - "resolve_limits None-guard added: an unknown/deleted workspace hits 'return' gracefully rather than AttributeError on .monthly_request_cap (Rule 1 hardening beyond the plan's stated cap==None skip)."
  - "cap <= 0 treated the same as cap is None (skip threshold work) — defensive against misconfigured plan_limits seed rows."
  - "settings import removed from ingest.py — it was the only consumer of settings.free_tier_monthly_limit inside the module, now fully unused (Rule 3 cleanup)."
  - "plan_label sourced from limits.plan (server-authoritative) with fallback to the auth-derived plan str; matches D-09 copy."
metrics:
  duration_minutes: ~10
  tasks_completed: 2
  completed_date: 2026-04-21
---

# Phase 9 Plan 05: Ingest soft-enforcement + counter UPSERT + threshold email

**One-liner:** Flipped `POST /v1/ingest` from hard-reject-429 to soft-accept with a single-statement Postgres UPSERT that bumps the `workspace_usage_cycles` counter and, on 80%/100% crossings, enqueues a fire-and-forget warning email exactly once per cycle.

## Scope

Plan 05 (Wave 2) is the QUOTA-03 pivot — the moment `/v1/ingest` stops hard-rejecting Free workspaces at their monthly cap. Instead every authenticated call:

1. UPSERTs `workspace_usage_cycles (workspace_id, cycle_start)` and reads `request_count` inline via `RETURNING`.
2. If `resolve_limits(workspace_id).monthly_request_cap` is set and the call pushes the workspace across 80% or 100%, atomically claims `notified_{80,100}_at` via a conditional UPDATE, and only the winning request `asyncio.create_task(send_usage_warning_email(...))`.
3. Always returns `200 OK` — the ingest 200 path is never flipped to failure by counter/email failure. Belt-and-suspenders double try/except around the helper guarantees that.

Everything here consumes Wave-1 artifacts (09-01 table + 09-02 email helper/templates) — no new tables, no new Pydantic models, no new email code.

## What Shipped

### 1. Task 1 — Deletions (refactor)
**Commit:** `1a2d3e8`

Removed from `burnlens_cloud/ingest.py`:
- `check_free_tier_limit(...)` helper (old SQL `COUNT(*) FROM request_records`).
- The `if plan == "free": if not await check_free_tier_limit(...)` branch that raised `HTTPException(status_code=429, detail={"error": "free_tier_limit", ...})`.
- Now-unused imports: `from dateutil import tz`, `timedelta` from the `datetime` line, `from .config import settings` (the only in-module consumer of `settings.free_tier_monthly_limit` was the deleted helper; config field itself was left in place per the plan's explicit out-of-scope note).

Net: ingest.py dropped 38 lines.

### 2. Task 2 — Counter UPSERT + threshold email (feat)
**Commit:** `23c6e70`

Added to `burnlens_cloud/ingest.py`:

- **New imports:** `from .email import send_usage_warning_email`, `from .plans import resolve_limits`.
- **New module helper** `_record_usage_and_maybe_notify(workspace_id, plan, records_count)` — async, `None` return, top-level `try/except Exception` that logs at WARNING and returns. The helper never raises.
- **Cycle bounds resolution** per D-02/D-03:
  - Free: `SELECT date_trunc('month', now() AT TIME ZONE 'UTC') AS cycle_start, (date_trunc('month', now() AT TIME ZONE 'UTC') + INTERVAL '1 month') AS cycle_end`.
  - Paid: `SELECT current_period_started_at, current_period_ends_at FROM workspaces WHERE id = $1`.
  - Missing bounds → warning log + early return (no throw).
- **Counter UPSERT** — the single statement that satisfies QUOTA-01:

  ```sql
  INSERT INTO workspace_usage_cycles
      (workspace_id, cycle_start, cycle_end, request_count, updated_at)
  VALUES ($1, $2, $3, $4, NOW())
  ON CONFLICT (workspace_id, cycle_start) DO UPDATE
      SET request_count = workspace_usage_cycles.request_count + EXCLUDED.request_count,
          updated_at = NOW()
  RETURNING id, request_count, notified_80_at, notified_100_at
  ```
- **prev_count reconstruction** without an extra SELECT: `prev_count = new_count - records_count`.
- **Crossing predicate** `pct_prev < threshold <= pct_new` (not `pct_new >= threshold`) — prevents re-fire once the cycle is already over.
- **Atomic threshold claim** — only the request that wins the UPDATE enqueues the email:

  ```sql
  UPDATE workspace_usage_cycles
  SET notified_100_at = NOW()   -- or notified_80_at
  WHERE id = $1 AND notified_100_at IS NULL
  RETURNING id
  ```
- **100%-before-80% precedence** — if a single batch straddles both 80% and 100%, only the 100% email fires. The 80% branch is an `elif`, not a second `if`.
- **Platform-safe date format** — `f"{cycle_end:%B} {cycle_end.day}, {cycle_end.year}"` renders "April 21, 2026" without GNU-only `%-d` / `%-Y`; works on macOS, Linux, Windows.
- **Fire-and-forget** — `asyncio.create_task(send_usage_warning_email(...))`. Not awaited.

Wired into the handler immediately after `logger.info("Ingested ...")` and BEFORE the existing OTEL forward block:

```python
# Phase 9 QUOTA-01/02/03: record usage, check 80/100% thresholds, enqueue email.
# Wrapped internally; failures MUST NOT affect the ingest 200 response.
try:
    await _record_usage_and_maybe_notify(workspace_id, plan, len(request.records))
except Exception as exc:
    logger.warning("usage.record_outer_guard workspace=%s err=%s", workspace_id, exc)
```

Outer `try/except` is belt-and-suspenders — the helper already swallows every exception, but the outer guard protects against programmer errors (`ImportError` during hot reload, etc.) from ever flipping the 200 path.

## File Size Delta

- **Before:** 167 lines (post-Task-1 deletions: 129 lines).
- **After:** 283 lines.
- **Net:** +116 lines vs. pre-plan baseline (-38 from Task 1, +153 from Task 2, +1 from the outer-guard handler insert).

Plan expected "DECREASE by ~20 lines from deletions + INCREASE by ~70 from new helper" ≈ +50. Actual +116 is higher because the helper is heavily commented and the UPSERT SQL is line-broken for readability. No functional deviation.

## Exact UPSERT SQL (verbatim from final file)

```sql
INSERT INTO workspace_usage_cycles
    (workspace_id, cycle_start, cycle_end, request_count, updated_at)
VALUES ($1, $2, $3, $4, NOW())
ON CONFLICT (workspace_id, cycle_start) DO UPDATE
    SET request_count = workspace_usage_cycles.request_count + EXCLUDED.request_count,
        updated_at = NOW()
RETURNING id, request_count, notified_80_at, notified_100_at
```

Conflict target `(workspace_id, cycle_start)` matches the UNIQUE index `idx_workspace_usage_cycles_ws_start` created in 09-01.

## Must-Haves Verification

| Truth | Verified? | Evidence |
|-------|-----------|----------|
| POST /v1/ingest never returns 429 in v1.1 (QUOTA-03) | Yes | `grep -c 'status_code=429' burnlens_cloud/ingest.py` → 0; `check_free_tier_limit` symbol removed. |
| Every ingest call UPSERTs by (workspace_id, cycle_start) RETURNING new count | Yes | `grep -c 'ON CONFLICT (workspace_id, cycle_start) DO UPDATE' ingest.py` → 1; RETURNING clause present. |
| Paid anchors on `workspaces.current_period_started_at`; free anchors on `date_trunc('month', now() AT TIME ZONE 'UTC')` | Yes | Both SQL branches present in helper lines 35–56. |
| 80/100% claims atomically via conditional UPDATE; only the claimer enqueues | Yes | Both `notified_80_at IS NULL` and `notified_100_at IS NULL` WHERE clauses present; each wrapped by `if claim:` before `asyncio.create_task(...)`. |
| Email enqueue is fire-and-forget; email/counter/threshold failures NEVER affect 200 | Yes | Helper outer `try/except Exception`; handler outer `try/except`; `asyncio.create_task` never awaited. |

## Acceptance Criteria Compliance

Task 1:
- `grep -n 'check_free_tier_limit' burnlens_cloud/ingest.py` → no matches. Pass.
- `grep -n 'status_code=429' burnlens_cloud/ingest.py` → no matches. Pass.
- `grep -n 'free_tier_limit' burnlens_cloud/ingest.py` → no matches. Pass.
- Auth block intact (`get_workspace_by_api_key` on line 186). Pass.
- Bulk insert block intact (`INSERT INTO request_records` on line 227). Pass.
- AST parses cleanly (`python -c "import ast; ast.parse(open(...).read())"`). Pass.

Task 2:
- `_record_usage_and_maybe_notify` present and async. Pass.
- Helper SQL contains `ON CONFLICT (workspace_id, cycle_start) DO UPDATE`, `RETURNING id, request_count, notified_80_at, notified_100_at`, `date_trunc('month', now() AT TIME ZONE 'UTC')`, atomic claim UPDATEs with `notified_*_at IS NULL`, `asyncio.create_task(send_usage_warning_email(...))`. Pass.
- Outer `try/except Exception` in helper. Pass.
- 100% branch runs before 80% branch (line 109 < line 130). Pass.
- Handler calls helper after `logger.info("Ingested ...")` (line 243 call, after line 236 log). Pass.
- OTEL forward block still present (`forwarder.forward_batch` count == 1). Pass.
- Imports `send_usage_warning_email` + `resolve_limits` present. Pass.
- AST parses cleanly. Pass.

Plan-level verification block:
- `grep -c 'status_code=429' burnlens_cloud/ingest.py` → 0. Pass.
- `grep -c 'check_free_tier_limit' burnlens_cloud/ingest.py` → 0. Pass.
- `grep -c 'ON CONFLICT (workspace_id, cycle_start) DO UPDATE' burnlens_cloud/ingest.py` → 1. Pass.
- `grep -c 'send_usage_warning_email' burnlens_cloud/ingest.py` → 3 (import + 80% call + 100% call). Pass.
- `grep -c 'forwarder.forward_batch' burnlens_cloud/ingest.py` → 1. Pass.

Plan's plaintext-assertion on `cycle_end_date` format (f-string, no GNU-only tokens) — confirmed: `f"{cycle_end:%B} {cycle_end.day}, {cycle_end.year}"` renders e.g. "April 21, 2026" on every OS without relying on `%-d`.

## Deviations from Plan

Minor hardening beyond what the plan's task body spelled out. None change the contract.

### Auto-fixed Issues

**1. [Rule 2 - Missing critical defensive check] `resolve_limits` can return `None` for deleted/unknown workspaces**
- **Found during:** Task 2, reviewing `plans.py::resolve_limits` signature which explicitly declares `-> Optional[ResolvedLimits]`.
- **Issue:** Plan's helper pseudo-code did `limits = await resolve_limits(...)` then immediately `cap = limits.monthly_request_cap` — would `AttributeError` on `None` if the workspace was mid-deletion.
- **Fix:** Added `if limits is None: return` before reading `.monthly_request_cap`. The outer `try/except` would have caught the error, but bailing cleanly avoids a confusing "usage.record_failed" warning for a simple race condition.
- **Files modified:** `burnlens_cloud/ingest.py` helper body.
- **Commit:** `23c6e70` (same commit as Task 2 main work).

**2. [Rule 3 - Unused import] `settings` became dead after Task 1 deletions**
- **Found during:** Task 1, grep for remaining `settings.` references in ingest.py returned zero.
- **Fix:** Removed `from .config import settings`. The plan explicitly allows this: "remove any now-unused imports from the top of the file"; the config field `settings.free_tier_monthly_limit` itself is left intact.
- **Files modified:** `burnlens_cloud/ingest.py`.
- **Commit:** `1a2d3e8` (rolled into Task 1's cleanup).

**3. [Rule 2 - Defense in depth] `cap <= 0` treated same as `cap is None`**
- **Found during:** Task 2 composition.
- **Issue:** A misconfigured `plan_limits` row with `monthly_request_cap = 0` would trigger `ZeroDivisionError` on `new_count / cap`. Plan said "cap is None => unlimited => skip"; did not mention 0.
- **Fix:** Widened the guard to `if cap is None or cap <= 0: return`.
- **Files modified:** helper body.
- **Commit:** `23c6e70`.

## Authentication Gates

None. Pure code edit — no SMTP send triggered at write time, no Paddle call, no DB migration required (tables already exist from 09-01). The helper itself is DB-hot-path code; on Railway it will run on first ingest after deploy.

## Security Notes

- **T-09-25 Threshold race:** Mitigated as planned — `UPDATE ... WHERE notified_*_at IS NULL RETURNING id`. asyncpg serializes at the DB; only one UPDATE wins.
- **T-09-27 DoS via tiny batches:** Counter bumps by `len(request.records)` (per-record, not per-call) — flood of 1-record batches still counts each record. No bypass.
- **T-09-28 Log PII:** `logger.warning` logs workspace_id (UUID, not PII) and the exception message; `exc_info=True` on the helper's outermost catch will include stack trace (may contain SQL fragments, not user data). Matches established pattern.
- **T-09-29 Fake plan string:** `plan` is server-authoritative (from `get_workspace_by_api_key` joining `workspaces.plan`). Client cannot override.
- **No new secrets, no new env vars, no new outbound endpoints.** Email send uses existing SendGrid config.

## Known Stubs

None. `_record_usage_and_maybe_notify` is fully wired: real SQL, real `resolve_limits` call, real `asyncio.create_task(send_usage_warning_email(...))` backed by 09-02's SendGrid-live helper. No placeholder no-op returns, no TODO markers, no mock data.

## Threat Flags

None. No new network endpoints, no new auth paths, no schema changes. The one new trust boundary (helper's server-authoritative counter write) was already enumerated in the plan's `<threat_model>` as T-09-25/26/27/28/29/30/31 — all dispositions (mitigate/accept) match the implementation.

## Self-Check: PASSED

Files modified:
- `burnlens_cloud/ingest.py` — FOUND (cat -n shows 283 lines, async def `_record_usage_and_maybe_notify` at line 17, handler at line 159, helper call at line 243).

Commits:
- `1a2d3e8` — FOUND (`git log --oneline --all | grep 1a2d3e8` returns one hit; subject: "refactor(09-05): remove check_free_tier_limit + 429 branch from /v1/ingest").
- `23c6e70` — FOUND (`git log --oneline --all | grep 23c6e70` returns one hit; subject: "feat(09-05): add counter UPSERT + 80/100% threshold email to /v1/ingest").

Syntactic parse:
- `python -c "import ast; ast.parse(open('burnlens_cloud/ingest.py').read())"` → exit 0.

Grep assertions (all passed):
- `status_code=429` → 0 matches.
- `check_free_tier_limit` → 0 matches.
- `free_tier_limit` → 0 matches.
- `ON CONFLICT (workspace_id, cycle_start) DO UPDATE` → 1 match.
- `RETURNING id, request_count, notified_80_at, notified_100_at` → 1 match.
- `date_trunc('month', now() AT TIME ZONE 'UTC')` → 2 matches (cycle_start + cycle_end expressions).
- `notified_80_at IS NULL` + `notified_100_at IS NULL` → 1 each; 100% appears before 80% (line 113 < line 134).
- `send_usage_warning_email` → 3 matches (import + 100% call + 80% call).
- `forwarder.forward_batch` → 1 match (OTEL forward block untouched).
- `_record_usage_and_maybe_notify(workspace_id, plan, len(request.records))` → 1 match (handler wiring).
- `from .email import send_usage_warning_email` → present at top.
- `from .plans import resolve_limits` → present at top.
