---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: completed
stopped_at: Completed 05-discovery-dashboard/05-03-PLAN.md
last_updated: "2026-04-11T04:07:05.211Z"
last_activity: 2026-04-10 — Completed 02-detection-engine/02-04-PLAN.md
progress:
  total_phases: 5
  completed_phases: 5
  total_plans: 15
  completed_plans: 15
  percent: 100
---

# State

## Current Position

**Milestone:** v1.0 Shadow AI Discovery & Inventory
**Phase:** 2 — Detection Engine
**Plan:** 02-04 complete (SDK transport interceptor with BurnLensTransport and wrap())
**Status:** Milestone complete
**Last activity:** 2026-04-10 — Completed 02-detection-engine/02-04-PLAN.md

Progress: [██████████] 100%

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-10)

**Core value:** Complete visibility into AI API spending with zero code changes
**Current focus:** Phase 1 — Data Foundation (ai_assets, provider_signatures, discovery_events tables + migration)

## Performance Metrics

- Phases complete: 0/5
- Requirements mapped: 25/25
- Plans executed: 2 (01-01, 01-02)

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 01-data-foundation | 01 | 3 min | 2 | 3 |
| 01-data-foundation | 02 | 4 min | 2 | 3 |
| 02-detection-engine | 01 | 8 min | 1 | 4 |
| 02-detection-engine | 02 | 8 min | 1 | 3 |
| 02-detection-engine | 04 | 3 min | 1 | 3 |
| Phase 02-detection-engine P03 | 4 | 2 tasks | 5 files |
| Phase 03-asset-management-api P01 | 8 min | 2 tasks | 4 files |
| Phase 03-asset-management-api P02 | 2 | 1 tasks | 2 files |
| Phase 03-asset-management-api P03 | 3 min | 2 tasks | 6 files |
| Phase 04-alert-system P01 | 3 min | 2 tasks | 5 files |
| Phase 04-alert-system P02 | 3 min | 2 tasks | 3 files |
| Phase 04-alert-system P03 | 3 min | 2 tasks | 4 files |
| Phase 05-discovery-dashboard P01 | 5 | 2 tasks | 5 files |
| Phase 05-discovery-dashboard P02 | 4 | 2 tasks | 5 files |
| Phase 05-discovery-dashboard P03 | 5min | 2 tasks | 3 files |

## Accumulated Context

### Key Decisions

- Agentless detection ships first (billing API parsing) — zero additional setup for existing users
- SQLite extended with new tables — consistent with existing stack, no external DB needed
- Metadata only, never store request/response payloads — privacy/security constraint
- Phase 1 ships as free feature — growth lever toward Phase 2 paid tier
- [01-01] SQLite RAISE(ABORT) triggers raise IntegrityError via aiosqlite (not OperationalError)
- [01-01] Plain TEXT for owner_team and project (no FK) — simple strings per CONTEXT.md design
- [01-01] INSERT OR IGNORE + UNIQUE constraint for idempotent provider seed data
- [01-02] update_asset_status uses event_type='model_changed' for status transitions — most appropriate existing CHECK constraint value
- [01-02] Private _row_to_asset/_row_to_event helpers centralize deserialization — keeps query functions readable and DRY
- [01-02] Dynamic WHERE clause accumulation (not string concatenation) for get_assets/get_discovery_events filters
- [02-01] Google detection uses proxy traffic only — no billing admin API with per-model breakdown
- [02-01] api_key_id hashed via sha256 before storage — raw keys never persisted
- [02-01] Fail-open: HTTPStatusError caught per-provider, logged, skipped — proxy never crashes
- [02-01] Asset dedup key is provider + model_name + endpoint_url (not api_key_hash which may be absent)
- [02-02] fnmatch.fnmatch chosen for provider URL glob matching — lightweight, zero extra deps, handles wildcards like *.openai.azure.com/*
- [02-02] Scheme stripping uses split('://', 1)[-1] — handles both http and https and plain host paths uniformly
- [02-02] Approved assets update last_active_at only — no status change, enforced in upsert_asset_from_detection, immutable by detection engine
- [02-03] First detection run deferred 1 hour — avoids running on startup before proxy has traffic
- [02-03] Proxy asset upsert fires in asyncio.create_task after response forwarded — zero latency added to proxy path
- [02-03] original_headers passed to _handle_non_streaming and _handle_streaming — needed to extract raw auth token for hashing before headers are cleaned
- [02-04] asyncio.create_task (fire-and-forget) used for logging — response returned immediately, never delayed by DB write
- [02-04] response.status_code is safe to read (header-level); response.aread/read/stream never called to preserve streaming
- [02-04] wrap() mutates client in place and returns same object — enables chaining without requiring user to reassign
- [02-04] Model extracted from URL path only (best-effort) — token counts are out of scope for SDK path (DETC-08 proxy handles tokens)
- [03-01] date_since filter uses first_seen_at >= ISO string comparison — consistent with existing datetime-as-TEXT pattern
- [03-01] get_asset_summary runs 5 small queries in one connection — readable, avoids multi-join complexity
- [03-01] update_asset_fields dynamic SET clause (same pattern as get_assets WHERE) — avoids updating unchanged fields
- [03-01] asset_to_response/event_to_response/signature_to_response raise ValueError on id=None — guards against converting unsaved objects
- [03-02] GET /summary defined before GET /{asset_id} — FastAPI path matching is order-sensitive; "summary" must not be treated as integer ID
- [03-02] response_model=dict for GET /{asset_id} detail endpoint — mixed asset+events compound response avoids dedicated DetailResponse schema
- [03-02] Approve endpoint inserts explicit discovery_event after update_asset_status (which auto-logs one) — double event for explicit approval audit trail
- [03-03] assets router mounted at /api/v1/assets (prefix=/api/v1/assets) because assets.py uses prefix='' — matches TestAssetAPI fixture
- [03-03] date_since/date_until added to get_discovery_events using same dynamic WHERE clause pattern as get_assets
- [03-03] insert_provider_signature uses INSERT OR IGNORE — idempotent for seeded providers, returns lastrowid==0 if duplicate
- [04-01] smtplib chosen over aiosmtplib to keep zero new pip dependencies (stdlib only)
- [04-01] asyncio.to_thread wraps blocking smtplib calls for non-blocking event loop
- [04-01] get_inactive_assets excludes deprecated/inactive status to avoid re-alerting known dormant assets
- [05-01] /ui/discovery uses explicit FileResponse route registered before StaticFiles mount — StaticFiles html=True does not serve clean URLs without trailing slash
- [05-01] Client-side sort after API fetch for asset table — /api/v1/assets has no sort_by param; sort applied to current page data after fetch
- [05-01] Monthly spend KPI shows page total from visible assets — avoids high-limit secondary fetch, noted in sub-text
- [05-01] Unassigned KPI proxied via by_risk_tier.unclassified — true null-team count not in summary endpoint
- [05-02] search_query uses OR LIKE across 5 columns (model_name, provider, owner_team, endpoint_url, tags) — JSON text tags column supports LIKE matching on serialized values
- [05-02] Event delegation on shadow panel click handler — avoids attaching listeners to dynamically rendered shadow cards
- [05-02] 300ms debounce on global-search input — prevents excessive API calls while typing
- [05-02] Fade-out CSS transition (300ms) for approve action — visual feedback before DOM removal
- [05-03] localStorage key burnlens_saved_views stores JSON array of {name, filters} objects — zero-backend persistence
- [05-03] renderSavedViewsDropdown() always rebuilds from localStorage — single source of truth for saved views dropdown
- [05-03] loadView() syncs both DOM elements and module-level filter state variables — keeps fetchAssets() consistent

### Architecture Notes

- New tables: ai_assets, provider_signatures, discovery_events
- New routers mount under /api/v1/assets, /api/v1/discovery, /api/v1/providers
- Detection engine runs on APScheduler (hourly)
- Alert system reuses existing BurnLens Slack webhook + adds email via Resend
- Dashboard extends existing static HTML + Chart.js approach (no React, no build step)
- Build spec at docs/phase1_discovery_build_spec.md has full technical detail

### Phase Dependencies

- Phase 3 (API) depends on Phase 1 (Data) — can start in parallel with Phase 2
- Phase 4 (Alerts) depends on Phase 2 (Detection) — needs shadow classifier
- Phase 5 (Dashboard) depends on Phase 3 (API) and Phase 4 (Alerts)

### Blockers

None at this time.

### Todos

- [x] Run `/gsd:discuss-phase 1` to gather implementation context
- [ ] Run `/gsd:plan-phase 1` to create execution plans for Data Foundation

## Session Continuity

**To resume:** Read .planning/ROADMAP.md to see phase structure, then check this STATE.md for current position.
**Stopped at:** Completed 05-discovery-dashboard/05-03-PLAN.md
**Next action:** Execute next plan in Phase 1 (Data Foundation) or plan remaining phases.
