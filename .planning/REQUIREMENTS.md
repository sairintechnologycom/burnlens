# Requirements: BurnLens

**Defined:** 2026-04-10
**Core Value:** Complete visibility into AI API spending with zero code changes

## v1 Requirements

Requirements for Shadow AI Discovery & Inventory. Each maps to roadmap phases.

### Data Model

- [x] **DATA-01**: System creates ai_assets table with provider, model, endpoint, team, status, risk tier, spend tracking
- [x] **DATA-02**: System pre-populates provider_signatures table for OpenAI, Anthropic, Google, Azure OpenAI, Bedrock, Cohere, Mistral
- [x] **DATA-03**: System maintains append-only discovery_events log for all detection events
- [x] **DATA-04**: Database migration creates all tables with proper indexes

### Detection

- [x] **DETC-01**: System parses OpenAI billing API to detect models, usage volumes, and API key identifiers
- [x] **DETC-02**: System parses Anthropic billing API to detect models, usage volumes, and API key identifiers
- [x] **DETC-03**: System parses Google AI billing API to detect models, usage volumes, and API key identifiers
- [x] **DETC-04**: System matches endpoint URLs and headers against provider_signatures to auto-identify providers
- [x] **DETC-05**: System classifies endpoint as shadow if API key, model, provider, or team is unregistered/unapproved
- [x] **DETC-06**: System runs detection on a scheduled basis (hourly via APScheduler)
- [x] **DETC-07**: SDK wrapper (`burnlens.wrap(client)`) intercepts calls and logs metadata without modifying payloads
- [x] **DETC-08**: Proxy mode forwards AI SDK traffic and logs metadata only (model, tokens, latency, status code)

### API

- [x] **API-01**: User can list all AI assets with filters (provider, status, team, risk_tier) and pagination
- [x] **API-02**: User can get single asset detail with usage history
- [x] **API-03**: User can update asset (assign team, set risk_tier, update tags, change status)
- [x] **API-04**: User can get dashboard summary (total assets, by provider, by status, by risk, new this week)
- [x] **API-05**: User can list shadow/unregistered AI endpoints filtered by date range
- [x] **API-06**: User can approve a shadow asset (change status from shadow to approved)
- [x] **API-07**: User can list and query discovery events by type, asset, date range
- [x] **API-08**: User can list known provider signatures
- [x] **API-09**: User can add custom provider signatures for self-hosted/private models

### Dashboard

- [ ] **DASH-01**: User sees summary cards (total assets, active this month, shadow detected, unassigned, monthly spend)
- [ ] **DASH-02**: User sees provider breakdown donut chart (asset count and spend by provider)
- [ ] **DASH-03**: User sees sortable, filterable asset table (model, provider, team, status, risk, spend, dates)
- [ ] **DASH-04**: User sees shadow AI alert panel with approve/assign actions inline
- [ ] **DASH-05**: User sees discovery event timeline showing new assets, model changes, alerts
- [ ] **DASH-06**: User sees "new this week" section for recently detected assets
- [ ] **DASH-07**: User can search globally by model name, provider, team, endpoint URL, or tag
- [ ] **DASH-08**: User can save filter combinations as named views

### Alerts

- [ ] **ALRT-01**: System sends Slack + email alert within 1 hour when new shadow AI endpoint detected
- [ ] **ALRT-02**: System sends Slack + email alert when new provider first seen
- [ ] **ALRT-03**: System sends daily email digest for model version changes
- [ ] **ALRT-04**: System sends weekly email digest for assets inactive >30 days
- [ ] **ALRT-05**: System sends Slack + email alert when single asset spend >200% of 30-day average

## v2 Requirements

Deferred to future milestones. Tracked but not in current roadmap.

### Policy Enforcement (Phase 2)

- **PLCY-01**: Admin can define allowed/blocked model lists
- **PLCY-02**: System blocks requests to unapproved models
- **PLCY-03**: Admin can set per-team spending limits with hard enforcement

### Compliance (Phase 3)

- **CMPL-01**: System generates compliance reports mapped to regulatory frameworks
- **CMPL-02**: System tracks data residency requirements per provider/model

## Out of Scope

| Feature | Reason |
|---------|--------|
| Policy enforcement or blocking | Phase 2 — monetization tier |
| Compliance reporting | Phase 3 — regulatory framework |
| Regulatory framework mapping | Phase 3 |
| Request/response payload logging | Privacy/security — metadata only |
| Agent-based deep payload inspection | Phase 1 is metadata only |
| Mobile app | Web dashboard sufficient |
| Multi-tenant SaaS hosting | Local-first architecture |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA-01 | Phase 1 | Complete |
| DATA-02 | Phase 1 | Complete |
| DATA-03 | Phase 1 | Complete |
| DATA-04 | Phase 1 | Complete |
| DETC-01 | Phase 2 | Complete |
| DETC-02 | Phase 2 | Complete |
| DETC-03 | Phase 2 | Complete |
| DETC-04 | Phase 2 | Complete |
| DETC-05 | Phase 2 | Complete |
| DETC-06 | Phase 2 | Complete |
| DETC-07 | Phase 2 | Complete |
| DETC-08 | Phase 2 | Complete |
| API-01 | Phase 3 | Complete |
| API-02 | Phase 3 | Complete |
| API-03 | Phase 3 | Complete |
| API-04 | Phase 3 | Complete |
| API-05 | Phase 3 | Complete |
| API-06 | Phase 3 | Complete |
| API-07 | Phase 3 | Complete |
| API-08 | Phase 3 | Complete |
| API-09 | Phase 3 | Complete |
| ALRT-01 | Phase 4 | Pending |
| ALRT-02 | Phase 4 | Pending |
| ALRT-03 | Phase 4 | Pending |
| ALRT-04 | Phase 4 | Pending |
| ALRT-05 | Phase 4 | Pending |
| DASH-01 | Phase 5 | Pending |
| DASH-02 | Phase 5 | Pending |
| DASH-03 | Phase 5 | Pending |
| DASH-04 | Phase 5 | Pending |
| DASH-05 | Phase 5 | Pending |
| DASH-06 | Phase 5 | Pending |
| DASH-07 | Phase 5 | Pending |
| DASH-08 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 25 total
- Mapped to phases: 25
- Unmapped: 0

---
*Requirements defined: 2026-04-10*
*Last updated: 2026-04-10 — traceability populated by roadmapper*
