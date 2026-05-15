---
gsd_roadmap_version: 1.0
---

# Roadmap — BurnLens

## Milestones

- ✅ **v0.x Core Proxy & FinOps** — Pre-GSD (shipped)
- ✅ **v1.0 Shadow AI Discovery & Inventory** — Phases 1–5 (shipped 2026-04-15)
- ✅ **v1.1 Billing & Quota** — Phases 6–10 (shipped 2026-04-30)
- ✅ **v1.2 Account Security & Notifications** — Phases 11–14 (shipped 2026-05-06)
- 🔄 **v1.3 Quota Enforcement & API Key Management** — Phases 15–18 (in progress)

## Phases

<details>
<summary>✅ v1.0 Shadow AI Discovery & Inventory (Phases 1–5) — SHIPPED 2026-04-15</summary>

- [x] Phase 1: Data Foundation — completed 2026-04-10
- [x] Phase 2: Detection Engine — completed 2026-04-11
- [x] Phase 3: Asset Management API — completed 2026-04-12
- [x] Phase 4: Alert System — completed 2026-04-13
- [x] Phase 5: Discovery Dashboard — completed 2026-04-15

See `.planning/milestones/` for full v1.0 details.

</details>

<details>
<summary>✅ v1.1 Billing & Quota (Phases 6–10) — SHIPPED 2026-04-30</summary>

- [x] Phase 6: Plan Limits Foundation (3/3 plans) — completed 2026-04-18
- [x] Phase 7: Paddle Lifecycle Sync (4/4 plans) — completed 2026-04-19
- [x] Phase 8: Billing Self-Service (12/12 plans) — completed 2026-04-20
- [x] Phase 9: Quota Tracking & Soft Enforcement (8/8 plans) — completed 2026-04-29
- [x] Phase 10: Feature Gating & Usage Visibility UI (4/4 plans) — completed 2026-04-27

See `.planning/milestones/v1.1-ROADMAP.md` for full details.

</details>

<details>
<summary>✅ v1.2 Account Security & Notifications (Phases 11–14) — SHIPPED 2026-05-06</summary>

- [x] Phase 11: Auth Essentials (9 plans) — completed 2026-05-02
- [x] Phase 12: Cloud Alert Engine (3 plans) — completed 2026-05-02
- [x] Phase 13: Alert Management UI (3 plans) — completed 2026-05-06
- [x] Phase 14: Budget-Aware Model Downgrade Routing (7 plans) — completed 2026-05-05

See `.planning/milestones/v1.2-ROADMAP.md` for full phase details.

</details>

### v1.3 Quota Enforcement & API Key Management

- [x] **Phase 15: Hard Ingest Quota Enforcement** (3/3 plans) — completed 2026-05-08
- [x] **Phase 16: API Key Management** — Full API key lifecycle UI + auth bug fix for API-key users (completed 2026-05-12)
- [ ] **Phase 17: Google URL-Path Routing** — Model downgrade via URL-path rewrite for Google provider
- [ ] **Phase 18: Usage Dashboard Improvements** — Date-range picker, model breakdown, CSV export, daily trend chart

## Phase Details

### Phase 15: Hard Ingest Quota Enforcement
**Goal**: Workspaces that exceed their plan limits are hard-blocked at the Railway ingest endpoint
**Depends on**: Nothing (builds on existing `plan_limits` table + `resolve_limits()` + monthly counters from Phase 9)
**Requirements**: QUOTA-01, QUOTA-02, QUOTA-03, QUOTA-04, QUOTA-05
**Success Criteria** (what must be TRUE):
  1. A workspace that has consumed its monthly API call quota receives a 429 (not 200) from POST /v1/ingest
  2. A workspace that has consumed its monthly token budget receives a 429 from POST /v1/ingest
  3. A workspace whose cumulative spend has crossed its dollar ceiling receives a 429 from POST /v1/ingest
  4. An API key belonging to a seat number above the plan's seat cap is rejected with a 429
  5. Every 429 response body contains a structured JSON object with the quota dimension, current usage value, and plan limit value
**Plans**: 3 plans
Plans:
- [ ] 15-PLAN-00.md — TDD scaffold: 12 RED test stubs for all QUOTA-01–05 cases
- [ ] 15-PLAN-01.md — Schema migrations + QuotaExceededDetail model + ResolvedLimits extension + plans.py wrapper
- [ ] 15-PLAN-02.md — _check_quota_or_raise() enforcement + extended UPSERT tracking

### Phase 16: API Key Management
**Goal**: Workspace owners can manage the full API key lifecycle from the UI, and the auth bug for API-key users is resolved
**Depends on**: Phase 15 (quota enforcement must be live before key management UI exposes key creation at scale)
**Requirements**: APIKEY-01, APIKEY-02, APIKEY-03, APIKEY-04, APIKEY-05, AUTH-08
**Success Criteria** (what must be TRUE):
  1. An owner visiting `/api-keys` sees all active workspace keys with their labels and last-used timestamps
  2. An owner can generate a new `bl_live_xxx` key with a custom label, and the full key value is immediately copyable to clipboard before leaving the creation dialog
  3. An owner can revoke any key and subsequent requests using that key are immediately rejected server-side (no grace period)
  4. An owner can edit the label or scope note on any existing key without revoking and re-creating it
  5. A viewer-role user visiting `/api-keys` sees only keys they created and cannot access keys created by other users (per D-04 — viewers may self-create and self-revoke their own keys; cross-creator access returns 404 indistinguishability)
  6. A user who signed up via API key (null `owner_email` in localStorage) successfully receives a resend-verification email because the handler reads email from the server-side session instead of localStorage
**Plans**: TBD
**UI hint**: yes

### Phase 17: Google URL-Path Routing
**Goal**: The OSS proxy correctly downgrades Google model requests by rewriting the URL path, not just the request body
**Depends on**: Nothing (isolated OSS proxy change; does not depend on cloud phases)
**Requirements**: ROUTE-08
**Success Criteria** (what must be TRUE):
  1. When `decide_route()` selects a downgrade model for a Google Generative Language API request, the outbound request URL path reflects the downgrade model name (not the original model from the path)
  2. The body-rewrite behavior from v1.2 is preserved — URL-path rewrite is additive, not a replacement
**Plans**: TBD

### Phase 18: Usage Dashboard Improvements
**Goal**: Users can slice, filter, and export their usage data from the cloud dashboard with richer chart views
**Depends on**: Phase 15 (quota enforcement live), Phase 16 (API key management complete — stable ingest pipeline)
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04
**Success Criteria** (what must be TRUE):
  1. User can choose a preset time window (7d, 30d, 90d) or set a custom date range, and all charts on the dashboard update to reflect the selected period
  2. User can view a ranked breakdown of cost by model (table or chart) showing each model's share of total spend for the selected period
  3. User can click an export button and download a CSV file containing the usage rows that match the currently active filters and date range
  4. Dashboard displays a daily cost trend chart that overlays per-model cost distribution so users can see both total spend trajectory and model mix over time
**Plans**: TBD
**UI hint**: yes

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Data Foundation | v1.0 | — | Complete | 2026-04-10 |
| 2. Detection Engine | v1.0 | — | Complete | 2026-04-11 |
| 3. Asset Management API | v1.0 | — | Complete | 2026-04-12 |
| 4. Alert System | v1.0 | — | Complete | 2026-04-13 |
| 5. Discovery Dashboard | v1.0 | — | Complete | 2026-04-15 |
| 6. Plan Limits Foundation | v1.1 | 3/3 | Complete | 2026-04-18 |
| 7. Paddle Lifecycle Sync | v1.1 | 4/4 | Complete | 2026-04-19 |
| 8. Billing Self-Service | v1.1 | 12/12 | Complete | 2026-04-20 |
| 9. Quota Tracking & Soft Enforcement | v1.1 | 8/8 | Complete | 2026-04-29 |
| 10. Feature Gating & Usage Visibility UI | v1.1 | 4/4 | Complete | 2026-04-27 |
| 11. Auth Essentials | v1.2 | 9/9 | Complete | 2026-05-02 |
| 12. Cloud Alert Engine | v1.2 | 3/3 | Complete | 2026-05-02 |
| 13. Alert Management UI | v1.2 | 3/3 | Complete | 2026-05-06 |
| 14. Budget-Aware Model Downgrade Routing | v1.2 | 7/7 | Complete | 2026-05-05 |
| 15. Hard Ingest Quota Enforcement | v1.3 | 0/3 | Not started | - |
| 16. API Key Management | v1.3 | 10/10 | Complete    | 2026-05-15 |
| 17. Google URL-Path Routing | v1.3 | 0/? | Not started | - |
| 18. Usage Dashboard Improvements | v1.3 | 0/? | Not started | - |

---
*v1.1 archived 2026-04-30. See `.planning/milestones/v1.1-ROADMAP.md` for full phase details.*
*v1.2 archived 2026-05-07. See `.planning/milestones/v1.2-ROADMAP.md` for full phase details.*
