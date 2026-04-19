---
phase: 07-paddle-lifecycle-sync
plan: 02
subsystem: burnlens_cloud.billing
status: complete
tags: [paddle, webhooks, fastapi, pydantic, security, billing]
requirements:
  - PDL-01
  - PDL-02
  - PDL-03
  - BILL-01
  - BILL-02
dependency_graph:
  requires:
    - burnlens_cloud/database.py — paddle_events table + workspaces lifecycle columns (Plan 07-01)
    - burnlens_cloud/database.py — plan_limits.paddle_price_id seed (Phase 6)
    - burnlens_cloud/auth.py::verify_token — workspace-scoped JWT dependency
    - burnlens_cloud/database.py::execute_query / execute_insert — asyncpg wrappers
  provides:
    - burnlens_cloud/models.py::BillingSummary — Pydantic response model
    - burnlens_cloud/billing.py::_plan_from_price_id — async, DB-first, env fallback
    - burnlens_cloud/billing.py::_handle_payment_failed — new past_due handler (D-21)
    - burnlens_cloud/billing.py::billing_summary — GET /billing/summary endpoint
    - burnlens_cloud/billing.py field-extraction helpers — _parse_iso, _extract_period_end, _extract_trial_end, _extract_cancel_at_period_end, _extract_price, _extract_price_id
    - webhook dedup via INSERT ... ON CONFLICT (event_id) DO NOTHING RETURNING
    - HTTP 401 signature-rejection contract (ROADMAP SC-1)
  affects:
    - Phase 7 Plan 03 (frontend billing context + Settings card) — will poll GET /billing/summary
    - Phase 7 Plan 04 (past_due banner) — reads billing.status from /billing/summary
    - Phase 8 (self-serve cancel/reactivate) — extends the webhook handlers; /summary contract stays
tech_stack:
  added: []
  patterns:
    - Webhook dedup via PRIMARY KEY + ON CONFLICT DO NOTHING RETURNING
    - Fail-soft Paddle payload extraction (all helpers return None/False on KeyError/TypeError/ValueError)
    - Handler-exception silent success (200 + paddle_events.error write, D-11)
    - DB-first plan lookup (plan_limits.paddle_price_id) with env-var fallback
    - Workspace-scoped endpoint via Depends(verify_token)
    - Explicit $3::jsonb cast because no asyncpg JSONB codec is registered
key_files:
  created:
    - tests/test_billing_webhook_phase7.py  # 18 async pytest cases
  modified:
    - burnlens_cloud/models.py  # +22 lines (BillingSummary)
    - burnlens_cloud/billing.py  # +200 net (5 in-order edits)
    - .gitignore  # +2 lines (test env stub)
decisions:
  - "SC-1: signature rejection returns HTTP 401 (not 400) for all four failure modes (missing / malformed / stale / bad-HMAC)"
  - "Missing event_id after signature verification keeps HTTP 400 — it is a malformed envelope error, not a signature rejection (pins the split in tests)"
  - "$3::jsonb explicit cast on the paddle_events INSERT because no asyncpg set_type_codec('jsonb', ...) is registered on the pool"
  - "_plan_from_price_id is async + DB-first; every caller was converted to await (2 call sites: activated + updated handlers)"
  - "_handle_subscription_canceled left untouched — existing body already sets plan='free', subscription_status='canceled', matching D-22/D-23"
  - "subscription.paused routed to _handle_subscription_canceled (D-23)"
  - "Handler exceptions still return 200; paddle_events.error captures the exception message (D-11 silent-success invariant)"
  - "/billing/summary defaults status to 'active' when subscription_status is NULL (legacy workspaces)"
metrics:
  duration: ~15 minutes
  completed_date: 2026-04-19
  tasks_completed: 3
  commits: 3
  lines_added: ~245
  lines_removed: ~23
  tests_added: 18
  tests_passing: 18
---

# Phase 7 Plan 02: Paddle Lifecycle Webhook + Billing Summary Endpoint

Extended `burnlens_cloud/billing.py` so Paddle webhook events are the authoritative source of each workspace's plan and subscription state, and added a workspace-scoped `GET /billing/summary` endpoint that reads from the Postgres cache populated by those webhooks. The plan delivered the full backend contract that Plans 03 and 04 will consume on the frontend — zero Paddle API round-trips on the read path.

## What Was Built

### Task 1 — `BillingSummary` Pydantic model (commit `83a1739`)

Read-only response model appended to `burnlens_cloud/models.py` immediately after `BillingPortalResponse`. Fields mirror the Paddle-populated columns on `workspaces`:

```python
class BillingSummary(BaseModel):
    plan: str
    price_cents: Optional[int] = None
    currency: Optional[str] = None
    status: str
    trial_ends_at: Optional[datetime] = None
    current_period_ends_at: Optional[datetime] = None
    cancel_at_period_end: bool = False
```

`status` is kept as a plain `str` (not `Literal`) for forward-compat per D-16. `datetime` / `Optional` were already imported at the top of models.py — no new imports.

### Task 2 — `burnlens_cloud/billing.py` refactor (commit `4eef0d8`)

Five in-order edits inside a single commit:

**Edit A — imports.** Added `from datetime import datetime` and `from .models import BillingSummary` alongside the existing imports. `Any` / `Optional` remained (needed by `_parse_iso` and helper return types).

**Edit B — async `_plan_from_price_id`.** The former sync function (env-only lookup) became async and queries `plan_limits.paddle_price_id` first, falling back to env vars only when the Phase 6 seed has not landed in the environment:

```python
async def _plan_from_price_id(price_id: str) -> str:
    if not price_id:
        return "free"
    rows = await execute_query(
        "SELECT plan FROM plan_limits WHERE paddle_price_id = $1",
        price_id,
    )
    if rows:
        return rows[0]["plan"]
    if price_id == settings.paddle_cloud_price_id:
        return "cloud"
    if price_id == settings.paddle_teams_price_id:
        return "teams"
    return "free"
```

Every call site inside `_handle_subscription_activated` and `_handle_subscription_updated` was converted to `await`. `grep -c "_plan_from_price_id"` yields 3; `grep -c "await _plan_from_price_id"` yields 2 (the `+1` is the async def line itself). No `asyncio.run` bridge was introduced.

**Edit C — fail-soft extraction helpers.** Six helpers added below `_plan_from_price_id`:

| Helper | Returns on success | Returns on malformed payload |
|---|---|---|
| `_parse_iso(value)` | `datetime` | `None` |
| `_extract_period_end(data)` | `datetime` | `None` |
| `_extract_trial_end(data)` | `datetime` | `None` |
| `_extract_cancel_at_period_end(data)` | `bool` | `False` |
| `_extract_price(data)` | `(int, str)` | `(None, None)` |
| `_extract_price_id(data)` | `str` | `None` |

Every helper is wrapped in try/except so a malformed Paddle payload cannot crash the dispatch loop (D-11 silent-success is preserved at the field level too).

**Edit D — webhook dispatch rewrite + HTTP 401 for signature rejection.** Three things happened here:

1. **SC-1 enforcement.** The existing `HTTPException(status_code=400, detail="Invalid signature")` became `status_code=401`. A pre-check now raises `401 Missing signature` when the header is absent, before any HMAC work. The surviving 400s in `paddle_webhook` are solely for `Invalid JSON` (body parse) and `Missing event_id` (post-signature envelope) — these are malformed-client errors, not signature rejections.

2. **Dedup via `INSERT ... ON CONFLICT`.** The dispatch body now does:
   ```sql
   INSERT INTO paddle_events (event_id, event_type, payload)
   VALUES ($1, $2, $3::jsonb)
   ON CONFLICT (event_id) DO NOTHING
   RETURNING event_id
   ```
   The `$3::jsonb` cast is needed because `burnlens_cloud/database.py` does NOT register a JSONB codec on the asyncpg pool (verified by `grep -E "set_type_codec|init=.*json"` returning no matches). If the INSERT returns no row, the endpoint returns `{"received": True, "deduped": True}` and the handler does not run again.

3. **Handler dispatch + audit write.** After dedup clears, the event is routed:
   - `subscription.activated` → `_handle_subscription_activated`
   - `subscription.updated` → `_handle_subscription_updated`
   - `subscription.canceled` OR `subscription.paused` → `_handle_subscription_canceled` (D-23)
   - `transaction.payment_failed` → `_handle_payment_failed` (new)
   - Anything else → logged debug, no write

   On handler success: `UPDATE paddle_events SET processed_at = now() WHERE event_id = $1`.
   On handler exception: the webhook still returns 200, and `UPDATE paddle_events SET error = $1 WHERE event_id = $2` captures the exception message (D-11).

4. **Handler extensions.** `_handle_subscription_activated` now sets 9 columns (plan, customer_id, subscription_id, status, trial_ends_at, current_period_ends_at, cancel_at_period_end, price_cents, currency) and `_handle_subscription_updated` sets 7 (plan, status, trial_ends_at, current_period_ends_at, cancel_at_period_end, price_cents, currency). `_handle_subscription_canceled` was deliberately NOT touched — its existing body already sets `plan='free'` and `subscription_status='canceled'`, matching D-22/D-23. A new `_handle_payment_failed` was added.

**Edit E — `GET /billing/summary`.** Appended at the bottom of `billing.py`:

```python
@router.get("/summary", response_model=BillingSummary)
async def billing_summary(token: TokenPayload = Depends(verify_token)):
    rows = await execute_query(
        """
        SELECT plan, price_cents, currency, subscription_status,
               trial_ends_at, current_period_ends_at, cancel_at_period_end
        FROM workspaces
        WHERE id = $1
        """,
        str(token.workspace_id),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Workspace not found")
    row = rows[0]
    return BillingSummary(
        plan=row["plan"],
        price_cents=row["price_cents"],
        currency=row["currency"],
        status=row["subscription_status"] or "active",
        trial_ends_at=row["trial_ends_at"],
        current_period_ends_at=row["current_period_ends_at"],
        cancel_at_period_end=bool(row["cancel_at_period_end"])
            if row["cancel_at_period_end"] is not None else False,
    )
```

### Task 3 — Pytest suite (commit `85c8bd2`)

18 async test cases in `tests/test_billing_webhook_phase7.py` covering:

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_webhook_rejects_missing_signature` | 401 — no `Paddle-Signature` header |
| 2 | `test_webhook_rejects_malformed_signature` | 401 — garbage header (no `ts=`/`h1=`) |
| 3 | `test_webhook_rejects_bad_signature` | 401 — well-formed header, wrong HMAC |
| 4 | `test_webhook_rejects_stale_signature` | 401 — valid HMAC for 400s-old `ts` |
| 5 | `test_webhook_rejects_missing_event_id` | **400** — signature passes, envelope lacks event_id |
| 6 | `test_webhook_dedup_returns_early` | `{"received":true,"deduped":true}`, handler not invoked |
| 7 | `test_subscription_activated_populates_all_columns` | UPDATE with 10 bound params matching plan/customer/sub/status/trial/period/cancel/price/currency/workspace_id |
| 8 | `test_subscription_updated_past_due_flips_status` | `subscription_status='past_due'`, plan unchanged |
| 9 | `test_subscription_canceled_downgrades_to_free` | `plan='free'`, `subscription_status='canceled'`, bound by `paddle_subscription_id` |
| 10 | `test_subscription_paused_downgrades_to_free` | Same UPDATE fires for `subscription.paused` (D-23) |
| 11 | `test_transaction_payment_failed_flips_past_due` | `subscription_status='past_due'`, no `plan` in SET clause, matched by `paddle_subscription_id` |
| 12 | `test_handler_exception_writes_error_column` | 200 returned + `UPDATE paddle_events SET error = $1 WHERE event_id = $2` |
| 13 | `test_plan_from_price_id_uses_db_first` | Returns `teams` from mocked `plan_limits` lookup |
| 14 | `test_plan_from_price_id_env_fallback` | env-cloud/env-teams/unknown → cloud/teams/free |
| 15 | `test_billing_summary_returns_workspace_data` | JSON shape + all 7 fields populated from mocked row |
| 16 | `test_billing_summary_rejects_unauth` | 401 — missing `Authorization` header |
| 17 | `test_billing_summary_scoped_to_caller` | SELECT binds only caller's workspace_id; WS_B never queried |
| 18 | `test_billing_summary_defaults_status_active_when_null` | `subscription_status=None` → response `status='active'` |

All tests mock `burnlens_cloud.billing.execute_query` / `execute_insert` directly — no real Postgres needed. No test imports asyncpg; none call `init_db()`.

### Final command pytest run

```
tests/test_billing_webhook_phase7.py ..................  [100%]
18 passed, 2 warnings in 0.50s
```

## Handler → Column Mapping (D-03, D-21, D-22, D-23)

| Event | Handler | SQL shape | Plan change? | Status set to |
|-------|---------|-----------|--------------|---------------|
| `subscription.activated` | `_handle_subscription_activated` | UPDATE workspaces SET plan, paddle_customer_id, paddle_subscription_id, subscription_status, trial_ends_at, current_period_ends_at, cancel_at_period_end, price_cents, currency WHERE id | Yes (DB-looked-up) | payload.status (`active` or `trialing`) |
| `subscription.updated` | `_handle_subscription_updated` | UPDATE workspaces SET plan, subscription_status, trial_ends_at, current_period_ends_at, cancel_at_period_end, price_cents, currency WHERE paddle_subscription_id | Yes (DB-looked-up) | payload.status |
| `subscription.canceled` | `_handle_subscription_canceled` | UPDATE workspaces SET plan='free', subscription_status='canceled' WHERE paddle_subscription_id | Yes → `free` | `canceled` |
| `subscription.paused` | `_handle_subscription_canceled` (D-23) | Identical | Yes → `free` | `canceled` |
| `transaction.payment_failed` | `_handle_payment_failed` | UPDATE workspaces SET subscription_status='past_due' WHERE paddle_subscription_id | **No** (D-21) | `past_due` |

## New Contract: `GET /billing/summary`

| Property | Value |
|---|---|
| Method | GET |
| Path | `/billing/summary` |
| Auth | `Authorization: Bearer <JWT>` via `Depends(verify_token)` |
| Scope | Caller's workspace only (`WHERE id = $1` bound to `token.workspace_id`) |
| Request body | None |
| Response model | `BillingSummary` |
| Response shape | `{plan, price_cents, currency, status, trial_ends_at, current_period_ends_at, cancel_at_period_end}` |
| Backend cost | 1 indexed Postgres lookup — no Paddle API round-trip |
| Polling pattern | Frontend polls every 30s (and on focus) per D-18 |
| NULL status fallback | Response `status='active'` when row's `subscription_status IS NULL` |

## Status-Code Split (locked by test #5)

| Condition | HTTP code | Path |
|---|---|---|
| Missing `Paddle-Signature` | **401** | signature rejection (ROADMAP SC-1) |
| Malformed `Paddle-Signature` (no `ts=`/`h1=`) | **401** | signature rejection |
| Stale timestamp (>300s) | **401** | signature rejection |
| HMAC mismatch | **401** | signature rejection |
| Valid signature but JSON body unparseable | 400 | `Invalid JSON` |
| Valid signature, valid JSON, no `event_id` | 400 | `Missing event_id` |
| Valid signature + envelope, duplicate event_id | 200 | `{received: true, deduped: true}` |
| Valid signature + envelope, handler throws | 200 | `{received: true}` (error recorded in paddle_events.error) |
| Valid signature + envelope, handler succeeds | 200 | `{received: true}` |

## Deviations from Plan

**1. [Rule 3 — Blocking] Test harness needed dotenv isolation**
- **Found during:** Task 3 initial test run.
- **Issue:** The project root `.env` is authored for the BurnLens proxy (OPENAI_API_KEY, ANTHROPIC_API_KEY, OPENAI_BASE_URL, etc.). `burnlens_cloud/config.py::Settings` (pydantic-settings 2.7) rejects those as `extra_forbidden` at import time, which prevented any test that imports `burnlens_cloud.billing` from collecting.
- **Fix:** Added a pre-import shim at the top of `tests/test_billing_webhook_phase7.py` that monkeypatches `pydantic_settings.sources.dotenv_values` to return `{}` for the duration of the test module. A 0-byte `tests/_phase7_billing_test.env` stub is created to satisfy any path-existence check. Runtime behavior in production is unchanged — the patch only affects the in-process Settings instantiation during this test module.
- **Files modified:** `tests/test_billing_webhook_phase7.py`, `.gitignore` (ignore the generated stub).
- **Commit:** `85c8bd2`.

No other deviations — plan executed exactly as specified. Every grep-based acceptance criterion in Tasks 1, 2, and 3 passed on the first run after the five edits landed.

## Threat Flags

None — every mitigation in the plan's threat register (T-07-06 through T-07-13) is implemented and covered by a test:

- **T-07-06 (Spoofing):** `_verify_signature` call preserved before any DB write; tests 1-4 pin HTTP 401 for all four failure modes.
- **T-07-07 (Tampering):** HMAC bound to raw body bytes; any byte flip invalidates `h1`. Test 3 covers this via wrong-HMAC case.
- **T-07-08 (Replay):** `event_id` PRIMARY KEY + ON CONFLICT DO NOTHING RETURNING; test 6 proves the second delivery returns `deduped: true` without handler rerun.
- **T-07-09 (Timing attack):** `hmac.compare_digest` in `_verify_signature` unchanged.
- **T-07-10 (Cross-tenant disclosure):** `/billing/summary` binds `WHERE id = $1` to `token.workspace_id`; test 17 pins this.
- **T-07-11 (DoS via handler retries):** try/except returns 200 + writes to paddle_events.error; test 12 pins this.
- **T-07-12 (Broken access control):** `Depends(verify_token)` required at route; test 16 pins 401 on missing Authorization.
- **T-07-13 (SQL injection):** All UPDATE/SELECT statements parameterised via asyncpg binds. No f-strings or `%` concatenation added.

## Known Stubs

None — every code path introduced by this plan is wired to real behavior. The `_handle_subscription_canceled` handler was intentionally left untouched (it already satisfies D-22/D-23 correctly).

## Self-Check: PASSED

- [x] `burnlens_cloud/models.py` modified — `BillingSummary` class present, imports cleanly.
- [x] `burnlens_cloud/billing.py` modified — `ast.parse` exits 0.
- [x] `tests/test_billing_webhook_phase7.py` created — 18 async test cases, `ast.parse` exits 0.
- [x] Commit `83a1739` exists: `feat(phase-7-02): add BillingSummary pydantic model`.
- [x] Commit `4eef0d8` exists: `feat(phase-7-02): paddle webhook dedup + extended handlers + billing summary`.
- [x] Commit `85c8bd2` exists: `test(phase-7-02): add 18-case pytest suite for paddle webhook + billing summary`.
- [x] `python -m pytest tests/test_billing_webhook_phase7.py -q` → **18 passed, 2 warnings in 0.50s**.
- [x] `grep -c "ON CONFLICT (event_id) DO NOTHING" burnlens_cloud/billing.py` → 1.
- [x] `grep -c "@router.get(\"/summary\"" burnlens_cloud/billing.py` → 1.
- [x] `grep -c "response_model=BillingSummary" burnlens_cloud/billing.py` → 1.
- [x] `grep -c "Depends(verify_token)" burnlens_cloud/billing.py` → 3 (checkout, portal, summary).
- [x] `grep -c "status_code=401" burnlens_cloud/billing.py` → 2 (missing + invalid signature).
- [x] Await invariant: `TOTAL=3 AWAITED=2` (3 == 2+1, the `+1` is the async def line).
- [x] No `asyncio.run` bridge: `grep -c "asyncio.run" burnlens_cloud/billing.py` → 0.
- [x] No new import of `asyncpg` in tests; no `init_db()` call in tests.
- [x] All 18 test names start with `test_` and sit at module scope.
- [x] Test file asserts 401 × 5 (one extra for `/billing/summary` unauth) and 400 × 1 (missing event_id).
- [x] Scope kept tight — only the three files listed in `files_modified` plus `.gitignore` (for the test env stub).
