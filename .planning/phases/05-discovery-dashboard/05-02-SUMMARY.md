---
phase: 05-discovery-dashboard
plan: "02"
subsystem: discovery-dashboard
tags: [search, shadow-ai, timeline, ui, api]
dependency_graph:
  requires: [05-01]
  provides: [shadow-review-workflow, discovery-timeline, global-search]
  affects: [burnlens/dashboard/static/discovery.html, burnlens/dashboard/static/discovery.js, burnlens/dashboard/static/style.css, burnlens/storage/queries.py, burnlens/api/assets.py]
tech_stack:
  added: []
  patterns: [OR-LIKE search across multiple columns, event delegation for shadow panel actions, debounced search input, fade-out animation on card removal]
key_files:
  created: []
  modified:
    - burnlens/storage/queries.py
    - burnlens/api/assets.py
    - burnlens/dashboard/static/discovery.html
    - burnlens/dashboard/static/discovery.js
    - burnlens/dashboard/static/style.css
    - tests/test_api.py
decisions:
  - search_query uses OR LIKE across 5 columns (model_name, provider, owner_team, endpoint_url, tags) — tags column is JSON text so LIKE on serialized string handles tag value matching
  - Event delegation on #shadow-panel click handler — avoids attaching listeners to dynamically rendered cards
  - 300ms debounce on global-search input — prevents excessive API calls while typing
  - Fade-out CSS transition (opacity 0, 300ms) for approve action — visual feedback before DOM removal
  - fetchShadowAssets and fetchTimeline wired into refresh() — both update on 30s auto-refresh cycle
metrics:
  duration: 4 minutes
  completed: "2026-04-11"
  tasks: 2
  files: 5
requirements-completed: [DASH-04, DASH-05, DASH-07]
---

# Phase 5 Plan 02: Shadow Panel, Timeline, and Global Search Summary

**One-liner:** Shadow AI review panel with inline approve/assign-team actions, discovery event timeline, and server-side global search via OR LIKE across 5 asset columns.

## What Was Built

### Task 1: search_query parameter on get_assets/get_assets_count + assets API (TDD)

Added `search_query: str | None = None` to both `get_assets()` and `get_assets_count()` in `burnlens/storage/queries.py`. The parameter appends an OR-based WHERE clause searching across `model_name`, `provider`, `owner_team`, `endpoint_url`, and `tags` (JSON text stored as TEXT in SQLite — LIKE on the serialized string handles tag value matching).

Added `search: str | None = None` query parameter to the `list_assets()` endpoint in `burnlens/api/assets.py`, passed through as `search_query=search` to both query functions.

8 tests added to `TestAssetSearch` in `tests/test_api.py` covering model, provider, team, URL, tag, count, API endpoint, and combined filter scenarios. Tests followed TDD — written before implementation (RED), then made green (GREEN).

### Task 2: Shadow panel, timeline, and global search in discovery dashboard

**discovery.html:** Added global search input (`#global-search`) above the filter bar; added Shadow AI Alert Panel section (`#shadow-panel-section`) and Discovery Event Timeline section (`#timeline-section`) after the asset table section.

**discovery.js:** Added:
- `fetchShadowAssets()` — fetches `/api/v1/assets?status=shadow&limit=100`, renders shadow cards with model, provider, risk badge, endpoint, first-seen date
- `handleApprove(assetId)` — POST to `/api/v1/assets/{id}/approve`, fades out card on success, decrements count badge, handles 409 (already approved)
- `handleAssignTeam(assetId)` — replaces Assign Team button with inline input + Save, PATCH to `/api/v1/assets/{id}` with `owner_team`
- `fetchTimeline()` — fetches `/api/v1/discovery/events?limit=30`, renders color-coded events with relative timestamps
- `handleSearch()` — 300ms debounce on `#global-search`, sets `_filterSearch`, resets offset, calls `fetchAssets()`
- Event delegation on `#shadow-panel` for approve and assign-team button clicks
- `fmtRelativeTime()` helper for human-readable timestamps

**style.css:** Added styles for:
- `#global-search` — full-width dark input with SVG search icon via background-image
- `.shadow-panel` / `.shadow-card` — grid layout, orange left border, fade-out transition
- `.btn-approve` / `.btn-assign` / `.btn-save-team` / `.inline-input` — action button styles
- `.timeline-panel` / `.timeline-event` — vertical timeline with left border line and colored event icons
- `.shadow-count-badge` — orange pill badge for shadow count in section header

## Deviations from Plan

None — plan executed exactly as written.

## Test Results

```
tests/test_api.py::TestAssetSearch::test_search_by_model_name PASSED
tests/test_api.py::TestAssetSearch::test_search_by_provider PASSED
tests/test_api.py::TestAssetSearch::test_search_by_owner_team PASSED
tests/test_api.py::TestAssetSearch::test_search_by_endpoint_url PASSED
tests/test_api.py::TestAssetSearch::test_search_by_tag_value PASSED
tests/test_api.py::TestAssetSearch::test_get_assets_count_with_search PASSED
tests/test_api.py::TestAssetSearch::test_api_search_param PASSED
tests/test_api.py::TestAssetSearch::test_search_combines_with_provider_filter PASSED
36 passed in 0.74s (full test_api.py suite)
```

## Task Commits

| Task | Description | Commit |
|------|-------------|--------|
| 1 | search_query on get_assets, get_assets_count, assets API + 8 tests | cc42566 |
| 2 | Shadow panel, timeline, global search in discovery dashboard | e71cda6 |

## Self-Check: PASSED

All 7 files found. Both commits (cc42566, e71cda6) verified in git log.
