# Roadmap: BurnLens v1.0 Shadow AI Discovery & Inventory

## Overview

This roadmap extends BurnLens's existing cost tracking into an automated Shadow AI Discovery and Inventory system. Starting from the data foundation (new tables + migrations), we build a detection engine that parses billing APIs and classifies shadow usage, expose asset management APIs, wire up alerts, and finally deliver a single-pane discovery dashboard. Each phase delivers a coherent, independently verifiable capability that unblocks the next.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Data Foundation** - Database tables, migrations, and seed data for the discovery system (completed 2026-04-10)
- [x] **Phase 2: Detection Engine** - Billing API parsers, provider signature matching, and shadow AI classifier (completed 2026-04-10)
- [ ] **Phase 3: Asset Management API** - REST endpoints for listing, filtering, updating, and approving AI assets
- [ ] **Phase 4: Alert System** - Slack and email alerts for shadow detection, model changes, and spend spikes
- [ ] **Phase 5: Discovery Dashboard** - Single-pane discovery UI with asset table, shadow panel, and timeline

## Phase Details

### Phase 1: Data Foundation
**Goal**: The database schema, seed data, and models required by all other phases exist and are queryable
**Depends on**: Nothing (first phase)
**Requirements**: DATA-01, DATA-02, DATA-03, DATA-04
**Success Criteria** (what must be TRUE):
  1. Running `burnlens start` against a fresh database creates ai_assets, provider_signatures, and discovery_events tables with all specified columns and indexes
  2. provider_signatures table is pre-populated with signatures for OpenAI, Anthropic, Google, Azure OpenAI, AWS Bedrock, Cohere, and Mistral
  3. discovery_events table enforces append-only behavior (no update/delete) and records event_type, asset_id, details, and detected_at
  4. All tables have the correct foreign key relationships and the migration runs cleanly with no errors on an existing BurnLens installation
**Plans:** 2/2 plans complete

Plans:
- [x] 01-01-PLAN.md -- Schema, models, tables, indexes, triggers, and provider seed data
- [x] 01-02-PLAN.md -- Insert and query helper functions with tests

### Phase 2: Detection Engine
**Goal**: BurnLens automatically detects AI assets by parsing billing APIs and proxy traffic, classifies shadow usage, and schedules recurring detection runs
**Depends on**: Phase 1
**Requirements**: DETC-01, DETC-02, DETC-03, DETC-04, DETC-05, DETC-06, DETC-07, DETC-08
**Success Criteria** (what must be TRUE):
  1. After connecting provider API keys, the detection engine creates ai_asset records for every model/endpoint observed in OpenAI, Anthropic, and Google billing data
  2. An API call to an endpoint whose URL matches a provider_signatures pattern is automatically assigned the correct provider without manual configuration
  3. An asset using an unregistered API key or an unrecognized provider is classified as status=shadow and a discovery_event of type new_asset_detected is written
  4. Detection runs automatically on an hourly schedule without manual invocation
  5. `burnlens.wrap(client)` intercepts SDK calls and logs model, tokens, latency, and status code to ai_assets without storing any request or response payloads
**Plans:** 4/4 plans complete

Plans:
- [ ] 02-01-PLAN.md -- Billing API parsers for OpenAI, Anthropic, Google (config + pagination + TDD)
- [ ] 02-02-PLAN.md -- Provider signature matcher + shadow classifier (fnmatch + upsert logic + TDD)
- [ ] 02-03-PLAN.md -- APScheduler wiring + proxy interceptor asset upsert extension
- [ ] 02-04-PLAN.md -- SDK wrapper burnlens.wrap(client) with httpx transport interception

### Phase 3: Asset Management API
**Goal**: All REST endpoints for the asset registry are functional and tested, enabling the dashboard and external tools to read and manage AI assets
**Depends on**: Phase 1
**Requirements**: API-01, API-02, API-03, API-04, API-05, API-06, API-07, API-08, API-09
**Success Criteria** (what must be TRUE):
  1. `GET /api/v1/assets` returns a paginated list of assets filterable by provider, status, team, and risk_tier
  2. `PATCH /api/v1/assets/{id}` persists team assignment, risk_tier, tags, and status changes and reflects them in subsequent GET responses
  3. `POST /api/v1/assets/{id}/approve` changes asset status from shadow to approved and writes a discovery_event record
  4. `GET /api/v1/assets/summary` returns total assets, counts by provider, counts by status, counts by risk tier, and new-this-week count
  5. `POST /api/v1/providers/signatures` stores a custom provider signature and it is subsequently used by the detection engine for matching
**Plans**: TBD

### Phase 4: Alert System
**Goal**: Configured Slack and email destinations receive timely alerts when shadow assets appear, new providers are detected, and spend spikes occur
**Depends on**: Phase 2
**Requirements**: ALRT-01, ALRT-02, ALRT-03, ALRT-04, ALRT-05
**Success Criteria** (what must be TRUE):
  1. Within 1 hour of a new shadow AI endpoint being detected, a Slack message and email are sent to configured destinations with the asset details
  2. When a provider not previously seen fires its first API call, a Slack message and email alert are sent immediately
  3. Each morning a single email digest is delivered listing all model version changes detected in the previous 24 hours
  4. Each week an email digest is delivered listing all assets that have been inactive for more than 30 days
  5. When a single asset's spend in a rolling period exceeds 200% of its 30-day average, a Slack message and email alert fire within 1 hour
**Plans**: TBD

### Phase 5: Discovery Dashboard
**Goal**: Users have a single-pane web view of their entire AI footprint with search, filter, shadow review, and saved views
**Depends on**: Phase 3, Phase 4
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04, DASH-05, DASH-06, DASH-07, DASH-08
**Success Criteria** (what must be TRUE):
  1. The discovery page shows summary cards for total assets, active this month, shadow detected, unassigned assets, and monthly spend — all reflecting live data
  2. The provider breakdown donut chart shows asset count and spend segmented by provider
  3. The asset table is sortable by any column and filterable by provider, status, risk tier, team, and date range simultaneously
  4. The shadow AI alert panel lists all shadow-status assets with inline approve and assign-team actions that persist on click
  5. The discovery event timeline shows new assets, model changes, and alerts in chronological order
  6. Global search returns matching assets when querying by model name, provider, team, endpoint URL, or tag
  7. A user can save a filter combination as a named view and reload it to restore the same filters
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Data Foundation | 2/2 | Complete   | 2026-04-10 |
| 2. Detection Engine | 4/4 | Complete   | 2026-04-10 |
| 3. Asset Management API | 0/TBD | Not started | - |
| 4. Alert System | 0/TBD | Not started | - |
| 5. Discovery Dashboard | 0/TBD | Not started | - |
