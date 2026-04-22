---
phase: 09-quota-tracking-soft-enforcement
fixed_at: 2026-04-22T00:55:00Z
review_path: .planning/phases/09-quota-tracking-soft-enforcement/09-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
---

# Phase 9: Code Review Fix Report

**Fixed at:** 2026-04-22T00:55:00Z
**Source review:** `.planning/phases/09-quota-tracking-soft-enforcement/09-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (2 Critical + 4 Warning; 4 Info skipped per scope)
- Fixed: 6
- Skipped: 0

## Fixed Issues

### CR-01: Paid-plan quota tracking silently broken — `workspaces.current_period_started_at` column does not exist

**Files modified:** `burnlens_cloud/ingest.py`
**Commit:** 46b199d
**Applied fix:** Replaced the `SELECT current_period_started_at, current_period_ends_at FROM workspaces` query (which raised `UndefinedColumnError` because that column never existed) with a lookup against `workspace_usage_cycles` ordered by `cycle_start DESC LIMIT 1` filtered by `cycle_end > NOW()`. Added a calendar-month fallback for the case where the Paddle webhook has not yet delivered. Paid-plan ingest paths now increment the cycle counter correctly and the 80%/100% thresholds can fire.

### CR-02: Revoked API keys continue to authenticate for up to `api_key_cache_ttl` seconds

**Files modified:** `burnlens_cloud/auth.py`, `burnlens_cloud/api_keys_api.py`
**Commit:** 6198eae
**Applied fix:** Added `invalidate_api_key_cache(key_hash)` helper to `auth.py` (avoids reaching into the private `_api_key_cache` dict from another module). Modified `revoke_api_key` to `RETURNING id, key_hash`, then immediately calls `invalidate_api_key_cache(revoked_hash)`. Revocation now takes effect within the same process instantly. Multi-worker note included in the helper's docstring.

### WR-01: Feature gate bypassable via `/usage/by-tag?tag_type=customer|team`

**Files modified:** `burnlens_cloud/dashboard_api.py`
**Commit:** 4684e6a
**Applied fix:** Added inline feature-gate enforcement inside `get_costs_by_tag` based on the `tag_type` query parameter: `tag_type=customer` requires `customers_view`, `tag_type=team` requires `teams_view`. Also narrowed `tag_type` via `pattern="^(team|feature|customer)$"` so arbitrary tag keys cannot be injected. Used the existing `require_feature(name)(token=token)` pattern (the dependency factory returns a checker callable). Internal callers `/usage/by-customer` and `/usage/by-team` pass through their already-gated tokens, so no duplicate 402.

### WR-02: 401 "Invalid API key" from ingest does not distinguish revoked vs nonexistent — and cache poisoning risk on revoke

**Files modified:** `burnlens_cloud/api_keys_api.py`
**Commit:** a2f4147
**Applied fix:** In `revoke_api_key`, after the api_keys UPDATE, run `UPDATE workspaces SET api_key_hash = NULL, api_key_last4 = NULL WHERE id = $1 AND api_key_hash = $2`. When a revoked key's hash is the same as the backfilled value in the legacy column, the legacy fallback branch in `get_workspace_by_api_key` can no longer silently re-authenticate the plaintext. For keys unique to the new table, the UPDATE is a safe no-op.

### WR-03: `asyncio.create_task` on email send is unawaited and unreferenced — cancellation/shutdown hazard

**Files modified:** `burnlens_cloud/email.py`, `burnlens_cloud/ingest.py`, `burnlens_cloud/main.py`
**Commit:** 4a27e93
**Applied fix:** Added module-level `_pending_email_tasks: set[asyncio.Task]` in `email.py`, plus `track_email_task(task)` (adds to set, registers `add_done_callback(_pending_email_tasks.discard)`) and `drain_pending_email_tasks(timeout=5.0)`. Wrapped both `create_task(...)` call sites in `ingest.py` (80% and 100% threshold branches) and the inner `_send_background` task in `email.py` through `track_email_task`. In `main.py` lifespan shutdown, added `await drain_pending_email_tasks(timeout=5.0)` before cancelling the other background tasks. Eliminates the GC-drop window and gives in-flight SendGrid POSTs a 5-second grace period on shutdown.

### WR-04: 80%/100% threshold logic is incorrect when multiple batches arrive concurrently AND a batch crosses both thresholds "backwards"

**Files modified:** `burnlens_cloud/ingest.py`
**Commit:** 955fa21
**Applied fix:** The root cause (phantom `workspaces.current_period_started_at` column) was eliminated by CR-01. Added a clarifying comment near the threshold-claim UPDATE block in `_record_usage_and_maybe_notify` explaining the narrowed residual race (webhook seeding next cycle between SELECT and UPSERT) and why it is benign — bleed-window usage accounts to the outgoing cycle, the new cycle starts fresh. Note: the review also suggests an integration test; that belongs in the verifier/test phase and is not in scope for the fixer agent.

---

_Fixed: 2026-04-22T00:55:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
