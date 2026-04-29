---
phase: 08-billing-self-service
slug: billing-self-service
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-29
audited: 2026-04-29
---

# Phase 8 — Validation Strategy

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/test_phase08_billing.py -q` |
| **Full suite command** | `uv run pytest tests/test_phase08_billing.py tests/test_billing_webhook_phase7.py tests/test_billing_usage.py -q` |
| **Estimated runtime** | ~1 second |

---

## Sampling Rate

- **After every task commit:** `uv run pytest tests/test_phase08_billing.py -q`
- **After every plan wave:** full suite command above
- **Before `/gsd-verify-work`:** full suite must be green
- **Max feedback latency:** ~1 second

---

## Per-Task Verification Map

| Task ID | Plan | Requirement | Behavior | Test Type | Automated Command | Status |
|---------|------|-------------|----------|-----------|-------------------|--------|
| 08-01 | 01 | BILL-05 | `cancellation_surveys` table exists with correct columns | unit | `uv run pytest tests/test_phase08_billing.py::TestCancelBodyValidation -q` | ✅ green |
| 08-02 | 02 | BILL-03/05/06 | `ChangePlanBody` allowlist + case-norm; `CancelBody` optional fields + length caps | unit | `uv run pytest tests/test_phase08_billing.py::TestChangePlanBodyValidation tests/test_phase08_billing.py::TestCancelBodyValidation -q` | ✅ green |
| 08-03 | 03 | BILL-03 | `POST /billing/change-plan` — upgrade, downgrade, idempotent, 400s, 502s | unit | `uv run pytest tests/test_phase08_billing.py -k "change_plan" -q` | ✅ green |
| 08-04 | 04 | BILL-05 | `POST /billing/cancel` — idempotent, free-plan 400, survey write, 502 | unit | `uv run pytest tests/test_phase08_billing.py -k "cancel" -q` | ✅ green |
| 08-05 | 05 | BILL-06 | `POST /billing/reactivate` — period-ended 400, status-canceled 400, happy path, 502 | unit | `uv run pytest tests/test_phase08_billing.py -k "reactivate" -q` | ✅ green |
| 08-06 | 06 | BILL-04 | `GET /billing/invoices` — free-empty, PDF fail-soft, 502 | unit | `uv run pytest tests/test_phase08_billing.py -k "invoices" -q` | ✅ green |
| 08-07 | 07 | BILL-03 | Paddle checkout hook (Phase 7 webhook path) | unit | covered by `test_billing_webhook_phase7.py` | ✅ green |
| 08-08 | 08 | BILL-03/05/06 | `BillingContext.setBilling` — mutation endpoints return fresh BillingSummary | unit | `uv run pytest tests/test_phase08_billing.py -k "upgrade or downgrade or happy_path" -q` | ✅ green |
| 08-09 | 09 | BILL-05 | Cancel modal renders D-08 copy + D-10 radios | manual | — | ✅ human UAT |
| 08-10 | 10 | BILL-04 | InvoicesCard 24-row table with Date/Amount/Status/Download | manual | — | ✅ human UAT |
| 08-11 | 11 | BILL-03 | PlanPickerModal side-by-side from `/billing/plans` | unit + manual | `uv run pytest tests/test_phase08_billing.py -k "plans" -q` | ✅ green |
| 08-12 | 12 | BILL-03/04/05/06 | Settings billing wiring — all cards mounted, W1 pending-downgrade render | manual | — | ✅ human UAT |

---

## Coverage Detail

### Tests written: `tests/test_phase08_billing.py` (36 tests)

**Model validation (8 tests)**
- `ChangePlanBody` accepts "cloud", "teams", uppercase → normalizes
- `ChangePlanBody` rejects "free", "enterprise", ""
- `CancelBody` empty body OK
- `CancelBody` with reason_code, reason_text
- `CancelBody` rejects reason_code > 64 chars, reason_text > 1000 chars

**POST /billing/change-plan (8 tests)**
- 401 unauthenticated
- Idempotent no-op (current == target)
- 400 target_plan="free"
- 400 no active subscription
- Cloud→Teams upgrade: Paddle PATCH with `prorated_immediately`, plan updated, `scheduled_plan` cleared
- Teams→Cloud downgrade: Paddle PATCH with `next_billing_period`, `scheduled_plan`+`scheduled_change_at` written
- Paddle 5xx → 502, DB NOT mutated
- Paddle timeout → 502, DB NOT mutated

**POST /billing/cancel (6 tests)**
- 401 unauthenticated
- Idempotent (already `cancel_at_period_end=true`)
- 400 free plan / no subscription
- Happy path with survey body → `cancel_at_period_end=true`, survey insert attempted
- Happy path without body → no survey insert
- Paddle 5xx → 502

**POST /billing/reactivate (6 tests)**
- 401 unauthenticated
- Idempotent (`cancel_at_period_end=false`)
- 400 period already ended
- 400 `subscription_status=canceled`
- Happy path: Paddle PATCH `scheduled_change=null`, `cancel_at_period_end=false` written
- Paddle 5xx → 502

**GET /billing/invoices (4 tests)**
- 401 unauthenticated
- Free workspace (no `paddle_customer_id`) → `{"invoices": []}`
- 2 transactions: PDF succeeds for one, times out for other → both rows returned, one `null` pdf_url
- Paddle list 5xx → 502

**GET /billing/plans (4 tests)**
- 401 unauthenticated
- Returns cloud+teams rows from `plan_limits`
- Empty DB → `{"plans": []}`
- `gated_features` as string JSONB → parsed to dict

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Free→Cloud upgrade via Paddle overlay | BILL-03 | Needs live Paddle sandbox + browser interaction | Open Settings, click Upgrade, complete sandbox checkout, verify plan flips within 60s |
| Cloud→Teams prorated upgrade (live sub) | BILL-03 | Requires live Paddle subscription + prorate-now behaviour is Paddle UX | Use sandbox Teams sub, PATCH via settings, verify immediate prorate charge |
| Teams→Cloud scheduled downgrade | BILL-03 | End-to-end W1 pending-downgrade render with real Paddle payload | Verify "Pending downgrade to Cloud on {date}" info line renders |
| Cancel + end-date display | BILL-05 | Visual copy check + cross-module: modal→endpoint→DB→UI flip | Cancel via modal, verify amber message + Resume button appear |
| Reactivate before period end | BILL-06 | Requires cancelled-but-not-ended Paddle subscription | Reactivate, verify Cancel button re-appears, toast shows "Subscription resumed" |
| Invoices PDF download opens new tab | BILL-04 | Signed URL validity + new-tab is browser UX | Click Download, verify Paddle-hosted PDF opens in new tab |
| Cancel modal exact copy (D-08 + D-10) | BILL-05 | Visual verification of copy strings | Check modal header, body, 5 radio labels match spec verbatim |
| Paddle 5xx error toast contains support email | BILL-03/05/06 | UI copy assertion | Force Paddle 5xx, verify toast includes "support@burnlens.app" |

---

## Validation Audit 2026-04-29

| Metric | Count |
|--------|-------|
| Gaps found | 8 |
| Automated (resolved) | 36 tests across 5 endpoints + 2 model classes |
| Manual-only | 8 (Paddle live-sandbox behaviours) |
| Escalated | 0 |

---

## Validation Sign-Off

- [x] All tasks have automated verify or manual-only entry
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 not needed — existing pytest infrastructure used
- [x] No watch-mode flags
- [x] Feedback latency < 2s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-04-29
