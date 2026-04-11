---
phase: 05-discovery-dashboard
verified: 2026-04-11T08:45:00Z
status: human_needed
score: 7/7 must-haves verified
human_verification:
  - test: "Visit http://localhost:8420/ui/discovery and confirm summary cards display live values (not zeros) for total assets, active this month, shadow detected, unassigned, and monthly spend"
    expected: "All 5 KPI cards show non-empty numeric values from /api/v1/assets/summary"
    why_human: "Cannot run the server or inspect runtime DOM values programmatically"
  - test: "Verify provider donut chart renders colored segments (not blank canvas)"
    expected: "Chart.js doughnut renders with labeled segments matching provider counts"
    why_human: "Chart rendering requires a browser with JS execution"
  - test: "Click a column header in the asset table and confirm the sort arrow indicator appears and rows reorder"
    expected: "Active column shows triangle indicator; rows sorted correctly"
    why_human: "Client-side sort behavior requires browser interaction"
  - test: "If shadow assets exist: click Approve on a shadow card and confirm the card fades out without page reload"
    expected: "Card disappears, shadow count badge decrements, summary cards refresh"
    why_human: "Animation and DOM mutation require browser; no shadow assets guaranteed in CI"
  - test: "If shadow assets exist: click Assign Team, type a name, click Save, and confirm team name appears on the card"
    expected: "Card updates inline with team name; no page reload"
    why_human: "Inline edit flow requires browser interaction"
  - test: "Type in global search box and confirm asset table updates after brief pause"
    expected: "Table shows only assets matching the search term; debounce prevents over-calling"
    why_human: "Debounce timing and live filtering require browser interaction"
  - test: "Click Save View, enter a name, save it, then reload the page and confirm the view appears in the dropdown"
    expected: "Named view persists across page reload via localStorage"
    why_human: "localStorage persistence requires browser; cannot inspect in CI"
---

# Phase 5: Discovery Dashboard Verification Report

**Phase Goal:** Users have a single-pane web view of their entire AI footprint with search, filter, shadow review, and saved views
**Verified:** 2026-04-11T08:45:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (from ROADMAP.md Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Discovery page shows summary cards for total assets, active this month, shadow detected, unassigned, and monthly spend — live data | VERIFIED | `discovery.html` has all 5 KPI card IDs (kpi-total-assets, kpi-active-month, kpi-shadow, kpi-unassigned, kpi-monthly-spend). `discovery.js` `fetchAssetSummary()` calls `/api/v1/assets/summary` and populates all 5 cards. Route `/ui/discovery` registered via `FileResponse` in `server.py:184-186`. |
| 2 | Provider breakdown donut chart shows asset count segmented by provider | VERIFIED | `discovery.html` has `<canvas id="provider-chart">`. `discovery.js` `renderProviderChart()` uses Chart.js `Doughnut` with `by_provider` data from summary response. Chart called in `fetchAssetSummary()`. |
| 3 | Asset table is sortable by any column and filterable by provider, status, risk tier, team, and date range simultaneously | VERIFIED | All 8 table headers have `class="sortable" data-col="..."`. `_assetSort` state tracks column/direction. `sortAssetData()` re-sorts after each `fetchAssets()`. Filter dropdowns (`filter-provider`, `filter-status`, `filter-risk`, `filter-team`, `filter-date-since`) each trigger `fetchAssets()` on change. |
| 4 | Shadow AI alert panel lists all shadow-status assets with inline approve and assign-team actions that persist on click | VERIFIED | `fetchShadowAssets()` fetches `/api/v1/assets?status=shadow&limit=100`. `handleApprove()` sends a POST to `/api/v1/assets/{id}/approve` with full response handling (200: fade-out + badge decrement; 409: already-approved message; error: inline message). `handleAssignTeam()` sends a PATCH to `/api/v1/assets/{id}` with `{owner_team}` and updates card inline on success. |
| 5 | Discovery event timeline shows new assets, model changes, and alerts in chronological order | VERIFIED | `fetchTimeline()` calls `apiFetch('/discovery/events?limit=30')` which resolves to `/api/v1/discovery/events?limit=30`. Events rendered in `#timeline-panel` with color-coded type badges and `fmtRelativeTime()` timestamps. Wired into `refresh()` for 30s auto-refresh. |
| 6 | Global search returns matching assets when querying by model name, provider, team, endpoint URL, or tag | VERIFIED | `search_query` parameter added to `get_assets()` and `get_assets_count()` in `queries.py` (OR LIKE across 5 columns). `list_assets()` in `assets.py` accepts `search: str` query param passed as `search_query`. `handleSearch()` debounces 300ms and sets `_filterSearch`, appended by `fetchAssets()` via `params.set('search', _filterSearch)`. All 8 `TestAssetSearch` tests pass. |
| 7 | User can save a filter combination as a named view and reload it to restore the same filters | VERIFIED | `saveView()`, `loadView()`, `deleteView()`, `renderSavedViewsDropdown()` implemented in `discovery.js`. Key `burnlens_saved_views` stored as JSON array in localStorage. `getCurrentFilters()` captures all filter state. `loadView()` syncs both DOM values and JS module-level `_filter*` variables before calling `fetchAssets()`. All UI elements present in `discovery.html` (`saved-views-select`, `save-view-btn`, `delete-view-btn`, `save-view-form`). |

**Score: 7/7 truths verified**

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `burnlens/dashboard/static/discovery.html` | Full page structure with all sections | VERIFIED | 185 lines. Contains all 14 required structural elements: 5 KPI cards, provider-chart canvas, new-this-week panel, global-search input, save-view-bar, filter-bar, asset-table with 8 sortable headers, pagination, shadow-panel-section, timeline-section. |
| `burnlens/dashboard/static/discovery.js` | All fetch, chart, sort, filter, shadow actions, timeline, search, saved views | VERIFIED | 1074 lines. All 12 required functions present: `fetchAssetSummary`, `fetchAssets`, `renderProviderChart`, `fetchShadowAssets`, `handleApprove`, `handleAssignTeam`, `fetchTimeline`, `handleSearch`, `saveView`, `loadView`, `deleteView`, `renderSavedViewsDropdown`. |
| `burnlens/dashboard/static/style.css` | Discovery-specific styles including discovery grid, badges, timeline, search, saved views | VERIFIED | 1049 lines. Discovery section present. Contains: `discovery-kpi-grid`, `kpi-shadow` orange highlight, status badge variants, `shadow-card` with orange left border, `timeline-panel`/`timeline-event`, `#global-search`, `save-view-bar`/`.save-view-form`, pagination controls. |
| `burnlens/proxy/server.py` | `/ui/discovery` FileResponse route | VERIFIED | Route at lines 184-186: `@app.get("/ui/discovery")` returns `FileResponse(_static_dir / "discovery.html")`. Registered before `StaticFiles` mount. |
| `burnlens/storage/queries.py` | `search_query` parameter on `get_assets` and `get_assets_count` | VERIFIED | Lines 81 and 144: both functions accept `search_query: str | None = None`. OR LIKE clause across `model_name`, `provider`, `owner_team`, `endpoint_url`, `tags` columns. |
| `burnlens/api/assets.py` | `search` query parameter on `list_assets` endpoint | VERIFIED | Line 68: `search: str | None = None` parameter. Passed as `search_query=search` to both `get_assets()` and `get_assets_count()` at lines 88-99. |
| `burnlens/dashboard/static/index.html` | Navigation link to /ui/discovery | VERIFIED | Line 18: anchor tag pointing to `/ui/discovery` with class `nav-link` and text "Discovery" in header. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `discovery.js` | `/api/v1/assets/summary` | `apiFetch('/assets/summary')` with `API_V1` base | WIRED | Line 113. Result populates all 5 KPI cards and seeds filter dropdowns. |
| `discovery.js` | `/api/v1/assets` | `apiFetch(path)` with URLSearchParams query | WIRED | Line 299. Includes provider, status, risk_tier, owner_team, date_since, search, limit, offset params. |
| `discovery.js` | `/api/v1/assets/{id}/approve` | `fetch(API_V1 + '/assets/' + assetId + '/approve', {method: 'POST'})` | WIRED | Line 552. Full response handling: success, 409, and network error paths. |
| `discovery.js` | `/api/v1/assets/{id}` (PATCH) | `fetch(API_V1 + '/assets/' + assetId, {method: 'PATCH', ...})` | WIRED | Line 615. Body sends `owner_team`. On success, card updates inline. |
| `discovery.js` | `/api/v1/discovery/events` | `apiFetch('/discovery/events?limit=30')` | WIRED | Line 690. Events rendered with type badges and relative timestamps. |
| `server.py` | `discovery.html` | `FileResponse(_static_dir / "discovery.html")` | WIRED | Lines 184-186. Route registered before `StaticFiles` mount. |
| `discovery.js` | `localStorage` | `getSavedViews()` / `persistSavedViews()` using `localStorage.getItem/setItem` | WIRED | Lines 832-845. JSON array stored under `burnlens_saved_views`. Loaded on page init via `renderSavedViewsDropdown()`. |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| DASH-01 | 05-01 | Summary cards (total assets, active, shadow, unassigned, monthly spend) | SATISFIED | All 5 KPI card IDs in HTML; `fetchAssetSummary()` populates from `/api/v1/assets/summary` |
| DASH-02 | 05-01 | Provider breakdown donut chart | SATISFIED | `<canvas id="provider-chart">` + `renderProviderChart()` with Chart.js Doughnut |
| DASH-03 | 05-01 | Sortable, filterable asset table | SATISFIED | 8 sortable `th` headers; 5 filter dropdowns + date input; `sortAssetData()` + filter change handlers |
| DASH-04 | 05-02 | Shadow AI alert panel with inline approve/assign actions | SATISFIED | `fetchShadowAssets()`, `handleApprove()` (POST), `handleAssignTeam()` (PATCH) — all fully wired |
| DASH-05 | 05-02 | Discovery event timeline | SATISFIED | `fetchTimeline()` + `/api/v1/discovery/events?limit=30` + color-coded event rendering |
| DASH-06 | 05-01 | "New this week" section | SATISFIED | `renderNewThisWeek()` fetches with `date_since={7_days_ago}` when `summary.new_this_week > 0`; empty state for zero |
| DASH-07 | 05-02 | Global search by model, provider, team, URL, tag | SATISFIED | `search_query` OR LIKE in `queries.py`; `search` param in `assets.py`; debounced `handleSearch()` in JS; 8 tests pass |
| DASH-08 | 05-03 | Save/load named filter views | SATISFIED | `saveView`/`loadView`/`deleteView` with localStorage persistence; dropdown UI; survives page reload |

No orphaned requirements — all 8 DASH-0x IDs appear in plan frontmatter and are accounted for.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `discovery.js` | 845 | `return []` in catch block | Info | Intentional fail-open behavior for malformed localStorage data — documented in 05-03-SUMMARY key-decisions |
| `discovery.js` | 572 | Direct DOM write used for static hardcoded empty-state string in shadow panel | Info | Only sets a trusted constant (no user input), but deviates from the project's `textContent`/`createElement` XSS policy noted in 05-01-SUMMARY |

No blockers found.

### Human Verification Required

All automated checks pass. The following behaviors require browser execution to confirm end-to-end:

#### 1. Live KPI Card Data

**Test:** Start BurnLens (`python -m burnlens start`) and visit `http://localhost:8420/ui/discovery`
**Expected:** All 5 summary cards show non-zero live values from the asset API
**Why human:** Server must be running; DOM values cannot be inspected without a browser

#### 2. Provider Donut Chart Renders

**Test:** On the discovery page, confirm the donut chart has colored segments with provider labels
**Expected:** Chart.js renders a doughnut with at least one segment per provider
**Why human:** Chart rendering requires JS execution in a browser context

#### 3. Column Sort Interaction

**Test:** Click any column header in the asset table; click it again
**Expected:** First click sorts ascending (triangle up); second click sorts descending (triangle down); rows reorder
**Why human:** Client-side sort + CSS class toggling requires browser interaction

#### 4. Shadow Approve Inline Action

**Test:** If shadow assets exist, click "Approve" on a shadow card
**Expected:** Card fades out and disappears; shadow count badge decrements; no page reload
**Why human:** Animation + async DOM removal + badge update require browser; shadow asset availability not guaranteed in CI

#### 5. Shadow Assign Team Inline Action

**Test:** Click "Assign Team" on a shadow card, type a team name, click Save
**Expected:** Inline input replaces button; team name appears on card after save; no page reload
**Why human:** Inline edit flow requires browser interaction

#### 6. Global Search Debounce

**Test:** Type "gpt" in the search box and wait approximately 400ms
**Expected:** Asset table updates to show only matching assets; API called once, not on every keystroke
**Why human:** Debounce timing and live filtering require browser interaction

#### 7. Saved Views localStorage Persistence

**Test:** Save a view with a name, reload the page, open the saved views dropdown
**Expected:** Saved view appears in dropdown; selecting it restores all filter values
**Why human:** localStorage read/write and dropdown population require browser; cannot inspect localStorage in CI

### Gaps Summary

No gaps found. All 7 observable truths from the ROADMAP success criteria are verified at all three levels (exists, substantive, wired). All 8 DASH requirements are satisfied by complete implementations. All 5 documented commits (`8b7e09d`, `f045d66`, `cc42566`, `e71cda6`, `6eb7685`) exist in git history and match their described changes. The 8 `TestAssetSearch` tests pass. Status is `human_needed` because interactive browser behaviors (chart rendering, sort animation, shadow inline actions, localStorage persistence across reload) cannot be confirmed programmatically.

---

_Verified: 2026-04-11T08:45:00Z_
_Verifier: Claude (gsd-verifier)_
