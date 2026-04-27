---
gsd_roadmap_version: 1.0
milestone: v1.1
milestone_name: billing-and-quota
granularity: standard
created: 2026-04-18
total_phases: 5
phase_range: "6-10"
---

# Roadmap — v1.1 Billing & Quota

**Goal:** Surface the user's tier, let them manage billing in-app, and enforce plan limits so Free / Cloud / Teams users can't exceed what they paid for.

**Scope note:** v1.1 is soft enforcement only — retention pruning + seat/API-key 402s + usage warnings. Hard ingest rejection stays deferred to v1.2.

## Phases

- [x] **Phase 6: Plan Limits Foundation** — Seed plan_limits table and build a single effective-limits resolver (completed 2026-04-18)
- [x] **Phase 7: Paddle Lifecycle Sync** — Webhook handlers drive plan/subscription state and the read-only Billing summary (completed 2026-04-19)
- [x] **Phase 8: Billing Self-Service** — Checkout, invoice history, cancel, and reactivate flows in Settings → Billing (completed 2026-04-20)
- [ ] **Phase 9: Quota Tracking & Soft Enforcement** — Monthly counters, seat/API-key 402s, retention pruning, backend entitlement middleware
- [ ] **Phase 10: Feature Gating & Usage Visibility UI** — Plan-gated UI, upgrade CTAs, and the sidebar usage meter

## Phase Details

### Phase 6: Plan Limits Foundation
**Goal**: A single Postgres source of truth for per-plan limits, with a resolver function that every downstream phase reads from.
**Depends on**: Nothing (foundation — unblocks 7, 9)
**Requirements**: PLAN-01, PLAN-02, PLAN-03, PLAN-04
**Success Criteria** (what must be TRUE):
  1. A `plan_limits` row exists for each of Free, Cloud ($29/mo), Teams ($99/mo) with request cap, seat count, retention days, API key count, and gated feature flags matching the live Paddle products.
  2. A workspace row can carry an override JSON blob that supersedes its plan's defaults.
  3. Calling `resolve_limits(workspace_id)` returns the effective limits (override merged over plan default) in a single Postgres round-trip.
  4. Migrations are idempotent — re-running them on an existing DB is a no-op and leaves seeded data intact.
**Canonical refs**:
  - REQ-IDs: PLAN-01, PLAN-02, PLAN-03, PLAN-04
  - Extend: `burnlens_cloud/database.py` (migrations), `burnlens_cloud/models.py` (Plan/Workspace schemas)
  - New: `burnlens_cloud/plans.py` (resolver) or equivalent module
**Plans**: 3 plans
- [x] 06-01-schema-and-seeds-PLAN.md — plan_limits table + workspaces.limit_overrides column + three seeded plan rows (PLAN-01, PLAN-02, PLAN-03)
- [x] 06-02-resolver-and-models-PLAN.md — resolve_limits() Postgres function + Pydantic models + burnlens_cloud/plans.py wrapper (PLAN-01, PLAN-02, PLAN-04)
- [x] 06-03-tests-PLAN.md — pytest suite covering idempotency, seed values, scalar override, per-flag gated_features merge, single round-trip (PLAN-01..04)

### Phase 7: Paddle Lifecycle Sync
**Goal**: Paddle webhook events are the authoritative source of each workspace's plan/subscription state, and the user can read that state back from Settings → Billing.
**Depends on**: Phase 6 (needs `plan_limits` to map Paddle product IDs to internal plans)
**Requirements**: PDL-01, PDL-02, PDL-03, PDL-04, BILL-01, BILL-02
**Success Criteria** (what must be TRUE):
  1. Paddle webhook signature verification rejects any unsigned or tampered payload with 401 before any DB write occurs.
  2. `subscription.created`, `subscription.updated`, and `subscription.canceled` events update the workspace's plan, status (active / trialing / past_due / canceled), and period dates in Postgres.
  3. `transaction.completed` and `transaction.payment_failed` drive `active` ↔ `past_due` transitions on the workspace.
  4. The Topbar plan badge and Settings → Billing summary reflect the new plan state within 60 seconds of the Paddle event firing.
  5. The user can see plan name, price, status, next billing date, and (if trialing) trial-expiry date on Settings → Billing.
**Canonical refs**:
  - REQ-IDs: PDL-01, PDL-02, PDL-03, PDL-04, BILL-01, BILL-02
  - Extend: `burnlens_cloud/billing.py` (webhook handler, Paddle client), `burnlens_cloud/main.py` (route mount), `frontend/src/app/settings/page.tsx` (Billing panel read view), `frontend/src/components/Topbar.tsx` (badge polling/refresh)
**Plans**: 4 plans
- [ ] 07-01-PLAN.md — Schema migrations: workspaces lifecycle columns + paddle_events dedup table (PDL-01, PDL-02, BILL-01, BILL-02)
- [ ] 07-02-PLAN.md — Webhook refactor + dedup + extended handlers + GET /billing/summary + BillingSummary model + pytest (PDL-01, PDL-02, PDL-03, BILL-01, BILL-02)
- [ ] 07-03-PLAN.md — BillingContext provider (poll+focus+visibility) + Shell mounting (PDL-04, BILL-01, BILL-02)
- [ ] 07-04-PLAN.md — BillingStatusBanner + Topbar rewire + Settings Billing card + ?checkout=success listener (PDL-04, BILL-01, BILL-02)
**UI hint**: yes

### Phase 8: Billing Self-Service
**Goal**: User can complete the full upgrade / downgrade / cancel / reactivate / invoice-history loop from inside the app without emailing support.
**Depends on**: Phase 7 (plan state must already be accurate so mutation flows have a correct "before" state)
**Requirements**: BILL-03, BILL-04, BILL-05, BILL-06
**Success Criteria** (what must be TRUE):
  1. User can launch a Paddle checkout overlay from Settings → Billing to upgrade or downgrade; the new plan is reflected in the app within 60 seconds of checkout completion.
  2. User can see a list of past invoices (amount, date, status) with a working download link that opens the Paddle-hosted invoice PDF.
  3. User can click "Cancel subscription" and see the effective end date (period end, not immediate); app state transitions to `canceled` with `cancel_at_period_end=true`.
  4. User can reactivate a canceled-but-not-yet-ended subscription before the period expires, restoring `active` status without re-checkout.
**Canonical refs**:
  - REQ-IDs: BILL-03, BILL-04, BILL-05, BILL-06
  - Extend: `burnlens_cloud/billing.py` (checkout session, cancel/reactivate endpoints, invoice list proxy), `frontend/src/app/settings/page.tsx` (Billing panel mutation UI)
**Plans**: 12 plans
- [x] 08-01-cancellation-surveys-schema-PLAN.md — Idempotent cancellation_surveys table migration in init_db (BILL-05)
- [x] 08-02-billing-models-PLAN.md — CancelBody / ChangePlanBody (allowlist) / Invoice / InvoicesResponse Pydantic models (BILL-03, BILL-04, BILL-05, BILL-06)
- [x] 08-03-change-plan-endpoint-PLAN.md — POST /billing/change-plan (upgrade prorated, downgrade at period end, idempotent, 502-on-paddle-fail) (BILL-03)
- [x] 08-04-cancel-endpoint-PLAN.md — POST /billing/cancel (Paddle effective_from=next_billing_period, best-effort survey insert, idempotent) (BILL-05)
- [x] 08-05-reactivate-endpoint-PLAN.md — POST /billing/reactivate (clears scheduled_change, idempotent, 400 when period already ended) (BILL-06)
- [x] 08-06-invoices-endpoint-PLAN.md — GET /billing/invoices (Paddle transactions proxy, 24-row cap, signed PDF URLs) (BILL-04)
- [x] 08-07-paddle-checkout-hook-PLAN.md — usePaddleCheckout hook + UpgradePrompt refactor (BILL-03)
- [x] 08-08-billing-context-setter-PLAN.md — BillingContext.setBilling escape hatch for optimistic post-mutation flip (BILL-03, BILL-05, BILL-06)
- [x] 08-09-cancel-modal-PLAN.md — CancelSubscriptionModal with exact D-08 body copy + D-10 reason radios (BILL-05)
- [x] 08-10-invoices-card-PLAN.md — InvoicesCard with Date/Amount/Status/Download PDF (BILL-04)
- [x] 08-11-plan-picker-modal-PLAN.md — GET /billing/plans + PlanPickerModal side-by-side comparison (BILL-03)
- [x] 08-12-settings-billing-wiring-PLAN.md — Replace disabled CTAs, mount InvoicesCard, wire Cancel/Resume/Change with D-21 refresh cadence (BILL-03, BILL-04, BILL-05, BILL-06)
**UI hint**: yes

### Phase 9: Quota Tracking & Soft Enforcement
**Goal**: The server knows every workspace's monthly usage, enforces seat / API-key caps with 402s, prunes retention-expired data, and warns users before they hit their cap.
**Depends on**: Phase 6 (reads from `plan_limits`); benefits from Phase 7 being live so plan state is trustworthy
**Requirements**: QUOTA-01, QUOTA-02, QUOTA-03, QUOTA-04, QUOTA-05, GATE-04, GATE-05
**Success Criteria** (what must be TRUE):
  1. Monthly request count per workspace is tracked in Postgres and resets on the billing-cycle anniversary; the value can be queried in a single indexed lookup.
  2. An email fires exactly once per billing cycle when a workspace crosses 80% of its plan quota, and again when it crosses 100%.
  3. `POST /v1/ingest` records usage and continues to accept traffic even when over-quota (soft enforcement — no 429).
  4. Inviting a team member or creating an API key beyond the plan limit returns HTTP 402 with a structured error identifying the blocking limit and the required plan.
  5. A scheduled job runs daily and deletes events older than the workspace's effective retention window, leaving newer events untouched.
  6. Every gated API route passes through a plan-entitlement middleware that returns 402 when the workspace's plan is below the required tier — independent of any UI gating.
**Canonical refs**:
  - REQ-IDs: QUOTA-01, QUOTA-02, QUOTA-03, QUOTA-04, QUOTA-05, GATE-04, GATE-05
  - Extend: `burnlens_cloud/ingest.py` (usage counter increment), `burnlens_cloud/team_api.py` (seat 402), `burnlens_cloud/settings_api.py` (API-key 402), `burnlens_cloud/database.py` (usage table + retention job), `burnlens_cloud/email.py` + `burnlens_cloud/emails/` (80%/100% templates), `burnlens_cloud/auth.py` (entitlement middleware)
**Plans**: 8 plans
- [ ] 09-01-PLAN.md — Schema: workspace_usage_cycles + api_keys tables + api_keys backfill + gated_features teams_view/customers_view seed supplement (QUOTA-01, QUOTA-05, GATE-04, GATE-05)
- [ ] 09-02-PLAN.md — Pydantic ApiKey models + 80/100% HTML email templates + send_usage_warning_email + retention_days=0 docstring (QUOTA-02, GATE-04)
- [ ] 09-03-PLAN.md — require_feature(name) dependency factory + dual-read get_workspace_by_api_key (GATE-04, GATE-05)
- [ ] 09-04-PLAN.md — /api-keys CRUD router (POST/GET/DELETE) with 402 cap + main.py mount (GATE-04)
- [ ] 09-05-PLAN.md — Ingest counter UPSERT + 80/100% email enqueue + remove 429 (QUOTA-01, QUOTA-02, QUOTA-03)
- [ ] 09-06-PLAN.md — Paddle webhook seeds workspace_usage_cycles row on period rollover (QUOTA-01)
- [ ] 09-07-PLAN.md — team_api 422→402 + require_feature(teams_view) + get_seat_limit via resolve_limits (QUOTA-04, GATE-05)
- [ ] 09-08-PLAN.md — Retention-prune asyncio loop + main.py lifespan wiring (QUOTA-05)

### Phase 10: Feature Gating & Usage Visibility UI
**Goal**: The dashboard makes it obvious what plan a user is on, what features are locked, and how close they are to their quota — with a clear upgrade path at every friction point.
**Depends on**: Phase 9 (entitlement middleware and usage counter must exist before UI reads from them); Phase 7 (plan state must be trustworthy)
**Requirements**: GATE-01, GATE-02, GATE-03, METER-01, METER-02, METER-03
**Success Criteria** (what must be TRUE):
  1. A Free-tier user sees the Teams and Customers views as locked panels with an inline "Upgrade" CTA; clicking the CTA opens Paddle checkout for the required tier.
  2. A Cloud-tier user sees Teams locked with an "Upgrade to Teams" CTA; a Teams-tier user sees it unlocked.
  3. Every dashboard page displays a usage meter in the sidebar showing `current month requests / plan limit` with a progress bar.
  4. The usage meter bar is green below 80%, amber from 80% to 100%, and red above 100% of quota.
  5. Clicking the usage meter navigates to Settings → Billing → Usage with a daily breakdown of requests for the current cycle.
**Canonical refs**:
  - REQ-IDs: GATE-01, GATE-02, GATE-03, METER-01, METER-02, METER-03
  - Extend: `frontend/src/components/Sidebar.tsx` (usage meter), `frontend/src/components/UpgradePrompt.tsx` (gated panel shell), `frontend/src/components/DashboardLayout.tsx` (meter mount point), `frontend/src/app/settings/page.tsx` (Usage subsection), and Teams / Customers route pages (lock wrappers)
**Plans**: 4 plans
- [x] 10-01-PLAN.md — Backend: /billing/summary usage+available_plans+api_keys extension + GET /billing/usage/daily + Pydantic models + idx_request_records_workspace_ts (METER-01, METER-02, METER-03) — completed 2026-04-25 (52/52 billing-adjacent pytest pass; backend partial — frontend in 10-02/03/04)
- [x] 10-02-PLAN.md — BillingContext type extension + planSatisfies helper + all Phase 10 CSS + UsageMeter component + Sidebar lockedForPlan affordance (METER-01, METER-02, GATE-01, GATE-02, GATE-03) — completed 2026-04-25 (frontend `tsc --noEmit` clean; commits f993ec4, ee8351b)
- [x] 10-03-PLAN.md — LockedPanel with dynamic 402-driven copy + Paddle overlay CTA + /teams and /customers migration + delete UpgradePrompt.tsx (GATE-01, GATE-02, GATE-03) — completed 2026-04-27 (frontend `tsc --noEmit` clean; commits 0ba67e2, f2e2d16, e665bd0)
- [x] 10-04-PLAN.md — VerticalBar chart + UsageCard (#usage anchor) + ApiKeysCard with plaintext-once modal + typed-name revoke + cap-banner Paddle CTA + Settings wiring (METER-03) — completed 2026-04-27 (frontend `tsc --noEmit` clean; commits 5d411ac, 642d1a7, d07d935)
**UI hint**: yes

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 6. Plan Limits Foundation | 3/3 | Complete | 2026-04-18 |
| 7. Paddle Lifecycle Sync | 0/4 | Planned | — |
| 8. Billing Self-Service | 12/12 | Complete | 2026-04-20 |
| 9. Quota Tracking & Soft Enforcement | 0/8 | Planned | — |
| 10. Feature Gating & Usage Visibility UI | 4/4 | Executing | — |

## Coverage

- Total v1.1 requirements: 28
- Mapped: 28
- Orphaned: 0

---
*Roadmap created 2026-04-18 for milestone v1.1 Billing & Quota.*
