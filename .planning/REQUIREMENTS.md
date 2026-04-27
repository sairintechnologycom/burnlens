# Requirements

## Milestone v1.1: Billing & Quota

**Goal:** Surface the user's tier, let them manage billing in-app, and enforce plan limits so free/Cloud/Teams users can't exceed what they paid for.

**Started:** 2026-04-18
**Status:** Defining

---

## v1.1 Requirements

### Billing Panel (BILL)

- [ ] **BILL-01** — User can view current plan name, price, and subscription status (active / trialing / past_due / canceled) from Settings → Billing
- [ ] **BILL-02** — User can see next billing date and, if trialing, the trial expiry date
- [ ] **BILL-03** — User can launch a Paddle checkout to upgrade or downgrade their plan without leaving the app
- [ ] **BILL-04** — User can view invoice history with amount, date, status, and a download link (via Paddle customer portal)
- [ ] **BILL-05** — User can cancel their subscription self-serve (cancel-at-period-end) and see the effective end date
- [ ] **BILL-06** — User can reactivate a canceled-but-not-ended subscription before the period expires

### Plan Definitions (PLAN)

- [x] **PLAN-01** — Plan limits (monthly request cap, seat count, retention days, API key count, gated features) are persisted in a `plan_limits` Postgres table as the source of truth (validated Phase 6)
- [x] **PLAN-02** — Workspace can carry per-workspace limit overrides that supersede its plan's defaults (for enterprise exceptions) (validated Phase 6)
- [x] **PLAN-03** — Three seeded plans exist at migration time: Free (local only), Cloud ($29/mo), Teams ($99/mo) — values confirmed against the live Paddle products (validated Phase 6)
- [x] **PLAN-04** — A single resolver function returns the effective limits for a given workspace (workspace override > plan default) (validated Phase 6)

### Quota Enforcement (QUOTA)

- [ ] **QUOTA-01** — Server tracks monthly request count per workspace, reset on each billing cycle anniversary
- [ ] **QUOTA-02** — Workspace receives an email when monthly usage crosses 80% and again at 100% of plan quota
- [ ] **QUOTA-03** — `POST /v1/ingest` records usage but does NOT hard-reject over-quota workspaces in v1.1 (soft enforcement — hardening deferred to v1.2)
- [ ] **QUOTA-04** — Team invite endpoint returns 402 Payment Required when inviting a member would exceed the plan's seat limit
- [ ] **QUOTA-05** — A scheduled job prunes stored events older than the workspace's plan retention window

### Feature Gating (GATE)

- [x] **GATE-01** — Free-tier workspaces can sync to cloud but cannot access Teams or Customers views (UI locked with upgrade CTA)
- [x] **GATE-02** — Cloud-tier workspaces see the Teams tab as locked with "Upgrade to Teams" CTA; Teams-tier sees it unlocked
- [x] **GATE-03** — Customer attribution views require Teams plan; Cloud and Free see upgrade CTA
- [ ] **GATE-04** — API key creation endpoint enforces per-plan key count (Free: 1, Cloud: 5, Teams: unlimited)
- [ ] **GATE-05** — Backend middleware verifies plan entitlement on every gated API call (not just UI); 402 returned if required tier not met

### Usage Visibility (METER)

- [x] **METER-01** — Every dashboard page displays a usage meter in the sidebar: current month requests / plan limit, with a progress bar
- [x] **METER-02** — Usage meter color transitions: green (<80%), amber (80–100%), red (>100%)
- [x] **METER-03** — Clicking the usage meter deep-links to Settings → Billing → Usage section with a daily breakdown

### Paddle Integration (PDL)

- [ ] **PDL-01** — Webhook handler processes `subscription.created`, `subscription.updated`, `subscription.canceled` and updates the workspace plan state
- [ ] **PDL-02** — Webhook handler processes `transaction.completed` and `transaction.payment_failed` to drive `past_due` and `active` transitions
- [ ] **PDL-03** — Webhook signatures are verified via the Paddle webhook secret before any state mutation
- [ ] **PDL-04** — Plan badge in the Topbar reflects subscription state accurately within 60 seconds of a Paddle lifecycle event

---

## Future Requirements (v1.2 and beyond)

- Hard quota enforcement at ingest (429 on over-quota)
- Admin UI for editing plan_limits table at runtime
- Usage-based overage billing (pay-as-you-go beyond plan cap)
- Annual plans and prepaid credits
- Custom enterprise contracts (negotiated limits, invoicing, NET-30)
- Plan entitlement caching at edge for sub-100ms gate checks
- Per-model cost caps (not just request count)

---

## Out of Scope (v1.1)

- Hard rejection of over-quota ingest traffic (deferred to v1.2 — need real data first)
- Billing for the open-source local proxy (stays free forever)
- Self-serve plan editing for end users (admin-only via deploy in v1.1)
- Custom enterprise contracts and negotiated pricing (handled off-platform)
- Compliance/SOC2 reporting integration (future milestone)
- Dunning email sequences beyond the 80%/100% and past_due notifications

---

## Traceability

Mapped to phases in `.planning/ROADMAP.md` on 2026-04-18. Coverage: 28/28.

| REQ-ID   | Phase                                    | Status  |
|----------|------------------------------------------|---------|
| BILL-01  | Phase 7: Paddle Lifecycle Sync           | Pending |
| BILL-02  | Phase 7: Paddle Lifecycle Sync           | Pending |
| BILL-03  | Phase 8: Billing Self-Service            | Pending |
| BILL-04  | Phase 8: Billing Self-Service            | Pending |
| BILL-05  | Phase 8: Billing Self-Service            | Pending |
| BILL-06  | Phase 8: Billing Self-Service            | Pending |
| PLAN-01  | Phase 6: Plan Limits Foundation          | Pending |
| PLAN-02  | Phase 6: Plan Limits Foundation          | Pending |
| PLAN-03  | Phase 6: Plan Limits Foundation          | Pending |
| PLAN-04  | Phase 6: Plan Limits Foundation          | Pending |
| QUOTA-01 | Phase 9: Quota Tracking & Soft Enforcement | Pending |
| QUOTA-02 | Phase 9: Quota Tracking & Soft Enforcement | Pending |
| QUOTA-03 | Phase 9: Quota Tracking & Soft Enforcement | Pending |
| QUOTA-04 | Phase 9: Quota Tracking & Soft Enforcement | Pending |
| QUOTA-05 | Phase 9: Quota Tracking & Soft Enforcement | Pending |
| GATE-01  | Phase 10: Feature Gating & Usage Visibility UI | Complete |
| GATE-02  | Phase 10: Feature Gating & Usage Visibility UI | Complete |
| GATE-03  | Phase 10: Feature Gating & Usage Visibility UI | Complete |
| GATE-04  | Phase 9: Quota Tracking & Soft Enforcement | Pending |
| GATE-05  | Phase 9: Quota Tracking & Soft Enforcement | Pending |
| METER-01 | Phase 10: Feature Gating & Usage Visibility UI | Complete |
| METER-02 | Phase 10: Feature Gating & Usage Visibility UI | Complete |
| METER-03 | Phase 10: Feature Gating & Usage Visibility UI | Complete |
| PDL-01   | Phase 7: Paddle Lifecycle Sync           | Pending |
| PDL-02   | Phase 7: Paddle Lifecycle Sync           | Pending |
| PDL-03   | Phase 7: Paddle Lifecycle Sync           | Pending |
| PDL-04   | Phase 7: Paddle Lifecycle Sync           | Pending |

---

*Requirements defined: 2026-04-18 | Traceability populated: 2026-04-18*
