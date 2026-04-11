---
phase: 03-asset-management-api
plan: "03"
subsystem: api
tags: [fastapi, discovery, providers, router, sqlite]
dependency_graph:
  requires: ["03-01", "03-02"]
  provides: ["burnlens/api/discovery.py", "burnlens/api/providers.py", "burnlens/proxy/server.py (v1 mounts)"]
  affects: ["burnlens/storage/queries.py", "burnlens/storage/database.py"]
tech_stack:
  added: []
  patterns: ["FastAPI APIRouter with prefix", "TDD red/green", "try/except graceful degradation in server.py"]
key_files:
  created:
    - burnlens/api/discovery.py
    - burnlens/api/providers.py
  modified:
    - burnlens/storage/queries.py
    - burnlens/storage/database.py
    - burnlens/proxy/server.py
    - tests/test_api.py
decisions:
  - "assets router mounted at /api/v1/assets (prefix=/api/v1/assets) because assets.py uses prefix='' — consistent with TestAssetAPI fixture"
  - "Single try/except wraps all three router imports — if any missing, all degrade gracefully"
  - "date_since/date_until added to get_discovery_events using same dynamic WHERE clause pattern as get_assets"
  - "insert_provider_signature uses INSERT OR IGNORE — idempotent for seeded providers, callers check lastrowid==0 for duplicates"
  - "POST /providers/signatures returns 201 on both new and duplicate inserts for consistent API behavior"
metrics:
  duration: "~3 min"
  completed: "2026-04-10"
  tasks_completed: 2
  files_changed: 6
requirements-completed: [API-07, API-08, API-09]
---

# Phase 03 Plan 03: Discovery Events and Provider Signatures Routers Summary

**One-liner:** Discovery events router (GET /api/v1/discovery/events with type/asset_id/date filters) and provider signatures router (GET/POST /api/v1/providers/signatures) with all three Phase 3 routers mounted in server.py under /api/v1.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Failing tests for discovery and provider endpoints | cd94fe0 | tests/test_api.py |
| 1 (GREEN) | Discovery events and provider signatures routers | 7c5fae2 | burnlens/api/discovery.py, burnlens/api/providers.py, burnlens/storage/queries.py, burnlens/storage/database.py |
| 2 | Mount all API v1 routers in server.py | 63aa9a1 | burnlens/proxy/server.py |

## What Was Built

### burnlens/api/discovery.py
FastAPI router with `prefix="/discovery"`. Single endpoint:
- `GET /events` — returns `DiscoveryEventListResponse` with filters: `event_type`, `asset_id`, `since` (ISO date), `until` (ISO date), `limit` (1-500, default 50)

### burnlens/api/providers.py
FastAPI router with `prefix="/providers"`. Two endpoints:
- `GET /signatures` — returns `list[SignatureResponse]`, optional `?provider=` filter
- `POST /signatures` — accepts `SignatureCreateRequest`, returns 201 with `SignatureResponse`; uses INSERT OR IGNORE for idempotency

### burnlens/storage/queries.py
Extended `get_discovery_events()` with `date_since` and `date_until` parameters. Follows existing dynamic WHERE clause accumulation pattern (`detected_at >= ?`, `detected_at <= ?`).

### burnlens/storage/database.py
Added `insert_provider_signature(db_path, sig: ProviderSignature) -> int`. Uses INSERT OR IGNORE — returns lastrowid (0 if duplicate, new id if created).

### burnlens/proxy/server.py
Added try/except block after dashboard routes that imports and mounts all three Phase 3 API v1 routers:
- `assets_router` at `/api/v1/assets`
- `discovery_router` at `/api/v1`
- `providers_router` at `/api/v1`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] assets router prefix mismatch**
- **Found during:** Task 2 verification
- **Issue:** Plan spec said mount assets at `/api/v1`, but assets.py uses `prefix=""` so that would land routes at `/api/v1/`, `/api/v1/{id}` — colliding with root. TestAssetAPI (from 03-02) uses `prefix="/api/v1/assets"` as mount prefix.
- **Fix:** Changed `app.include_router(assets_router, prefix="/api/v1")` to `app.include_router(assets_router, prefix="/api/v1/assets")`
- **Files modified:** burnlens/proxy/server.py
- **Commit:** 63aa9a1

## Verification Results

- All 9 new tests pass (TestDiscoveryAPI: 4, TestProviderAPI: 5)
- All 16 API tests pass (TestQueryExtensions: 7, TestDiscoveryAPI: 4, TestProviderAPI: 5)
- All 3 Phase 3 routers mounted under /api/v1: `/api/v1/assets/*`, `/api/v1/discovery/events`, `/api/v1/providers/signatures`
- Existing /api/* dashboard routes unchanged
- POST /api/v1/providers/signatures creates a signature visible in subsequent GET

## Self-Check: PASSED

Files created/modified:
- burnlens/api/discovery.py: FOUND
- burnlens/api/providers.py: FOUND
- burnlens/storage/queries.py: FOUND (modified)
- burnlens/storage/database.py: FOUND (modified)
- burnlens/proxy/server.py: FOUND (modified)
- tests/test_api.py: FOUND (modified)

Commits:
- cd94fe0: FOUND (RED phase tests)
- 7c5fae2: FOUND (GREEN phase implementation)
- 63aa9a1: FOUND (server.py mount)
