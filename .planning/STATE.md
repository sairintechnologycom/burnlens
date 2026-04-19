---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: milestone
status: executing
stopped_at: Phase 7 complete (human_needed); ready for Phase 8.
last_updated: "2026-04-19T11:15:00.000Z"
last_activity: 2026-04-19
progress:
  total_phases: 5
  completed_phases: 2
  total_plans: 11
  completed_plans: 7
  percent: 64
---

# State

## Current Position

**Milestone:** v1.1 Billing & Quota
**Phase:** 8 — Billing Self-Service (not yet planned)
**Plan:** —
**Status:** Ready to discuss/plan
**Last activity:** 2026-04-19

Progress: [████░░░░░░] 40% (2/5 phases complete)

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-18)

**Core value:** Complete visibility into AI API spending with zero code changes
**Current focus:** v1.1 — Plan limits foundation (shipped), Paddle webhooks (next), billing self-service, soft quota enforcement, gating + usage meter UI

## Phase Plan (v1.1)

| # | Phase | Depends on | Status |
|---|-------|------------|--------|
| 6 | Plan Limits Foundation | — | ✓ Complete (2026-04-18) |
| 7 | Paddle Lifecycle Sync | Phase 6 | ✓ Complete (2026-04-19, human_needed) |
| 8 | Billing Self-Service | Phase 7 | Not started |
| 9 | Quota Tracking & Soft Enforcement | Phase 6 (+ Phase 7 for trustworthy plan state) | Not started |
| 10 | Feature Gating & Usage Visibility UI | Phase 9, Phase 7 | Not started |

## Accumulated Context

### Key Decisions (carried forward from v1.0)

- Agentless detection first (billing API parsing) — shipped
- SQLite extended for Shadow AI tables — shipped
- Metadata only, never store request/response payloads — privacy constraint
- Paddle replaced Stripe (merchant-of-record for global tax) — shipped 2026-04
- Quota enforcement belongs at POST /v1/ingest (single chokepoint) — v1.1 decision
- Local proxy stays unmetered — only cloud workspaces have quotas

### New Decisions (v1.1 roadmap)

- v1.1 is soft enforcement only: seat/API-key 402s + retention pruning + 80%/100% warnings. Hard ingest 429 deferred to v1.2.
- `plan_limits` Postgres table is the single source of truth; per-workspace overrides live on the workspace row.
- Paddle webhooks are authoritative for plan state — the app reads, never computes from checkout redirect.
- Entitlement middleware on gated API routes is mandatory; UI gating alone is not sufficient.

### Phase 7 Shipped (2026-04-19, human_needed)

- Schema: 5 paddle lifecycle columns on `workspaces` (trial_ends_at, current_period_ends_at, cancel_at_period_end, price_cents, currency) + `paddle_events` dedup table with idx on `received_at DESC`, all idempotent
- Webhook refactor: signature-first 401 gate, `ON CONFLICT (event_id) DO NOTHING` dedup, handlers for `subscription.activated/updated/canceled/paused` (D-23 collapses paused into canceled) + `transaction.payment_failed` (sets past_due, preserves plan per D-21), DB-first `plan_limits.paddle_price_id` lookup with env fallback, D-11 silent-success invariant preserved
- New `GET /billing/summary` behind `verify_token`, workspace-scoped
- `BillingSummary` Pydantic model
- 18-case pytest suite (`tests/test_billing_webhook_phase7.py`) — 100% passing
- `BillingContext` provider + `useBilling()` hook: 30s-visible polling + focus-throttled-10s + AuthError→logout, safe default outside provider (PeriodContext pattern), mounted in Shell after session guard
- `BillingStatusBanner` past_due only, amber, below Topbar (I2 — single mount covers all authed routes)
- Topbar pill rewired to `useBilling().billing.plan` with session.plan fallback (D-19)
- Settings → Billing card: 3-row layout (plan+price+status pill, next-billing/trial-ends, disabled CTA), date format `Month D, YYYY`, USD $X/mo formatting with Intl.NumberFormat fallback for non-USD, status pill tokens (cyan active/trialing, amber past_due), W2 canceled/paused race-window cleanup
- `?checkout=success` handler: `refresh()` + `history.replaceState` strip
- W3 invariant: zero new hex values in Phase 7 frontend surfaces
- Open: 5 items in 07-VERIFICATION.md (live Paddle webhook, 60s SLA, cross-route banner sweep, 5 card states, checkout-success URL strip) — all require browser/live-Paddle testing

### Phase 6 Shipped (2026-04-18)

- `plan_limits` Postgres table (9 columns, partial index on paddle_price_id) — added to `init_db()` in `burnlens_cloud/database.py`
- `workspaces.limit_overrides JSONB` nullable column — added via idempotent DO-block ALTER
- 3 seed rows: Free (10000/1/7/1, no Paddle IDs), Cloud (1M/1/30/3, live Paddle IDs), Teams (10M/10/90/25, live Paddle IDs)
- `resolve_limits(ws_id UUID)` SQL function (LANGUAGE SQL STABLE, CREATE OR REPLACE, single round-trip, COALESCE + JSONB `||` merge)
- `PlanLimits` and `ResolvedLimits` Pydantic models in `burnlens_cloud/models.py`
- `burnlens_cloud/plans.py` — async `resolve_limits(workspace_id)` wrapper
- `tests/test_plan_limits.py` — 12 async pytest tests (module-skips without DATABASE_URL)
- Open: 2 items in 06-HUMAN-UAT.md (live-DB pytest run + idempotency against prior-migrated DB)

### v1.0 Shipped

- Full Shadow AI Discovery & Inventory system
- 5 phases, 15 plans completed
- All 25 v1.0 requirements mapped and delivered

### Architecture Notes

- Cloud backend: burnlens_cloud/ on Railway (FastAPI + asyncpg + Postgres)
- Frontend: burnlens.app on Vercel (Next.js App Router, TypeScript, custom CSS)
- Billing: Paddle (Cloud $29/mo 7d trial, Teams $99/mo)
- Auth: session.plan + apiKey in localStorage after login

### Blockers

None at this time.

## Session Continuity

**To resume:** Run `/gsd-discuss-phase 8` to start Phase 8 (Billing Self-Service).
**Stopped at:** Phase 7 complete (human_needed); ready for Phase 8.
**Next action:** `/gsd-discuss-phase 8` — gather context and decisions before planning Phase 8.
