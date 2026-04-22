---
phase: 09-quota-tracking-soft-enforcement
reviewed: 2026-04-22T00:35:13Z
depth: standard
files_reviewed: 14
files_reviewed_list:
  - burnlens_cloud/database.py
  - burnlens_cloud/models.py
  - burnlens_cloud/email.py
  - burnlens_cloud/emails/templates/usage_80_percent.html
  - burnlens_cloud/emails/templates/usage_100_percent.html
  - burnlens_cloud/plans.py
  - burnlens_cloud/auth.py
  - burnlens_cloud/api_keys_api.py
  - burnlens_cloud/main.py
  - burnlens_cloud/ingest.py
  - burnlens_cloud/billing.py
  - burnlens_cloud/team_api.py
  - burnlens_cloud/dashboard_api.py
  - burnlens_cloud/compliance/retention_prune.py
findings:
  critical: 2
  warning: 4
  info: 4
  total: 10
status: issues_found
---

# Phase 9: Code Review Report

**Reviewed:** 2026-04-22T00:35:13Z
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

Phase 9 introduces workspace usage cycles, an `api_keys` table with CRUD, a `require_feature` plan-entitlement middleware, soft quota enforcement with 80%/100% warning emails, Paddle-driven cycle seeding, and a daily retention-prune loop. The overall design is sound and security-conscious (hashed-only key storage, fail-open fire-and-forget, tenant-indistinguishable 404s on cross-tenant access, JSONB `||` additive merge for idempotent seeds).

The most serious issue is a schema/code mismatch that silently disables quota tracking for **every paid-plan workspace**: ingest reads a column (`workspaces.current_period_started_at`) that the schema never creates and no webhook ever writes. The outer exception guard swallows the resulting `UndefinedColumnError`, so ingest still 200s but no cycle row is ever upserted and no 80%/100% email will ever fire for paid customers. The seed rows Paddle writes into `workspace_usage_cycles` are never read back.

A secondary security issue: the new `require_feature` gate is attached to `/usage/by-customer` and `/usage/by-team` but the underlying `/usage/by-tag?tag_type=customer|team` route remains ungated, letting Free-plan users bypass the gate by calling the generic endpoint.

A third concern: revoking an API key via `DELETE /api-keys/{id}` does not invalidate `_api_key_cache`, so revoked keys continue to authenticate for up to `api_key_cache_ttl` seconds — directly undermining the security purpose of revocation.

## Critical Issues

### CR-01: Paid-plan quota tracking silently broken — `workspaces.current_period_started_at` column does not exist

**File:** `burnlens_cloud/ingest.py:42-50`, `burnlens_cloud/billing.py:368,449`
**Issue:** `_record_usage_and_maybe_notify` for non-free plans runs:

```sql
SELECT current_period_started_at AS cycle_start,
       current_period_ends_at    AS cycle_end
FROM workspaces WHERE id = $1
```

`workspaces.current_period_started_at` is never created — `database.py:707-726` only adds `trial_ends_at`, `current_period_ends_at`, `cancel_at_period_end`, `price_cents`, `currency` (no `started_at`). The billing webhook handlers extract `current_period_started_at` from Paddle and use it to seed `workspace_usage_cycles`, but never UPDATE it back onto `workspaces`. Result: every paid-plan ingest call raises `asyncpg.exceptions.UndefinedColumnError`, which is caught by the outer try/except and logged at WARNING (`usage.record_failed`). Ingest still returns 200, but:

- `workspace_usage_cycles.request_count` is never incremented for paid plans
- 80%/100% warning emails will never be sent to paid customers
- The cycle rows that `_handle_subscription_activated/updated` seed with `request_count=0` stay at 0 forever

**Fix:** Read cycle bounds from `workspace_usage_cycles` directly (the Paddle webhooks already seed it) rather than reconstructing from non-existent `workspaces` columns. For example:

```python
if plan == "free":
    cycle_row = await execute_query(
        """
        SELECT
            date_trunc('month', now() AT TIME ZONE 'UTC') AS cycle_start,
            (date_trunc('month', now() AT TIME ZONE 'UTC') + INTERVAL '1 month') AS cycle_end
        """
    )
else:
    # Use the most recent cycle row seeded by billing.py. If none exists
    # (webhook lagged), fall back to the calendar month so we don't drop usage.
    cycle_row = await execute_query(
        """
        SELECT cycle_start, cycle_end
        FROM workspace_usage_cycles
        WHERE workspace_id = $1 AND cycle_end > NOW()
        ORDER BY cycle_start DESC
        LIMIT 1
        """,
        workspace_id,
    )
    if not cycle_row:
        cycle_row = await execute_query(
            """
            SELECT
                date_trunc('month', now() AT TIME ZONE 'UTC') AS cycle_start,
                (date_trunc('month', now() AT TIME ZONE 'UTC') + INTERVAL '1 month') AS cycle_end
            """
        )
```

Alternatively (simpler): add `current_period_started_at TIMESTAMPTZ` to the workspaces ALTER block and have `_handle_subscription_activated/_updated` include it in the UPDATE SET clauses alongside `current_period_ends_at`. Either fix should be covered by an integration test that ingests for a paid workspace and asserts the cycle counter advanced.

### CR-02: Revoked API keys continue to authenticate for up to `api_key_cache_ttl` seconds

**File:** `burnlens_cloud/api_keys_api.py:127-147`, `burnlens_cloud/auth.py:521-560`
**Issue:** `get_workspace_by_api_key` caches lookup results in `_api_key_cache` keyed by `key_hash`, with TTL `settings.api_key_cache_ttl`. When `DELETE /api-keys/{id}` sets `revoked_at = NOW()`, no code path clears the corresponding cache entry. A compromised/leaked key remains accepted by `/v1/ingest` until the entry naturally expires. This directly defeats the security purpose of revocation and contradicts the router-level "Soft-revoke: sets revoked_at = now()" contract, which users will reasonably interpret as "effective immediately".

**Fix:** On revoke, look up the `key_hash` and evict it from `_api_key_cache`. Example:

```python
# api_keys_api.py — revoke_api_key
from .auth import _api_key_cache  # or expose an invalidate_api_key_cache(key_hash) helper

result = await execute_query(
    """
    UPDATE api_keys
    SET revoked_at = NOW()
    WHERE id = $1 AND workspace_id = $2 AND revoked_at IS NULL
    RETURNING id, key_hash
    """,
    str(key_id),
    str(token.workspace_id),
)
if not result:
    raise HTTPException(status_code=404, detail={"error": "api_key_not_found"})
_api_key_cache.pop(result[0]["key_hash"], None)
```

Prefer adding a thin `invalidate_api_key_cache(key_hash)` helper in `auth.py` rather than reaching into the private dict from another module. For multi-worker deployments (Railway spawns multiple Uvicorn workers in some configs), a pub/sub or short-TTL-by-design approach is needed; at minimum, drop the cache TTL to a small value (a few seconds) when revocation semantics matter.

## Warnings

### WR-01: Feature gate bypassable via `/usage/by-tag?tag_type=customer|team`

**File:** `burnlens_cloud/dashboard_api.py:142-181,184-207`
**Issue:** Phase 9 gates `/usage/by-customer` and `/usage/by-team` with `require_feature("customers_view" / "teams_view")`. Both handlers internally call the ungated `get_costs_by_tag` endpoint at `GET /usage/by-tag`, which exposes the same data via a `tag_type` query parameter. A Free-plan user can call `GET /usage/by-tag?tag_type=customer` or `?tag_type=team` directly and retrieve exactly the data the gate was designed to block. The gate is therefore cosmetic against any client that inspects the network tab.

**Fix:** Either (a) drop the public `/usage/by-tag` route and make `get_costs_by_tag` a private helper, routing the per-tag views only through the gated endpoints, or (b) enforce the gate inside `get_costs_by_tag` based on `tag_type`:

```python
@router.get("/usage/by-tag", response_model=List[CostByTag])
async def get_costs_by_tag(
    token: TokenPayload = Depends(verify_token),
    tag_type: str = Query("team", pattern="^(team|feature|customer)$"),
    days: int = Query(7),
):
    if tag_type == "customer":
        await _require_feature_inline(token, "customers_view")
    elif tag_type == "team":
        await _require_feature_inline(token, "teams_view")
    await require_role("viewer", token)
    ...
```

Option (a) is cleaner because it removes the temptation for future routes to introduce the same bypass. Add a regression test that calls `/usage/by-tag?tag_type=customer` as a Free workspace and asserts 402.

### WR-02: `401 "Invalid API key"` from ingest does not distinguish revoked vs nonexistent — and cache poisoning risk on revoke

**File:** `burnlens_cloud/auth.py:534-552`, `burnlens_cloud/ingest.py:186-189`
**Issue:** The dual-read SELECT filters `ak.revoked_at IS NULL`, so revoked keys fall through to the legacy `workspaces.api_key_hash` fallback. If a workspace was created before Phase 9 (owner key in `workspaces.api_key_hash`) and later had a key created via the new endpoint, revoking the new key lets the query match on the legacy row and keep authenticating — the fallback silently "undoes" the revoke for workspaces whose `workspaces.api_key_hash` was the same value that got backfilled.

More practically: the backfill at `database.py:845-854` copies `w.api_key_hash` into `api_keys`. If an operator later revokes *that* row via the UI, the legacy fallback still accepts the plaintext key because `workspaces.api_key_hash` is untouched. Users will perceive this as "revoke didn't work".

**Fix:** When revoking an api_keys row whose `key_hash` equals `workspaces.api_key_hash` for the same workspace, also NULL out the legacy column:

```sql
UPDATE workspaces SET api_key_hash = NULL, api_key_last4 = NULL
WHERE id = $1 AND api_key_hash = $2
```

Or, preferred, drop the legacy fallback branch once the backfill has completed in production — it's only needed for the dual-read transition window, not forever. Track this with a feature flag or dated TODO so it actually gets removed in v1.1.1+ as the comment promises.

### WR-03: `asyncio.create_task` on email send is unawaited and unreferenced — cancellation/shutdown hazard

**File:** `burnlens_cloud/ingest.py:112-132` (both threshold branches), `burnlens_cloud/email.py:242`
**Issue:** Two layers of fire-and-forget: ingest schedules `send_usage_warning_email(...)` via `asyncio.create_task`, which itself schedules `_send_background()` via another `asyncio.create_task`. Neither task is stored in a referenced collection, so:

1. Python's GC can drop the outer task reference if no one keeps it alive (this risk is mitigated by the event-loop strong-reference, but it's an asyncio anti-pattern and linters flag it).
2. On FastAPI lifespan shutdown, these background tasks are cancelled mid-flight. The SendGrid POST may fire but the caller disappears before the response returns — tolerable, but the inner `_send` calls `sg.send(message)` in a thread, so the `asyncio.to_thread` call may also not complete.
3. Lost emails are silent: `send_usage_warning_email` returns `True` as soon as the task is scheduled, so the ingest path never knows the email failed to dispatch.

**Fix:** Keep a module-level `set[asyncio.Task]` and add a `task.add_done_callback(tasks.discard)` so the event loop retains references and a shutdown handler can wait on the outstanding set for a brief grace period (e.g., 5s). Minimal change:

```python
# email.py (top of module)
_pending_email_tasks: set[asyncio.Task] = set()

# when scheduling:
task = asyncio.create_task(_send_background())
_pending_email_tasks.add(task)
task.add_done_callback(_pending_email_tasks.discard)
```

And in `main.py` lifespan shutdown, `await asyncio.wait(_pending_email_tasks, timeout=5)` before cancel.

### WR-04: 80%/100% threshold logic is incorrect when multiple batches arrive concurrently AND a batch crosses both thresholds "backwards"

**File:** `burnlens_cloud/ingest.py:95-103`
**Issue:** The threshold check uses the locally-reconstructed `prev_count = new_count - records_count`. This is correct when batches are serialized by asyncpg's UPSERT, and each batch's `prev_count` reflects what it saw before its own contribution. However:

- If `records_count == 0` (empty records list), `prev_count == new_count`, no email fires — benign.
- If `cap` is `None` (unlimited), returns early — correct.
- **Concern:** If the CYCLE rolls over (webhook seeds a new row with `request_count=0` and `notified_80_at=NULL`) while an in-flight request was targeting the OLD cycle, the ingest's UPSERT `ON CONFLICT (workspace_id, cycle_start) DO UPDATE` will target whichever `cycle_start` the ingest computed at the top of the function. If the ingest reads the OLD cycle_start (because the query reconstructs it from `workspaces.current_period_ends_at` — but see CR-01) and the new row has been seeded with the NEW cycle_start, the old row's counter keeps ticking up past 100% with no email because `notified_80_at`/`notified_100_at` were already claimed.

Low-probability in practice, but worth a comment or a test that explicitly exercises a webhook-driven cycle rollover mid-ingest. This may be out-of-scope correction after CR-01 is fixed.

**Fix:** After fixing CR-01 to read cycle bounds from `workspace_usage_cycles` directly, this race narrows to "ingest begins, webhook seeds, UPSERT targets old row" — which is fine because the old cycle is effectively closed. Add an integration test: seed the next cycle, then ingest; verify the new cycle's counter receives the increment, not the old one.

## Info

### IN-01: `check_seat_limit(workspace_id, plan)` second argument is dead

**File:** `burnlens_cloud/team_api.py:93-109`
**Issue:** The `plan` parameter is no longer used inside the function body (the limit is resolved via `resolve_limits(workspace_id)` now). The docstring acknowledges "retained for backwards compatibility" but this file is internal to the cloud service and grep-checking confirms only `team_api.py` calls it. Dead parameter is a code smell and a future trap.

**Fix:** Remove the parameter and update the single caller at `team_api.py:369`:

```python
async def check_seat_limit(workspace_id: UUID) -> bool:
    ...
```

### IN-02: `_PLAN_PRICE_ORDER` duplicated across three files

**File:** `burnlens_cloud/auth.py:255`, `burnlens_cloud/api_keys_api.py:29`, `burnlens_cloud/team_api.py:112`
**Issue:** The same `("free", "cloud", "teams")` tuple is redefined three times with identical semantics. If Enterprise launches or order changes, three places need edits and one will be missed.

**Fix:** Move to `plans.py` (or a new `constants.py`) as `PLAN_PRICE_ORDER` and import. Also consider deriving from `plan_limits` ordered by a `price_cents` column if/when that becomes canonical.

### IN-03: `get_seat_limit` returns `10**9` sentinel instead of an explicit "unlimited" signal

**File:** `burnlens_cloud/team_api.py:82-90`
**Issue:** Returning `10**9` as a "large enough" sentinel for unlimited works today but is the kind of magic number that bites later (imagine a comparison against `int8` column types or a JSON serialization that emits `1000000000` to a UI that shows the number). The name `get_seat_limit` doesn't signal this; callers must read the docstring.

**Fix:** Either return `math.inf` / `None` and handle in the caller, or introduce a module constant:

```python
UNLIMITED_SEAT_SENTINEL = 10**9  # "effectively unlimited" for >= comparisons
```

### IN-04: 100% email template omits `{current}` — minor copy inconsistency

**File:** `burnlens_cloud/emails/templates/usage_100_percent.html:4`
**Issue:** 80% template: "You've used 80% of your Cloud requests this cycle (X / Y)." 100% template: "You've hit your Cloud monthly cap (Y requests)." The 100% email drops the actual current count. If a workspace crosses 100% by a large margin (e.g., 3× the cap in a single batch), the user sees only the cap, not how far over they went. Not wrong, but the 80%/100% emails should have parallel structure.

**Fix:** Include `{current}` in the 100% template body, e.g., "You've hit your {plan_label} monthly cap ({current} / {limit} requests)." Harmless because `format(current=...)` is already being passed.

---

_Reviewed: 2026-04-22T00:35:13Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
