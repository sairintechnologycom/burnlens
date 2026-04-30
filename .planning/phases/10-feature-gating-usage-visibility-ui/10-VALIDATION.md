---
phase: 10
slug: feature-gating-usage-visibility-ui
status: compliant
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-30
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feature gating, usage visibility, and API Keys UI.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Backend framework** | pytest 7.x + pytest-asyncio |
| **Backend config** | `pyproject.toml` |
| **Frontend framework** | Playwright (`@playwright/test` ^1.59.1) |
| **Frontend config** | `frontend/playwright.config.ts` |
| **Backend quick run** | `pytest tests/test_billing_usage.py -x` |
| **Backend full run** | `pytest tests/test_billing_usage.py tests/test_billing_webhook_phase7.py -x` |
| **Frontend type check** | `cd frontend && npx tsc --noEmit` |
| **Frontend E2E quick run** | `cd frontend && npx playwright test tests/e2e/phase10_*.spec.ts --project=chromium` |
| **Frontend E2E full run** | `cd frontend && npx playwright test --project=chromium` |
| **Estimated backend runtime** | ~8 seconds |
| **Estimated E2E runtime** | ~30 seconds |

---

## Sampling Rate

- **After every backend task commit:** `pytest tests/test_billing_usage.py -x`
- **After every frontend task commit:** `cd frontend && npx tsc --noEmit`
- **After every plan wave:** backend full run + E2E quick run
- **Before `/gsd-verify-work`:** all suites must be green
- **Max feedback latency:** ~40 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 10-01-01 | 01 | 1 | METER-01/02/03 (Pydantic models) | — | N/A | unit | `pytest tests/test_billing_usage.py -x -k "models or shape"` | ✅ | ✅ green |
| 10-01-02 | 01 | 1 | METER-01 (`/billing/summary` usage subobject) | T-10-26 | `api_keys.active_count` scoped by `token.workspace_id` | unit | `pytest tests/test_billing_usage.py -x -k "summary"` | ✅ | ✅ green |
| 10-01-03 | 01 | 1 | METER-03 (`/billing/usage/daily`) | T-10-01 | Daily query binds workspace_id from token — never from caller-supplied params | unit | `pytest tests/test_billing_usage.py -x -k "daily"` | ✅ | ✅ green |
| 10-01-04 | 01 | 1 | METER-03 (workspace isolation) | T-10-01 | test_usage_daily_workspace_isolation: cross-tenant rows never returned | unit | `pytest tests/test_billing_usage.py::test_usage_daily_workspace_isolation -x` | ✅ | ✅ green |
| 10-01-05 | 01 | 1 | D-26 (api_keys isolation) | T-10-26 | test_summary_api_keys_workspace_isolation: count never crosses orgs | unit | `pytest tests/test_billing_usage.py::test_summary_api_keys_workspace_isolation -x` | ✅ | ✅ green |
| 10-01-06 | 01 | 1 | METER-01 (unauthenticated) | T-10-02 | `/billing/usage/daily` returns 401 without valid token | unit | `pytest tests/test_billing_usage.py::test_usage_daily_unauthenticated_returns_401 -x` | ✅ | ✅ green |
| 10-02-01 | 02 | 2 | METER-01 (sidebar meter DOM) | T-10-07 | UsageMeter renders values as React text children — no raw HTML injection | E2E | `cd frontend && npx playwright test tests/e2e/phase10_meter.spec.ts --project=chromium` | ✅ | ✅ green |
| 10-02-02 | 02 | 2 | METER-02 (threshold coloring) | T-10-11 | CSS class `.usage-meter-fill--amber/red` applied at 80%/100% | E2E | `cd frontend && npx playwright test tests/e2e/phase10_meter.spec.ts --project=chromium` | ✅ | ✅ green |
| 10-02-03 | 02 | 2 | GATE-01..03 (frontend types) | T-10-08 | TypeScript enforces `planSatisfies` call-sites at compile time | type-check | `cd frontend && npx tsc --noEmit` | ✅ | ✅ green |
| 10-03-01 | 03 | 3 | GATE-01 (`/teams` locked on 402) | T-10-12 | 402 body strings rendered as React text children (auto-escaped XSS mitigation) | E2E | `cd frontend && npx playwright test tests/e2e/phase10_gating.spec.ts --project=chromium` | ✅ | ✅ green |
| 10-03-02 | 03 | 3 | GATE-03 (`/customers` locked on 402) | T-10-13 | CTA calls startCheckout directly — never consumes upgrade_url from 402 (open-redirect closed) | E2E | `cd frontend && npx playwright test tests/e2e/phase10_gating.spec.ts --project=chromium` | ✅ | ✅ green |
| 10-03-03 | 03 | 3 | GATE-02 (Teams-tier unlocked) | — | LockedPanel dialog absent when teams endpoint returns 200 | E2E | `cd frontend && npx playwright test tests/e2e/phase10_gating.spec.ts --project=chromium` | ✅ | ✅ green |
| 10-04-01 | 04 | 4 | METER-03 (UsageCard `#usage` anchor) | — | `/settings#usage` anchor mounted so sidebar meter click lands correctly | E2E | `cd frontend && npx playwright test tests/e2e/phase10_settings.spec.ts --project=chromium` | ✅ | ✅ green |
| 10-04-02 | 04 | 4 | D-26 (pre-emptive at-cap disabled) | T-10-20 | "Create key" disabled from `billing.api_keys` before any 402 seen | E2E | `cd frontend && npx playwright test tests/e2e/phase10_settings.spec.ts --project=chromium` | ✅ | ✅ green |
| 10-04-03 | 04 | 4 | D-24 (NewApiKeyModal blocking) | T-10-17/T-10-18 | Escape key does NOT dismiss modal; plaintext cleared only on primary dismiss | E2E | `cd frontend && npx playwright test tests/e2e/phase10_settings.spec.ts --project=chromium` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements.

- `tests/test_billing_usage.py` — 17 backend tests (Plan 01)
- `tests/test_billing_webhook_phase7.py` — 18 regression tests (rewired in Plan 01)
- `frontend/tests/e2e/phase10_meter.spec.ts` — 2 E2E tests (Plan 02)
- `frontend/tests/e2e/phase10_gating.spec.ts` — 3 E2E tests (Plan 03)
- `frontend/tests/e2e/phase10_settings.spec.ts` — 4 E2E tests (Plan 04)
- `frontend/playwright.config.ts` — pre-existing Playwright config
- `frontend/tests/e2e/test-utils.ts` — `authenticatedPage` fixture with route mock support

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Frosted-glass visual quality on `/teams` + `/customers` | GATE-01/02/03 | CSS blur depth and opacity are qualitative — no programmatic assertion for perceived rendering quality | Log in as free-tier user; navigate to `/teams`. Verify skeleton is visible but blurred/translucent behind overlay card. Repeat on `/customers`. |
| Paddle checkout overlay launches on LockedPanel CTA click | GATE-01/02/03, D-04 | Requires live Paddle sandbox session + `NEXT_PUBLIC_PADDLE_CLIENT_TOKEN`; checkout iframe cannot be reliably asserted in mocked E2E | In staging with live Paddle token: click "Upgrade to Teams" CTA on `/teams`; verify Paddle checkout iframe opens with correct plan. |
| Usage meter color visual confirmation | METER-02 | CSS class asserted programmatically; human eye confirms `--cyan`, `--amber`, `--red` tokens render correctly against dark/light themes | In dashboard with seeded usage data at 50%, 85%, 110%: verify bar color matches design spec green→amber→red. |
| Over-quota overflow label format | METER-01/METER-02 | Requires seeded workspace data exceeding cap | Seed workspace with `request_count > monthly_request_cap`; verify sidebar label shows `"{over} / {cap} ({pct}%)"`. |
| Hash-anchor scroll on meter click | METER-03 | E2E asserts `#usage` anchor presence but not scroll behavior in headless mode | Click sidebar usage meter in running browser; verify page scrolls to Usage card in Settings. |

---

## Validation Audit 2026-04-30

| Metric | Count |
|--------|-------|
| Gaps found | 6 |
| Resolved (automated) | 6 |
| Escalated to manual-only | 0 |
| E2E tests written | 9 (Playwright) |
| Pre-existing backend tests | 17 (pytest) |

---

## Validation Sign-Off

- [x] All tasks have automated verify
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 40s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-04-30
