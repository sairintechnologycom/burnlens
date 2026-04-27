---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: milestone
status: executing
stopped_at: Phase 10 Plan 01 complete (2026-04-25)
last_updated: "2026-04-27T11:59:28.524Z"
last_activity: 2026-04-27
progress:
  total_phases: 5
  completed_phases: 4
  total_plans: 31
  completed_plans: 29
  percent: 94
---

# State

## Current Position

Phase: 10 (feature-gating-usage-visibility-ui) — EXECUTING
Plan: 1 of 4
**Milestone:** v1.1 Billing & Quota
**Phase:** 10 — Feature Gating & Usage Visibility UI
**Plan:** 10-01 ✓; 10-02 ✓; 10-03 next
**Status:** Executing Phase 10
**Last activity:** 2026-04-27

Progress: [█████████▓] 97% (30/31 plans complete)

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-18)

**Core value:** Complete visibility into AI API spending with zero code changes
**Current focus:** Phase 10 — feature-gating-usage-visibility-ui

## Phase Plan (v1.1)

| # | Phase | Depends on | Status |
|---|-------|------------|--------|
| 6 | Plan Limits Foundation | — | ✓ Complete (2026-04-18) |
| 7 | Paddle Lifecycle Sync | Phase 6 | ✓ Complete (2026-04-19, human_needed) |
| 8 | Billing Self-Service | Phase 7 | ✓ Complete (2026-04-20, human_needed) |
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

### Phase 10 Plan 02 Shipped (2026-04-25)

- `frontend/src/lib/hooks/usePlanSatisfies.ts` (new): `PLAN_ORDER` (free/cloud/teams), `planSatisfies(have, need)` rank helper, `LOCKED_NAV` map (/teams + /customers → "teams"), `nextPlanFor(current)` upsell helper — single source of plan-rank truth for Plans 02/03/04
- `frontend/src/components/UsageMeter.tsx` (new): sidebar-footer widget, threshold coloring (cyan < 80%, amber 80–100%, red > 100%), bar width clamped at 100% per D-14 with overflow `(120%)` style numeric, ARIA progressbar attributes, polite live-region on amber/red, loading + empty-cycle states, click-to-`/settings#usage`
- `frontend/src/components/Sidebar.tsx`: `SidebarItem.lockedForPlan` field; `/teams` and `/customers` annotated `lockedForPlan: "teams"` (D-09); lock glyph + plan subtitle render via `planSatisfies(currentPlan, item.lockedForPlan)`; locked items remain clickable per D-10; `<UsageMeter />` mounted at footer
- `frontend/src/lib/contexts/BillingContext.tsx`: `BillingSummary` extended with optional `usage`, `available_plans`, `api_keys` (mirrors Plan 01 backend shape; `api_keys` is `workspace_id`-scoped, not `org_id`); `POLL_INTERVAL_MS` flipped from 30_000 to 60_000 (D-17 override of Phase 7 D-18 — visibility-gating preserved); the 30s value is removed (not commented out)
- `frontend/src/app/globals.css`: appended complete Phase 10 CSS block at EOF (157 lines) — `.usage-meter*`, `.sidebar-item--locked`, `.locked-panel*`, `.usage-card-summary`, `.api-keys-*`, `.api-key-modal-*`, `prefers-reduced-motion` overrides — file-ownership boundary so Plans 03/04 do NOT touch CSS
- T-10-07 (XSS via API-derived numerics): mitigated — `grep -ciE "(innerHTML|setInnerHTML)"` on UsageMeter.tsx and Sidebar.tsx both return 0
- T-10-10 (DoS via tight poll loop): mitigated — UsageMeter consumes BillingContext rather than starting a second poller; the existing visibility-gated 60s poller is the only setInterval
- TypeScript: `cd frontend && npx tsc --noEmit` exits clean (no errors)
- Plans 03/04 awareness: import `planSatisfies / LOCKED_NAV / nextPlanFor` from `@/lib/hooks/usePlanSatisfies`; consume `useBilling()` for `billing.usage / .available_plans / .api_keys`; do NOT add a second poller; do NOT touch globals.css; Plan 04 owns the `/settings#usage` anchor target
- Commits: `f993ec4` (types + helper + CSS), `ee8351b` (UsageMeter + Sidebar)

### Phase 10 Plan 01 Shipped (2026-04-25)

- `burnlens_cloud/models.py`: 5 new Pydantic models (UsageCurrentCycle, AvailablePlan, ApiKeysSummary, UsageDailyEntry, UsageDailyResponse) + BillingSummary additively extended with `usage` / `available_plans` / `api_keys` (all Optional with safe defaults — Phase 7/8 callers unaffected)
- `burnlens_cloud/billing.py`: GET /billing/summary now composes `usage.current_cycle` + `available_plans` + `api_keys` subobjects (D-18 / D-26); new GET /billing/usage/daily endpoint with workspace-scoped daily aggregation over `request_records` and `?cycle=previous` returning the documented 400 not_implemented stub (D-21)
- `_resolve_current_cycle(workspace_id, plan)` helper in billing.py — single source of paid (workspace_usage_cycles cycle_end>NOW) vs free (calendar-month UTC) vs brand-new (calendar-month + count=0) cycle resolution; reused by both Plan 10-01 endpoints and available for Plans 02/03/04 to grep
- `_PLAN_PRICE_CENTS` module-level constants (`{"cloud": 2900, "teams": 9900}`) — committed v1.0 source-of-truth for plan pricing on /billing/summary.available_plans; v1.2 followup tracks promotion to a real plan_limits column
- Workspace-scoping invariant: every SELECT in both endpoints binds `$1` to `token.workspace_id` — `?workspace_id=...` query params silently ignored (T-10-01 / T-10-26 mitigations); `test_summary_api_keys_workspace_isolation` and `test_usage_daily_workspace_isolation` lock the invariant
- Index `idx_request_records_workspace_ts` already existed at database.py:335 — no second-named-index added per plan instruction
- Tests: 17 new in `tests/test_billing_usage.py` (model shapes + summary extension + daily endpoint + previous-cycle stub + workspace isolation + auth gate); 3 Phase 7 /billing/summary tests rewired to multi-SQL side_effect mocks (workspace-scoping invariant preserved); 52/52 billing-adjacent pytest pass
- Deviation: Plan's `<interfaces>` block named the api_keys workspace column "org_id" but actual schema uses `workspace_id` — code uses `workspace_id` (matches Phase 9 D-12 callers)
- Plans 02/03/04 awareness: `summary.usage` / `summary.available_plans` / `summary.api_keys` are now live for the frontend; `_load_billing_summary` (Phase 8 mutation responses) was NOT updated, so post-mutation responses serialize the new fields as `null/[]/null` — frontend BillingContext re-polls within 30s, acceptable per D-22 design

### Phase 8 Shipped (2026-04-20, human_needed)

- Schema: `cancellation_surveys` table (FK cascade to workspaces, nullable reason_code/reason_text) + `workspaces.scheduled_plan` / `scheduled_change_at` columns — all idempotent in `init_db()`
- Pydantic models (`burnlens_cloud/models.py`): `CancelBody`, `ChangePlanBody` (allowlist `{cloud, teams}` with case-normalization), `Invoice`, `InvoicesResponse`; `BillingSummary` gained optional `scheduled_plan` + `scheduled_change_at`
- 5 new endpoints on `burnlens_cloud/billing.py`, all `verify_token`-gated, server-read Paddle IDs, idempotent, 502-on-Paddle-fail without DB mutation, D-22 fresh-BillingSummary responses:
  - `POST /billing/change-plan` — upgrade prorated_immediately / downgrade next_billing_period; downgrade response carries scheduled_plan+scheduled_change_at (W1)
  - `POST /billing/cancel` — Paddle effective_from=next_billing_period; best-effort cancellation_surveys insert only if reason fields present
  - `POST /billing/reactivate` — clears scheduled_change; 400 when period already ended (D-15); W3-compliant module-level datetime import
  - `GET /billing/invoices` — Paddle transactions proxy, 24-row cap, per-row PDF lookup with W4 null-fallback; B2-compliant asyncpg subscript access
  - `GET /billing/plans` — serves plan_limits data for PlanPickerModal comparison
- Frontend hook: `usePaddleCheckout.ts` (initializePaddle + Paddle.Checkout.open + hosted-URL fallback; never throws); UpgradePrompt refactored to consume it
- `BillingContext.setBilling(next)` escape hatch with W5 KNOWN_STATUSES coercion — powers D-22 optimistic flip without /summary round-trip
- 3 new components: `CancelSubscriptionModal` (exact D-08 body + D-10 radios + D-28 support@burnlens.app toast); `InvoicesCard` (24-row table, Date/Amount/Status/PDF, `—` for null PDF, Retry on error); `PlanPickerModal` (data-driven Cloud/Teams comparison from /billing/plans)
- Settings page rewired: replaces two disabled Phase 7 CTAs with per-plan action rows (Free: Upgrade to Cloud + Teams link; Cloud: Upgrade to Teams + Cancel/Resume; Teams: Change plan + Cancel/Resume); W1 pending-downgrade info line; D-12 amber canceled-state message; D-21 refresh cadence (0s/3s/10s + 30s context poll); .btn-green (new globals.css utility, B1 contrast guaranteed) for Resume, .btn-red for Cancel
- Tests: 32/32 billing-adjacent pytest pass (`test_billing*.py`); frontend `tsc --noEmit` clean
- Open: 8 items in 08-HUMAN-UAT.md (all require live Paddle sandbox — upgrades, downgrade, cancel-with-reason, reactivate, invoice PDFs, 502 toast copy, PlanPickerModal discoverability)

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

**To resume:** Run `/gsd-execute-phase 10` to continue with Plan 10-02 (frontend BillingContext + UsageMeter sidebar widget).
**Stopped at:** Phase 10 Plan 01 complete (2026-04-25)
**Next action:** Execute Plan 10-02.

**Planned Phase:** 10 (Feature Gating & Usage Visibility UI) — 4 plans — 2026-04-25T00:10:59.043Z
**Phase 10 progress:** Plan 01 ✓; Plan 02/03/04 pending.
