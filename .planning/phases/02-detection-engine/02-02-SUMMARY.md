---
phase: 02-detection-engine
plan: "02"
subsystem: detection
tags: [fnmatch, sqlite, aiosqlite, shadow-classification, provider-matching]

# Dependency graph
requires:
  - phase: 01-data-foundation
    provides: "insert_asset, insert_discovery_event, get_assets, get_provider_signatures, AiAsset, DiscoveryEvent, ProviderSignature models"
provides:
  - "match_provider: fnmatch glob URL → provider name (case-insensitive, scheme-stripping)"
  - "upsert_asset_from_detection: idempotent shadow asset creation with new_asset_detected event"
  - "classify_new_assets: periodic scan of shadow assets with unknown-provider logging"
affects: [03-api, 04-alerts, 05-dashboard]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "fnmatch glob pattern matching for URL-to-provider resolution"
    - "Upsert pattern: query existing → insert if missing, update last_active_at if found"
    - "Never-demote rule: approved status is immutable by detection engine"
    - "Private _update_last_active helper for atomic timestamp updates"

key-files:
  created:
    - burnlens/detection/__init__.py
    - burnlens/detection/classifier.py
    - tests/test_detection_classifier.py
  modified: []

key-decisions:
  - "fnmatch.fnmatch chosen for glob matching — lightweight, zero extra deps, handles wildcards like *.openai.azure.com/*"
  - "Scheme stripping uses split('://', 1)[-1] — handles both http and https and plain host paths uniformly"
  - "get_assets(provider=provider) narrows fetch scope before Python-level model+URL match — keeps query efficient"
  - "classify_new_assets returns examined count, not event count — function is a scan, not a creator"
  - "Approved assets update last_active_at only — no status change, enforced in upsert_asset_from_detection"

patterns-established:
  - "TDD red-green: failing test committed before implementation"
  - "Provider URL matching always strips scheme and lowercases both URL and pattern"
  - "Classifier module is the single entry point for shadow classification — storage layer does not classify"

requirements-completed: [DETC-04, DETC-05]

# Metrics
duration: 8min
completed: 2026-04-10
---

# Phase 02 Plan 02: Provider Signature Matcher and Shadow Classifier Summary

**fnmatch-based URL-to-provider matcher with idempotent shadow asset upsert, approved-status protection, and periodic classify_new_assets scan**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-04-10T13:00:00Z
- **Completed:** 2026-04-10T13:04:14Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 3

## Accomplishments

- `match_provider`: resolves any endpoint URL to a provider name using seeded provider_signatures glob patterns, with scheme stripping and case-insensitive matching
- `upsert_asset_from_detection`: idempotent — creates shadow asset + new_asset_detected event on first detection, updates last_active_at on re-detection, never demotes approved assets
- `classify_new_assets`: periodic scan over shadow assets, logs warning for unknown-provider endpoints, returns count examined
- 10 tests covering all 7 seeded providers (including Azure wildcard), unknown URLs, case-insensitivity, re-detection, approved-status protection, and integration scenario

## Task Commits

Each task was committed atomically:

1. **RED: failing tests** - `17c97e0` (test)
2. **GREEN: classifier implementation** - `8d81245` (feat)

## Files Created/Modified

- `/Users/bhushan/Documents/Projects/burnlens/burnlens/detection/__init__.py` - Detection engine package init
- `/Users/bhushan/Documents/Projects/burnlens/burnlens/detection/classifier.py` - match_provider, upsert_asset_from_detection, classify_new_assets, _update_last_active
- `/Users/bhushan/Documents/Projects/burnlens/tests/test_detection_classifier.py` - 10 tests covering full behavioral spec

## Decisions Made

- Used `fnmatch.fnmatch` for glob URL matching — no extra dependencies, handles `*.openai.azure.com/*` wildcard correctly
- Scheme stripping with `split("://", 1)[-1]` safely handles https, http, and plain host/path URLs
- Filter `get_assets(provider=provider)` before Python-level model+URL match to limit DB rows processed
- `classify_new_assets` returns examined count, not new-event count — it is a scan function, not an emitter
- `_update_last_active` is a private helper to keep the public API surface clean

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. All 10 tests passed on first GREEN run. Pre-existing failure in `tests/test_detection_billing.py` (missing `burnlens.detection.billing` module) is unrelated to this plan and was present before this execution.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Provider signature matching and shadow classification are complete and tested
- `upsert_asset_from_detection` is ready to be called from detection sources (billing API parsers, proxy interceptor)
- `classify_new_assets` is ready to be scheduled via APScheduler (hourly) in Phase 4
- Phase 3 (API layer) can expose `/api/v1/assets` using the storage layer directly — classifier not blocking

---
*Phase: 02-detection-engine*
*Completed: 2026-04-10*
