---
gsd_state_version: 1.0
milestone: v1.3
milestone_name: Quota Enforcement & API Key Management
status: executing
last_updated: "2026-05-25T10:40:35.631Z"
last_activity: 2026-05-25 -- Phase 17 planning complete
progress:
  total_phases: 4
  completed_phases: 1
  total_plans: 11
  completed_plans: 13
  percent: 25
---

# State

## Current Position

Phase: 17
Plan: Not started
Status: Ready to execute
Resume file: .planning/phases/17-google-url-path-routing/17-CONTEXT.md
Last activity: 2026-05-25 -- Phase 17 planning complete

## Key Decisions (Phase 12)

- Used `secrets.compare_digest` for constant-time cron secret comparison (timing-safe)
- Cron endpoint fail-open: exceptions from `evaluate_all_workspaces` return `{evaluated:0, fired:0}`
- Cron endpoint tests use minimal FastAPI app without lifespan to avoid DB dependency in unit tests
- SSRF guard on Slack webhook: rejects any URL not starting with `https://hooks.slack.com/`

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-07 after v1.2 milestone close)

**Core value:** Complete visibility into AI API spending with zero code changes
**Current focus:** Phase 16 — API Key Management

## v1.3 Phase Summary

| # | Phase | Requirements | Status |
|---|-------|-------------|--------|
| 15 | Hard Ingest Quota Enforcement | QUOTA-01–05 (5 reqs) | Not started |
| 16 | API Key Management | APIKEY-01–05 + AUTH-08 (6 reqs) | Not started |
| 17 | Google URL-Path Routing | ROUTE-08 (1 req) | Not started |
| 18 | Usage Dashboard Improvements | DASH-01–04 (4 reqs) | Not started |

## v1.2 Phase Summary

| # | Phase | Requirements | Status |
|---|-------|-------------|--------|
| 11 | Auth Essentials | AUTH-01–07, EMAIL-01–04 (11 reqs) | ✓ Complete (2026-05-02) |
| 12 | Cloud Alert Engine | ALERT-01–07 (7 reqs) | ✓ Complete (2026-05-02) |
| 13 | Alert Management UI | ALERT-08–09 (2 reqs) | ✓ Complete (2026-05-06) |
| 14 | Budget-Aware Model Downgrade Routing | ROUTE-01–07 (7 reqs) | ✓ Complete (2026-05-05) |

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

## Key Decisions (Phase 14)

- `decide_route()` never raises — any exception returns fail-open `RouteDecision(reason="error")`
- Budget priority: customer > team > global_usd > budget_limit_usd (per D-03)
- Pct threshold check runs before USD check; when both trigger, reason = "budget_pct"
- Team spend cached 60 seconds per team (`_team_spend_cache` dict) to avoid per-request DB reads
- Deferred imports inside `_resolve_budget()` to break circular dependency between router ↔ database
- Body rewrite is JSON-decode + field replace + re-encode; Google URL-path routing is a known limitation (addressed in Phase 17)

## Session Continuity

**Next action:** Run `/gsd-plan-phase 15` to plan Phase 15 — Hard Ingest Quota Enforcement
**Last milestone:** v1.2 complete — all 4 phases (11–14) shipped 2026-05-06
**Active milestone:** v1.3 Quota Enforcement & API Key Management — roadmap created, 4 phases (15–18)

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
