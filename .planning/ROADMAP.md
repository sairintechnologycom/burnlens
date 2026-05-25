---
gsd_roadmap_version: 1.0
---

# Roadmap — BurnLens

## Milestones

- ✅ **v0.x Core Proxy & FinOps** — Pre-GSD (shipped)
- ✅ **v1.0 Shadow AI Discovery & Inventory** — Phases 1–5 (shipped 2026-04-15)
- ✅ **v1.1 Billing & Quota** — Phases 6–10 (shipped 2026-04-30)
- ✅ **v1.2 Account Security & Notifications** — Phases 11–14 (shipped 2026-05-06)
- ✅ **v1.3 Quota Enforcement & API Key Management** — Phases 15–17 (shipped 2026-05-25)
- 📋 **v1.4 Usage Dashboard Improvements** — Phase 18 (planned)

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

<details>
<summary>✅ v1.3 Quota Enforcement & API Key Management (Phases 15–17) — SHIPPED 2026-05-25</summary>

- [x] **Phase 15: Hard Ingest Quota Enforcement** (3/3 plans) — completed 2026-05-08
- [x] **Phase 16: API Key Management** (10/10 plans) — completed 2026-05-15
- [x] **Phase 17: Google URL-Path Routing** (1/1 plan) — completed 2026-05-25

See `.planning/milestones/v1.3-ROADMAP.md` for full phase details.

</details>

### v1.4 Usage Dashboard Improvements

- [ ] **Phase 18: Usage Dashboard Improvements** — Date-range picker, model breakdown, CSV export, daily trend chart (DASH-01–04, deferred from v1.3)

## Phase Details

### Phase 18: Usage Dashboard Improvements
**Goal**: Users can slice, filter, and export their usage data from the cloud dashboard with richer chart views
**Depends on**: Nothing (carried forward from v1.3)
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
| 15. Hard Ingest Quota Enforcement | v1.3 | 3/3 | Complete | 2026-05-08 |
| 16. API Key Management | v1.3 | 10/10 | Complete | 2026-05-15 |
| 17. Google URL-Path Routing | v1.3 | 1/1 | Complete | 2026-05-25 |
| 18. Usage Dashboard Improvements | v1.4 | 0/? | Not started | - |

---
*v1.1 archived 2026-04-30. See `.planning/milestones/v1.1-ROADMAP.md` for full phase details.*
*v1.2 archived 2026-05-07. See `.planning/milestones/v1.2-ROADMAP.md` for full phase details.*
*v1.3 archived 2026-05-25. See `.planning/milestones/v1.3-ROADMAP.md` for full phase details.*
