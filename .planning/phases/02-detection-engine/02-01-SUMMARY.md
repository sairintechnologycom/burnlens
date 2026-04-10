---
phase: 02-detection-engine
plan: 01
subsystem: detection
tags: [httpx, respx, billing-api, openai, anthropic, google, sqlite, sha256, pagination]

requires:
  - phase: 01-data-foundation
    provides: AiAsset/DiscoveryEvent dataclasses, insert_asset, insert_discovery_event, get_assets queries

provides:
  - "fetch_openai_usage(): polls /v1/organization/usage/completions with group_by model+api_key_id"
  - "fetch_anthropic_usage(): polls /v1/organizations/usage_report/messages with x-api-key header"
  - "fetch_google_usage(): stub returning [] (proxy-only detection)"
  - "_paginate_usage(): shared pagination helper following has_more/next_page"
  - "run_all_parsers(): orchestrates all parsers, upserts shadow assets, writes discovery events"
  - "BurnLensConfig extended with openai_admin_key and anthropic_admin_key fields"

affects: [03-api-layer, 04-alerts, 05-dashboard, detection-engine]

tech-stack:
  added: [respx (test mocking already installed), httpx (already in stack)]
  patterns: [TDD red-green cycle with respx HTTP mocking, fail-open error handling, sha256 key hashing]

key-files:
  created:
    - burnlens/detection/__init__.py
    - burnlens/detection/billing.py
    - tests/test_detection_billing.py
  modified:
    - burnlens/config.py

key-decisions:
  - "Google detection uses proxy traffic only — no billing admin API available with per-model breakdown"
  - "api_key_id from OpenAI billing API hashed via sha256 before storage — raw keys never persisted"
  - "Shared _paginate_usage() helper normalizes OpenAI (nested results[]) vs Anthropic (flat data[]) differences"
  - "run_all_parsers upsert pattern: get_assets() to check existence, then insert_asset or update last_active_at"
  - "Fail-open: HTTPStatusError and RequestError caught per-provider, logged, and skipped (never crash)"

patterns-established:
  - "Provider billing parser pattern: None admin_key -> warning + empty list, no exception"
  - "Pagination pattern: _paginate_usage with has_more/next_page cursor, shared across providers"
  - "Asset dedup key: provider + model_name + endpoint_url (not api_key_hash)"

requirements-completed: [DETC-01, DETC-02, DETC-03]

duration: 8min
completed: 2026-04-10
---

# Phase 2 Plan 01: Detection Engine Billing Parsers Summary

**Billing API parsers for OpenAI and Anthropic that discover shadow AI assets via organization usage endpoints, with SHA-256 key hashing, paginated HTTP fetch, and SQLite upsert with discovery events**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-04-10T12:35:00Z
- **Completed:** 2026-04-10T12:43:00Z
- **Tasks:** 1 (TDD: 2 commits — test RED + feat GREEN)
- **Files modified:** 4

## Accomplishments

- Billing parsers for OpenAI (`fetch_openai_usage`), Anthropic (`fetch_anthropic_usage`), and Google stub (`fetch_google_usage`) with proper auth headers and group_by params
- Shared pagination helper `_paginate_usage()` follows `has_more` + `next_page` cursor pattern
- `run_all_parsers()` orchestrates all three parsers, upserts `ai_asset` records as `shadow`, writes `new_asset_detected` discovery events, and skips duplicates
- `BurnLensConfig` extended with `openai_admin_key` and `anthropic_admin_key` with YAML + env var support
- 14 tests covering all scenarios: pagination, missing keys, auth headers, dedup, sha256 hashing, discovery events

## Task Commits

1. **Task 1 (RED): Test billing parsers** - `0f94ad6` (test)
2. **Task 1 (GREEN): Implement billing parsers** - `e452534` (feat)

## Files Created/Modified

- `burnlens/detection/__init__.py` — Detection package init
- `burnlens/detection/billing.py` — All billing parsers + `run_all_parsers` orchestrator
- `burnlens/config.py` — Added `openai_admin_key`, `anthropic_admin_key`, env var support
- `tests/test_detection_billing.py` — 14 tests covering all parser behaviors

## Decisions Made

- Google detection uses proxy traffic only — no suitable billing API with per-model breakdown
- api_key_id hashed via sha256 before storage — raw keys never reach the database
- Shared `_paginate_usage()` helper normalizes provider-specific response shapes (OpenAI nested `results[]` vs Anthropic flat `data[]`)
- Asset dedup key is provider + model_name + endpoint_url (not api_key_hash, which may be absent)
- Fail-open: `HTTPStatusError` and `RequestError` caught per-provider, logged, and skipped — never crashes

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required at this stage. Admin keys are optional; parsers return empty list gracefully when not set.

## Next Phase Readiness

- Billing parsers are ready for integration with the APScheduler hourly detection job (Phase 2 remaining plans)
- `run_all_parsers(db_path, config)` is the public API surface for the scheduler to call
- Full test suite green (396 passed, 1 skipped)

---
*Phase: 02-detection-engine*
*Completed: 2026-04-10*
