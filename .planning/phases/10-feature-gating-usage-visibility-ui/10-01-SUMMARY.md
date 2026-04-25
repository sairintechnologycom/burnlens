---
phase: 10-feature-gating-usage-visibility-ui
plan: 01
subsystem: billing-backend
tags: [billing, usage, meter, fastapi, postgres, phase-10]
requires:
  - "burnlens_cloud.auth.verify_token (TokenPayload.workspace_id)"
  - "burnlens_cloud.plans.resolve_limits (ResolvedLimits.monthly_request_cap, .api_key_count)"
  - "burnlens_cloud.database.execute_query"
  - "Phase 9 workspace_usage_cycles table (cycle_start, cycle_end, request_count)"
  - "Phase 9 api_keys table (workspace_id, revoked_at)"
  - "Phase 6 plan_limits table (paddle_price_id) + resolve_limits() SQL function"
provides:
  - "GET /billing/summary now returns usage.current_cycle + available_plans + api_keys subobjects (additive — backward compatible with Phase 7/8 callers)"
  - "GET /billing/usage/daily — daily request_records aggregation for the caller's current cycle (workspace-scoped, ?cycle=previous returns 400 not_implemented stub)"
  - "_resolve_current_cycle(workspace_id, plan) helper — single source of paid-vs-free + brand-new-workspace cycle resolution; reused by both endpoints in this plan and available for Plans 02/03/04"
  - "_PLAN_PRICE_CENTS module-level constants ({'cloud': 2900, 'teams': 9900}) — committed v1.0 source-of-truth for plan pricing on /billing/summary.available_plans"
  - "Five new Pydantic models: UsageCurrentCycle, AvailablePlan, ApiKeysSummary, UsageDailyEntry, UsageDailyResponse"
affects:
  - "burnlens_cloud/billing.py (handlers + helpers + constants)"
  - "burnlens_cloud/models.py (additive Pydantic models + extended BillingSummary)"
  - "tests/test_billing_usage.py (new — 17 tests)"
  - "tests/test_billing_webhook_phase7.py (3 /billing/summary tests rewired to multi-SQL side_effect mocks)"
tech-stack:
  added: []
  patterns:
    - "Helper-based composition: handler factors paid-vs-free cycle resolution to a private _resolve_current_cycle so Plans 02/03/04 can reuse it"
    - "Source-of-truth ordering: pricing comes from module-level constants (v1.0 committed path) NOT from a runtime column-existence branch (per plan)"
    - "Workspace-scoping invariant: every SELECT in both endpoints binds $1 to token.workspace_id — query/body workspace params are silently ignored by FastAPI (T-10-01 / T-10-26 mitigations)"
key-files:
  created:
    - "tests/test_billing_usage.py (590 lines, 17 tests)"
  modified:
    - "burnlens_cloud/models.py (5 new models + 3 fields on BillingSummary)"
    - "burnlens_cloud/billing.py (handler extension + new daily route + helpers + constants)"
    - "tests/test_billing_webhook_phase7.py (3 tests rewired for multi-SQL handler)"
decisions:
  - "Used module-level _PLAN_PRICE_CENTS constants for available_plans pricing — confirmed plan_limits has no price_cents column (verified via grep on database.py), v1.2 followup tracks promotion to a real column."
  - "api_keys table is scoped on workspace_id, NOT org_id — the plan's <interfaces> block called the column 'org_id' but the actual schema (database.py line 827) uses workspace_id. Code uses workspace_id; this is the correct path."
  - "idx_request_records_workspace_ts already exists at database.py:335 (CREATE INDEX IF NOT EXISTS idx_request_records_workspace_ts ON request_records(workspace_id, ts DESC)) — no second-named-index added per plan instruction."
  - "_resolve_current_cycle returns request_count=0 + calendar-month bounds for brand-new workspaces (no workspace_usage_cycles row yet) so /billing/summary's usage subobject is never absent."
metrics:
  duration: "~40 minutes"
  completed: "2026-04-25"
  tests_added: 17
  tests_total: 52
---

# Phase 10 Plan 01: Backend billing endpoints (usage + available_plans + api_keys + /usage/daily) Summary

GET /billing/summary now carries the three additive subobjects (usage, available_plans, api_keys) the Phase 10 sidebar meter, LockedPanel, and ApiKeysCard need; GET /billing/usage/daily is live and workspace-scoped, with the v1.2 ?cycle=previous stub returning the documented 400.

## Final handler signatures

```python
@router.get("/summary", response_model=BillingSummary)
async def billing_summary(token: TokenPayload = Depends(verify_token)) -> BillingSummary

@router.get("/usage/daily", response_model=UsageDailyResponse)
async def get_usage_daily(
    cycle: str = "current",
    token: TokenPayload = Depends(verify_token),
) -> UsageDailyResponse
```

## Cycle-bounds helper (for Plans 02/03/04 to search)

The shared paid-vs-free + brand-new-workspace resolver lives at:

- **Module:** `burnlens_cloud/billing.py`
- **Symbol:** `async def _resolve_current_cycle(workspace_id: str, plan: str) -> tuple[datetime, datetime, int]`
- **Returns:** `(cycle_start, cycle_end, request_count)`

Behavior:
- `plan == "free"`: reads workspace_usage_cycles row whose cycle_start matches `date_trunc('month', now() AT TIME ZONE 'UTC')`. Falls back to calendar-month bounds + 0.
- `plan != "free"` (paid): reads the most-recent workspace_usage_cycles row whose `cycle_end > NOW()`. Falls back to calendar-month bounds + 0 (matches Phase 9 ingest.py paid-fallback rationale: webhook may not have seeded yet).

Plans 02/03/04 should `grep "_resolve_current_cycle"` in `burnlens_cloud/billing.py`.

## Pricing constants (committed v1.0 path)

- **Module:** `burnlens_cloud/billing.py`
- **Symbols:** `_PLAN_PRICE_CENTS: dict[str, int] = {"cloud": 2900, "teams": 9900}` and `_PLAN_CURRENCY: str = "USD"`
- **No runtime column-existence branch was added.** The constants are the deterministic v1.0 path (per plan's Part A).
- **v1.2 followup:** `.planning/followups/v1.2-price-cents-column.md` tracks promotion to a real `plan_limits.price_cents` column.

## api_keys subobject (D-26)

Confirmed end-to-end: `summary.api_keys.active_count` and `summary.api_keys.limit` are populated correctly:

- **SQL:** `SELECT COUNT(*) AS n FROM api_keys WHERE workspace_id = $1 AND revoked_at IS NULL` (parameterized on `str(token.workspace_id)`).
- **Limit:** read from `resolve_limits(workspace_id).api_key_count` (None means unlimited).
- **Tests covering both:**
  - `test_summary_api_keys_active_count` (active_count counts non-revoked rows)
  - `test_summary_api_keys_workspace_isolation` (T-10-26: $1 is always WS_A, never WS_B)
  - `test_summary_api_keys_unlimited_plan` (limit=None when api_key_count is None)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] Plan's interfaces block named the api_keys workspace column "org_id"**

- **Found during:** Task 2, while writing the count SQL.
- **Issue:** The plan's `<interfaces>` block (lines 109–110 of 10-01-PLAN.md) describes the api_keys table as `api_keys(id, org_id, name, last4, key_hash, ...)`, and the action's example SQL (Part B step 5) uses `WHERE org_id = $1`. The actual schema in `burnlens_cloud/database.py:827` is `workspace_id UUID NOT NULL REFERENCES workspaces(id)` — there is no `org_id` column.
- **Fix:** Used `WHERE workspace_id = $1` in both Task-2 SQL sites (summary handler line ~723 and the unused helper that was later removed). All Phase 9 callers (api_keys_api.py:61) already use `workspace_id`, confirming this is the right column.
- **Files:** `burnlens_cloud/billing.py`
- **Commit:** c8833f2
- **Plan acceptance criterion regex impact:** the plan's regex `'FROM api_keys\s*WHERE org_id\s*=\s*\$1\s*AND revoked_at IS NULL'` does not match (org_id ≠ workspace_id). The functional intent (workspace-scoped count of non-revoked rows) is satisfied; flagging for Plan 10-04 awareness so any frontend consumer reading `api_keys.active_count` gets the right values.

**2. [Rule 1 — Test regression] Phase 7 /billing/summary tests broke when the handler started firing extra SELECTs**

- **Found during:** Task 2 verification.
- **Issue:** `tests/test_billing_webhook_phase7.py` had three /billing/summary tests using a single-shot `AsyncMock(return_value=[workspace_row])`. The extended handler now fires multiple SELECTs (workspaces, workspace_usage_cycles, plan_limits, api_keys). The single-shot mock returned the workspace row for every call → KeyError on cycle_start lookup. Also `test_billing_summary_scoped_to_caller` asserted `mock_query.call_count == 1`, which is no longer true.
- **Fix:** Rewired the three tests to use SQL-substring `side_effect` mocks that distinguish each SELECT, plus a `resolve_limits` patch returning a representative ResolvedLimits. The workspace-scoping invariant (the spirit of test 17) was preserved: now the test asserts that NO SQL call across the entire summary path may carry WS_B in its args.
- **Files:** `tests/test_billing_webhook_phase7.py`
- **Commit:** c8833f2

### Skipped (per plan instruction)

**1. Did not add a second `idx_request_records_workspace_ts` index**

- The index already existed at `burnlens_cloud/database.py:335` covering `(workspace_id, ts DESC)`. Plan Part D explicitly says: "If an equivalent index already exists (grep the file for idx_request_records), do nothing." The DESC ordering is fine for the daily aggregation (the planner uses `ORDER BY date`, not the underlying ts column).

## Verification Results

- `pytest tests/test_billing_usage.py -x`: **17/17 pass**
- `pytest tests/test_billing_webhook_phase7.py`: **18/18 pass** (no regression after rewiring)
- `pytest tests/test_billing_google.py`: **7/7 pass** (no regression)
- `pytest tests/test_ingest.py`: pass (no regression — ingest cycle helper unaffected)
- `pytest tests/test_auth.py`: pass (no regression)
- Total billing-adjacent: **52/52 pass**

`tests/test_plan_limits.py` (12 errors) is a pre-existing failure verified by `git stash` — needs live DATABASE_URL, unrelated to this plan.

## Threat Model Compliance

| Threat ID | Status | Evidence |
|-----------|--------|----------|
| T-10-01 (IDOR /usage/daily) | mitigated | `test_usage_daily_workspace_isolation` proves `?workspace_id=WS_B` is ignored; SQL `$1` is always `token.workspace_id` |
| T-10-02 (missing auth) | mitigated | `test_usage_daily_unauthenticated_returns_401` |
| T-10-03 (price leak) | accepted | available_plans contains only public Paddle prices |
| T-10-04 (DoS unbounded scan) | mitigated | cycle bounds are server-resolved, ≤31 days; existing index used |
| T-10-05 (plan injection) | accepted | `_PLAN_PRICE_CENTS` is module-level immutable; plan_limits seeded by repo-controlled migrations |
| T-10-06 (?cycle=previous timing oracle) | mitigated | 400 returned without DB read |
| T-10-26 (IDOR api_keys count) | mitigated | `test_summary_api_keys_workspace_isolation` proves $1 is always WS_A |

## Follow-ups / Awareness for downstream plans

- **Plan 10-02 (frontend BillingContext):** the new fields are `summary.usage`, `summary.available_plans`, `summary.api_keys`. All are nullable / default-empty so legacy callers don't break. The TypeScript type extension should mirror the Pydantic optionality.
- **Plan 10-03 (frontend Settings → Usage card):** consume `GET /billing/usage/daily` (no `?cycle` param for current cycle). The `daily[]` array is sorted ascending by date and may be empty (a fresh workspace with no records still gets `cap`/`current`/`cycle_start`/`cycle_end`).
- **Plan 10-04 (frontend ApiKeysCard):** read `summary.api_keys.active_count` and `summary.api_keys.limit` for the pre-emptive at-cap state. `limit === null` means unlimited (don't disable the Create button in that case).
- **Phase 8 mutation endpoints (`/change-plan`, `/cancel`, `/reactivate`):** their `_load_billing_summary` helper was NOT updated to populate the three new subobjects. The response_model is BillingSummary so the fields will serialize as `null/[]/null` post-mutation. Frontend BillingContext re-polls `/billing/summary` on a 30s cadence, so the eventual-consistency window is acceptable. If a future plan needs immediate values on mutation responses, extend `_load_billing_summary` to call the same helpers.

## Self-Check: PASSED

Files verified to exist:
- FOUND: `burnlens_cloud/models.py` (extended)
- FOUND: `burnlens_cloud/billing.py` (extended)
- FOUND: `tests/test_billing_usage.py` (created, 17 tests)

Commits verified to exist:
- FOUND: 0482442 — feat(10-01): add UsageCurrentCycle/AvailablePlan/ApiKeysSummary/UsageDaily models
- FOUND: c8833f2 — feat(10-01): extend /billing/summary + add GET /billing/usage/daily
