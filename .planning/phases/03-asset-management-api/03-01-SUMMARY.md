---
phase: 03-asset-management-api
plan: "01"
subsystem: storage-queries, api-schemas
tags: [queries, pydantic, filters, aggregation, tdd]
dependency_graph:
  requires: [01-data-foundation, 02-detection-engine]
  provides: [extended-asset-queries, api-schemas]
  affects: [03-02-asset-router, 03-03-events-router]
tech_stack:
  added: [pydantic-v2]
  patterns: [dynamic-where-clause, tdd-red-green, dataclass-to-pydantic-converter]
key_files:
  created:
    - burnlens/api/__init__.py
    - burnlens/api/schemas.py
    - tests/test_api.py
  modified:
    - burnlens/storage/queries.py
decisions:
  - "date_since filter uses first_seen_at >= ? (ISO string comparison) — consistent with existing datetime-as-TEXT pattern"
  - "update_asset_fields uses dynamic SET clause (same pattern as get_assets WHERE) — avoids building UPDATE for unchanged fields"
  - "get_asset_summary runs 5 small queries inside a single connection context — readable and avoids multi-join complexity"
  - "asset_to_response/event_to_response/signature_to_response raise ValueError on id=None — guards against converting unsaved objects"
  - "get_assets_count mirrors get_assets filter params exactly — single source of truth for pagination total"
metrics:
  duration: "8 min"
  completed: "2026-04-10"
  tasks_completed: 2
  files_changed: 4
---

# Phase 03 Plan 01: Query Extensions and Pydantic Schemas Summary

**One-liner:** Extended get_assets() with risk_tier/date_since filters, added get_asset_summary() aggregation and update_asset_fields() partial update helper, and created Pydantic v2 schema layer in burnlens/api/schemas.py.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 (RED) | Failing tests for query extensions | cef659f | tests/test_api.py |
| 1 (GREEN) | Extend queries.py with filters and helpers | a775916 | burnlens/storage/queries.py |
| 2 | Create Pydantic schemas and API package | 76508b0 | burnlens/api/__init__.py, burnlens/api/schemas.py |

## What Was Built

### Task 1: Extended Query Layer (TDD)

**burnlens/storage/queries.py** — four new/extended functions:

- `get_assets()` — gained `risk_tier` and `date_since` filter parameters using the existing dynamic WHERE clause pattern
- `get_assets_count()` — same filter surface as get_assets() minus pagination, returns `COUNT(*)` for API pagination metadata
- `get_asset_summary()` — runs 5 queries in one connection: total, by_provider GROUP BY, by_status GROUP BY, by_risk_tier GROUP BY, new_this_week (last 7 days)
- `update_asset_fields()` — partial update via dynamic SET clause; always updates `updated_at`; logs a `model_changed` discovery_event when status changes; returns the refreshed AiAsset; raises ValueError for missing asset_id

### Task 2: Pydantic Schemas

**burnlens/api/schemas.py** — full schema layer for all three REST resource families:

- Asset: `AssetResponse`, `AssetListResponse`, `AssetUpdateRequest`, `AssetApproveResponse`
- Summary: `AssetSummaryResponse`
- Events: `DiscoveryEventResponse`, `DiscoveryEventListResponse`
- Signatures: `SignatureResponse`, `SignatureCreateRequest`
- Converters: `asset_to_response()`, `event_to_response()`, `signature_to_response()`

## Verification

```
tests/test_api.py::TestQueryExtensions::test_get_assets_risk_tier_filter PASSED
tests/test_api.py::TestQueryExtensions::test_get_assets_date_since_filter PASSED
tests/test_api.py::TestQueryExtensions::test_get_asset_summary_keys PASSED
tests/test_api.py::TestQueryExtensions::test_get_asset_summary_new_this_week PASSED
tests/test_api.py::TestQueryExtensions::test_update_asset_fields_persists_changes PASSED
tests/test_api.py::TestQueryExtensions::test_update_asset_fields_raises_on_missing_asset PASSED
tests/test_api.py::TestQueryExtensions::test_get_assets_count_returns_filtered_total PASSED

7 passed in 0.25s
```

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

All created files verified on disk. All task commits (cef659f, a775916, 76508b0) verified in git log.
