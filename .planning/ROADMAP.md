---
gsd_roadmap_version: 1.0
---

# Roadmap — BurnLens

## Milestones

- ✅ **v0.x Core Proxy & FinOps** — Pre-GSD (shipped)
- ✅ **v1.0 Shadow AI Discovery & Inventory** — Phases 1–5 (shipped 2026-04-15)
- ✅ **v1.1 Billing & Quota** — Phases 6–10 (shipped 2026-04-30)
- 📋 **v1.2 Account Security & Notifications** — Phases 11–13 (active)

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

### 📋 v1.2 Account Security & Notifications (Active)

- [ ] **Phase 11: Auth Essentials** — password reset, email verification, transactional email infrastructure
- [ ] **Phase 12: Cloud Alert Engine** — alert schema, Railway cron evaluation, email + Slack dispatch
- [ ] **Phase 13: Alert Management UI** — /alerts page for viewing and managing workspace alert rules

## Phase Details

### Phase 11: Auth Essentials
**Goal**: Cloud users can recover locked accounts and verify email ownership; transactional email infrastructure supports all current and future notification types
**Depends on**: Phase 10 (v1.1 complete)
**Requirements**: AUTH-01, AUTH-02, AUTH-03, AUTH-04, AUTH-05, AUTH-06, AUTH-07, EMAIL-01, EMAIL-02, EMAIL-03, EMAIL-04
**Success Criteria** (what must be TRUE):
  1. A user who forgot their password can request a reset link, click it, set a new password, and log in — all within the time-limit window; the reset link is single-use
  2. The password-reset request endpoint always returns 200 regardless of whether the email exists (no user enumeration)
  3. A newly registered user automatically receives a welcome email and sees a dashboard banner prompting email verification until they click the verification link
  4. An existing user whose account predates v1.2 sees no verification banner and is treated as verified without any action on their part
  5. After completing a password reset, the user receives a confirmation email; after a successful Paddle payment, they receive a receipt — both delivered via the typed template registry
**Plans**: TBD
**UI hint**: yes

### Phase 12: Cloud Alert Engine
**Goal**: Org owners are automatically notified by email (and optionally Slack) when workspace spend crosses configured budget thresholds — no proxy needed, runs server-side on Railway
**Depends on**: Phase 11
**Requirements**: ALERT-01, ALERT-02, ALERT-03, ALERT-04, ALERT-05, ALERT-06, ALERT-07
**Success Criteria** (what must be TRUE):
  1. Cloud plan workspaces have default alert rules seeded at 80% and 100% of their plan's monthly allowance without any manual configuration
  2. The org owner receives an email notification when a budget threshold is crossed; repeated crossings of the same threshold within 24 hours do not generate duplicate notifications
  3. Org owners who configure a Slack webhook receive threshold notifications in Slack in addition to email
  4. Alert evaluation runs automatically on an hourly schedule via Railway cron; evaluation failures are logged but never interrupt the cron job
  5. Every fired alert is recorded in an audit log table with the rule, timestamp, and recipient
**Plans**: 3 plans
Plans:
- [ ] 12-01-PLAN.md — Schema: alert_rules + alert_events tables + default seeding migration
- [ ] 12-02-PLAN.md — Alert engine: burnlens_cloud/alert_engine.py + 24h dedup + email + Slack dispatch
- [ ] 12-03-PLAN.md — Cron endpoint + Slack webhook settings + config + test suite

### Phase 13: Alert Management UI
**Goal**: Org owners can view, enable/disable, and edit their workspace alert rules from the cloud dashboard without needing API access
**Depends on**: Phase 12
**Requirements**: ALERT-08, ALERT-09
**Success Criteria** (what must be TRUE):
  1. An org owner can navigate to /alerts and see all alert rules for their workspace, including current threshold values and enabled/disabled state
  2. An org owner can toggle a rule on or off, change its threshold percentage, and add or remove notification email recipients — changes take effect on the next cron evaluation
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
| 11. Auth Essentials | v1.2 | 0/? | Not started | — |
| 12. Cloud Alert Engine | v1.2 | 0/3 | Not started | — |
| 13. Alert Management UI | v1.2 | 0/? | Not started | — |

---
*v1.1 archived 2026-04-30. See `.planning/milestones/v1.1-ROADMAP.md` for full phase details.*
