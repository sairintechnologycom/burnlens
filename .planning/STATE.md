---
gsd_state_version: 1.0
milestone: v1.2
milestone_name: Account Security & Notifications
status: planned
last_updated: "2026-05-02T10:50:00.000Z"
last_activity: 2026-05-02 — Phase 11 (Auth Essentials) planning complete — 7 execute plans created
progress:
  total_phases: 3
  completed_phases: 0
  total_plans: 7
  completed_plans: 0
---

# State

## Current Position

Phase: 11 — Auth Essentials (planned, not yet executed)
Plan: —
Status: Phase 11 planning complete — 7 execute plans ready (01, 02, 03a, 03b, 04, 05a, 05b)
Last activity: 2026-05-02 — Phase 11 plans written and verified

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-30 after v1.2 milestone start)

**Core value:** Complete visibility into AI API spending with zero code changes
**Current focus:** v1.2 Account Security & Notifications

## v1.2 Phase Summary

| # | Phase | Requirements | Status |
|---|-------|-------------|--------|
| 11 | Auth Essentials | AUTH-01–07, EMAIL-01–04 (11 reqs) | Planned — 7 plans ready |
| 12 | Cloud Alert Engine | ALERT-01–07 (7 reqs) | Not started |
| 13 | Alert Management UI | ALERT-08–09 (2 reqs) | Not started |

## v1.1 Phase Summary

| # | Phase | Status |
|---|-------|--------|
| 6 | Plan Limits Foundation | ✓ Complete (2026-04-18) |
| 7 | Paddle Lifecycle Sync | ✓ Complete (2026-04-19) |
| 8 | Billing Self-Service | ✓ Complete (2026-04-20) |
| 9 | Quota Tracking & Soft Enforcement | ✓ Complete (2026-04-29) |
| 10 | Feature Gating & Usage Visibility UI | ✓ Complete (2026-04-27) |

## Deferred Items

Items acknowledged and deferred at milestone close on 2026-04-30:

| Category | Item | Status |
|----------|------|--------|
| human_uat | Phase 7 — 5 live Paddle sandbox tests (webhook delivery, 60s SLA, banner sweep, card states, checkout-success) | deferred |
| human_uat | Phase 8 — 8 live Paddle/browser tests (upgrade overlay, downgrade prorate, cancel modal, reactivate, invoices PDF, 502 toast, PlanPickerModal) | deferred |
| human_uat | Phase 9 — 3 manual verifications (live SMTP delivery, daily 03:00 UTC prune tick, cold-start lifespan count) | deferred |
| human_uat | Phase 10 — rate-limit related Playwright specs not completed | deferred |
| tech_debt | Phase 6 — test_plan_limits.py missing dotenv isolation shim (3-line fix) | deferred |
| tech_debt | Phase 9 — VERIFICATION.md absent (covered by VALIDATION.md + 36 passing tests) | deferred |
| tech_debt | Phase 8 — BillingSummary TS interface omits scheduled_plan/scheduled_change_at | deferred |

Known deferred items at close: 25+ (see above)

## Key Decisions (v1.1)

- Soft enforcement only in v1.1 — hard 429 deferred to v1.2 after real usage data available
- `plan_limits` Postgres table is the single source of truth; workspace overrides via JSONB merge
- Paddle webhooks are authoritative for plan state — app reads, never computes from redirect
- Entitlement middleware is mandatory on gated routes; UI gating alone is insufficient
- Local proxy stays unmetered — only cloud workspaces have quotas

## Session Continuity

**Next action:** Execute Phase 11 plans — Wave 1 (01+02 parallel), Wave 2 (03a→03b, 04 parallel with 03a), Wave 3 (05a→05b)
**Last milestone:** v1.1 ended at Phase 10 — v1.2 begins at Phase 11
**Roadmap:** 3 phases (11–13), 19 requirements, all mapped

## Phase 11 Execution Plan

Wave 1 (parallel):
- `11-PLAN-01` → database.py: auth_tokens table + email_verified_at column
- `11-PLAN-02` → email.py: TemplateSpec registry + 5 transactional send functions + HTML templates

Wave 2:
- `11-PLAN-03a` (after 01+02) → models.py + rate_limit.py + encode_jwt email_verified field
- `11-PLAN-03b` (after 03a) → 4 auth route handlers + signup email wiring
- `11-PLAN-04` (after 01+02, parallel with 03a) → billing.py: transaction.completed webhook handler

Wave 3:
- `11-PLAN-05a` (after 03b) → useAuth.ts emailVerified + setup/page.tsx forgot-password flow
- `11-PLAN-05b` (after 05a) → /reset-password page + /verify-email page + BillingStatusBanner
