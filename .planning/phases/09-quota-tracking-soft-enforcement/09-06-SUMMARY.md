---
phase: 09-quota-tracking-soft-enforcement
plan: 06
subsystem: burnlens_cloud.billing
tags: [billing, webhook, paddle, cycle-rollover, quota]
requirements: [QUOTA-01]
dependency_graph:
  requires:
    - workspace_usage_cycles (Plan 09-01)
    - workspaces (existing)
    - workspaces.paddle_subscription_id_hash (Phase 7)
    - workspaces.current_period_ends_at (Phase 7)
    - _sub_id_hash helper (billing.py existing)
    - paddle_events outer dedup (Phase 7)
  provides:
    - Paid-tier cycle-row seeding on subscription.activated
    - Paid-tier cycle-row seeding on subscription.updated
    - _extract_period_start helper (reads current_billing_period.starts_at)
  affects:
    - burnlens_cloud/billing.py
tech_stack:
  added: []
  patterns:
    - "Best-effort post-UPDATE INSERT with ON CONFLICT DO NOTHING guard"
    - "try/except with logger.warning fallback so seed failures never 5xx the webhook"
    - "Belt-and-suspenders: outer paddle_events(event_id) dedup + inner workspace_usage_cycles(workspace_id, cycle_start) dedup"
key_files:
  created: []
  modified:
    - burnlens_cloud/billing.py
decisions:
  - "D-02 honored: paid-tier cycle anchoring lives in the webhook handler, not in ingest."
  - "ON CONFLICT (workspace_id, cycle_start) DO NOTHING (NOT DO UPDATE) — plan-change mid-cycle cannot reset request_count."
  - "Seed insert runs AFTER the UPDATE workspaces — a failed UPDATE short-circuits before seeding."
  - "Free-tier workspaces untouched here — they get their cycle row lazily via ingest (Plan 05)."
  - "Canceled/paused/payment_failed handlers untouched — cancellation does not advance the billing period."
metrics:
  duration: "~10m"
  completed_date: "2026-04-21"
  tasks: 1
  files_modified: 1
---

# Phase 9 Plan 6: Paid-Tier Cycle Rollover on Paddle Webhook Summary

**One-liner:** Seed the next `workspace_usage_cycles` row from the Paddle `subscription.activated` / `subscription.updated` handlers so the next `/v1/ingest` finds a ready paid-tier counter row.

## Scope

Plan 06 (Wave 2) closes the paid half of QUOTA-01. Plan 05 handles the Free-tier lazy-insert case; this plan handles the paid-tier eager-insert case.

Depends on 09-01 (which provides the `workspace_usage_cycles` table + `UNIQUE (workspace_id, cycle_start)` index that this plan uses as its conflict target).

## Changes

### 1. `_extract_period_start` helper
- **File:** `burnlens_cloud/billing.py`
- **Location:** **lines 120-125** (immediately after `_extract_period_end`).
- **Shape:** Mirrors `_extract_period_end`; reads `current_billing_period.starts_at` via the existing `_parse_iso` helper. Returns `Optional[datetime]`, never raises.
- **Rationale:** The plan's prescribed INSERT needs `cycle_start`, but prior to this change there was no local `current_period_started_at` and no corresponding extractor. This is the minimal plumbing required to make the plan's contract executable (Rule 2: missing critical functionality). The schema has `workspaces.current_period_ends_at` but NOT `current_period_started_at` — the cycle-row insert consumes the extracted value directly without persisting it to `workspaces`, matching D-02's "Paddle payload is the source of truth."

### 2. `_handle_subscription_activated` — cycle-row seed
- **File:** `burnlens_cloud/billing.py`
- **Function:** lines **359-439** (was 351-407 pre-patch).
- **New variable binding:** line 368 — `current_period_started_at = _extract_period_start(data)` (immediately adjacent to the existing `current_period_ends_at`).
- **New seed block:** lines **418-439** — INSERT runs AFTER the `UPDATE workspaces` at lines 389-412.
- **SQL:**
  ```sql
  INSERT INTO workspace_usage_cycles
      (workspace_id, cycle_start, cycle_end, request_count)
  VALUES ($1, $2, $3, 0)
  ON CONFLICT (workspace_id, cycle_start) DO NOTHING
  ```
- **Guard:** `if current_period_started_at and current_period_ends_at:` — skips the seed when the Paddle payload lacks either boundary.
- **Fail-open:** `try/except Exception` wraps the INSERT; failures log via `logger.warning` and the handler returns normally.

### 3. `_handle_subscription_updated` — cycle-row seed
- **File:** `burnlens_cloud/billing.py`
- **Function:** lines **442-500** (was 410-437 pre-patch).
- **New variable binding:** line 449 — `current_period_started_at = _extract_period_start(data)`.
- **New seed block:** lines **472-500** — INSERT runs AFTER the `UPDATE workspaces` at lines 454-469.
- **workspace_id resolution:** This handler does not receive `workspace_id` from the Paddle payload. I fetch it after the UPDATE via:
  ```sql
  SELECT id FROM workspaces WHERE paddle_subscription_id_hash = $1
  ```
  — using the same `_sub_id_hash(subscription_id)` lookup already used by the UPDATE. If the lookup returns zero rows, the seed is silently skipped (same fail-open invariant).
- **Same SQL** as `_handle_subscription_activated`; same `ON CONFLICT ... DO NOTHING`; same `try/except` + `logger.warning`.
- **Idempotency on plan-change inside same cycle:** `DO NOTHING` preserves the running `request_count` — a mid-cycle upgrade/downgrade cannot reset usage.

## Must-Haves Verification

| Truth | Verified? |
|-------|-----------|
| `subscription.activated` advancing the period inserts a fresh `workspace_usage_cycles` row | Yes — `INSERT INTO workspace_usage_cycles` block at lines 418-439. |
| `subscription.updated` advancing the period inserts a fresh row | Yes — block at lines 472-500; fetches `workspace_id` via the same `paddle_subscription_id_hash` lookup the UPDATE uses. |
| `ON CONFLICT (workspace_id, cycle_start) DO NOTHING` prevents duplicate inserts across redeliveries | Yes — both blocks use this exact clause; redelivery of the same Paddle event is additionally guarded by the outer `paddle_events(event_id)` dedup at lines ~322. |
| Free workspaces untouched | Yes — these handlers only run for Paddle-managed subscriptions (paid tier). Free workspaces have no subscription, no Paddle event, no code path reaches these blocks. |
| Plan 07 team_api and existing ingest/billing flows untouched | Yes — diff is local to two handlers; no team_api.py, ingest.py, or other billing endpoints touched. |

## Acceptance Criteria Compliance

- Both handlers contain exactly one `INSERT INTO workspace_usage_cycles` block each. Grep count = **2**, matches `<verification>` target.
- Both blocks use `ON CONFLICT (workspace_id, cycle_start) DO NOTHING` (NOT `DO UPDATE`). Grep count = **2**.
- Both blocks wrapped in `try/except Exception` with `logger.warning(...)` on failure.
- Insert runs AFTER the existing `UPDATE workspaces` in each function — verified positionally (`src.find('UPDATE workspaces') < src.find('INSERT INTO workspace_usage_cycles')`).
- `_handle_subscription_canceled`, `_handle_subscription_paused` (collapsed into canceled per Phase 7 D-23), and `_handle_payment_failed` do NOT contain `workspace_usage_cycles`.
- Existing Phase 7 `ON CONFLICT (event_id) DO NOTHING` dedup on `paddle_events` is unchanged.
- `python3 -c "import ast; ast.parse(open('burnlens_cloud/billing.py').read())"` exits 0.

## Automated Verification Output

The plan's `<automated>` block (plus the extra positional + try/except + grep-count checks) was run out-of-tree (to bypass shell-level `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` env vars that pollute the pydantic `Settings` import path — an environmental, not code, issue). Final result: `OK - all assertions passed`:

- Both target handlers contain `INSERT INTO workspace_usage_cycles` ✓
- Both contain `ON CONFLICT (workspace_id, cycle_start) DO NOTHING` ✓
- Neither contains `DO UPDATE` in the cycle-insert vicinity ✓
- Insert-after-UPDATE order verified ✓
- try/except + logger.warning present ✓
- Grep counts = 2 / 2 ✓
- Canceled/paused/payment_failed untouched ✓
- Phase 7 `paddle_events` dedup preserved ✓

## Deviations from Plan

### Auto-added Issues

**1. [Rule 2 — Missing functionality] Introduced `_extract_period_start` helper**
- **Found during:** Task 1 read-first / scoping pass.
- **Issue:** The plan's `<action>` block uses `current_period_started_at` as a local variable in both handlers, but the pre-patch code only bound `current_period_ends_at` (via `_extract_period_end`). There was no `_extract_period_start`, and `workspaces.current_period_started_at` does not exist in the schema (Phase 7 added only `current_period_ends_at`).
- **Fix:** Added a new `_extract_period_start(data: dict) -> Optional[datetime]` helper at lines 120-125, mirroring `_extract_period_end`. It reads `current_billing_period.starts_at` from the Paddle payload. Each handler now binds `current_period_started_at = _extract_period_start(data)` alongside the existing `current_period_ends_at` binding. The extracted value is consumed directly by the new INSERT — it is NOT persisted to `workspaces` (no schema change).
- **Files modified:** `burnlens_cloud/billing.py`
- **Commit:** `61ae677`

**2. [Rule 2 — Missing functionality] `workspace_id` lookup inside `_handle_subscription_updated`**
- **Found during:** Task 1 read-first / scoping pass.
- **Issue:** The plan's `<action>` block uses `workspace_id` as a local variable in both handlers, but the pre-patch `_handle_subscription_updated` did not bind `workspace_id` anywhere — the UPDATE targets rows via `WHERE paddle_subscription_id_hash = $1` without needing to fetch the PK. The INSERT needs `workspace_id` for its first parameter.
- **Fix:** Added a SELECT immediately before the INSERT inside the same `try/except`:
  ```python
  ws_row = await execute_query(
      "SELECT id FROM workspaces WHERE paddle_subscription_id_hash = $1",
      _sub_id_hash(subscription_id),
  )
  workspace_id = ws_row[0]["id"] if ws_row else None
  if workspace_id:
      await execute_insert(...)
  ```
  If the lookup returns zero rows (orphaned subscription event, extremely rare), the seed is silently skipped — matching the fail-open invariant required by D-07 / threat T-09-34. The SELECT executes once per advancing subscription.updated event, which is already rare (1-2x per cycle per paid workspace) — no perf concern.
- **Files modified:** `burnlens_cloud/billing.py`
- **Commit:** `61ae677`

**3. [Rule 3 — Blocking issue] Plan contract compatibility on missing started_at**
- **Found during:** Task 1 scoping.
- **Issue:** The plan's non-negotiable rules say: "If a function does not compute / bind `current_period_started_at` in some code paths ... gate the seed with the `if current_period_started_at and current_period_ends_at:` check; on None skip the insert." I honored this — both blocks are guarded by `if current_period_started_at and current_period_ends_at:`.
- **Fix:** No code change beyond the documented guard; flagging here so the guard choice is visible.
- **Files modified:** `burnlens_cloud/billing.py` (already counted above)
- **Commit:** `61ae677`

### Note on Plan's `<automated>` Harness

The plan's `<automated>` block uses `importlib.import_module('burnlens_cloud.billing')`, which transitively imports `burnlens_cloud.config` → instantiates `Settings()` via pydantic-settings. In my shell environment, `OPENAI_BASE_URL` and `ANTHROPIC_BASE_URL` are set (pointing at the local BurnLens proxy — unrelated to this phase), and pydantic-settings rejects them as `extra_forbidden`.

I ran the same assertions via an AST-level rewrite (reads the file, `ast.parse`, pulls the function body via `ast.get_source_segment`, applies identical assertions) which does NOT instantiate `Settings`. All assertions pass. Flagging here so a future planner with a cleaner shell sees the expected import-path check pass out of the box; or so the verifier knows to `unset` the proxy env vars before running the plan's exact `python -c` snippet.

## Authentication Gates

None triggered — this plan is pure Python edit; no Paddle live calls, no SMTP, no auth flows exercised.

## Known Stubs

None. Every line added is productive — the helper reads a real Paddle field, the handlers issue a real INSERT against the Plan 01 schema, and the `try/except` is a deliberate fail-open not a placeholder.

## Threat Flags

No new security-relevant surface introduced. The INSERT values all come from the already-authenticated Paddle payload (signature verification upstream per Phase 7), and the target table `workspace_usage_cycles` is a Phase 9 table already modeled in the plan's `<threat_model>` (T-09-32..T-09-36). Threat-model mitigations `T-09-32` (redelivery dupes) and `T-09-33` (mid-cycle counter reset) are implemented exactly as planned. `T-09-34` (seed failure kills webhook) is mitigated by the inner try/except as required.

## Self-Check: PASSED

**Files modified:**
- `burnlens_cloud/billing.py` — FOUND

**Commits:**
- `61ae677` — FOUND (Task 1: seed workspace_usage_cycles row on Paddle period rollover)

**Python parses cleanly:**
- `python3 -c "import ast; ast.parse(open('burnlens_cloud/billing.py').read())"` exits 0.

**Schema / code assertions (all passed):**
- `_handle_subscription_activated` contains exactly one `INSERT INTO workspace_usage_cycles` ✓
- `_handle_subscription_updated` contains exactly one `INSERT INTO workspace_usage_cycles` ✓
- Both use `ON CONFLICT (workspace_id, cycle_start) DO NOTHING` (NOT `DO UPDATE`) ✓
- Both wrap insert in `try/except Exception` + `logger.warning(...)` ✓
- Both run INSERT after `UPDATE workspaces` (positional) ✓
- `_handle_subscription_canceled` / `_handle_subscription_paused` / `_handle_payment_failed` do NOT reference `workspace_usage_cycles` ✓
- Existing `ON CONFLICT (event_id) DO NOTHING` dedup unchanged ✓
- Grep counts match `<verification>` section: `INSERT INTO workspace_usage_cycles` = 2; `ON CONFLICT (workspace_id, cycle_start) DO NOTHING` = 2 ✓
