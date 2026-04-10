---
phase: 02-detection-engine
plan: 04
subsystem: detection
tags: [httpx, async, transport, sdk, interceptor, sha256, openai, anthropic]

# Dependency graph
requires:
  - phase: 02-detection-engine
    provides: upsert_asset_from_detection, match_provider from classifier.py

provides:
  - BurnLensTransport: async httpx transport that logs AI API call metadata without consuming response body
  - wrap(): public function that replaces client._client._transport in place, returns same client
  - burnlens.wrap() re-exported from package top-level

affects:
  - 02-detection-engine (DETC-08 proxy path)
  - 05-dashboard (any UI showing SDK-intercepted assets)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Fire-and-forget asyncio.create_task for non-blocking metadata logging in hot path
    - Best-effort model extraction from URL path segments (v1 prefix stripped, /models/{id} detected)
    - SHA-256 hashing of Authorization Bearer tokens before any storage
    - Fail-open: all logging errors caught and emitted as warnings, never raised

key-files:
  created:
    - burnlens/detection/wrapper.py
    - tests/test_detection_wrapper.py
  modified:
    - burnlens/__init__.py

key-decisions:
  - "asyncio.create_task (fire-and-forget) used for logging — response returned immediately, never delayed by DB write"
  - "response.status_code is safe to read (header-level attribute); response.aread/read/stream are never called to preserve streaming"
  - "Model extracted from URL path only (best-effort) — token counts are NOT available via SDK path, they come from DETC-08 proxy"
  - "wrap() mutates client in place and returns same object — enables chaining without requiring user to reassign"
  - "Sync client detection: warning logged and client returned unmodified (Phase 2 scope is async only)"

patterns-established:
  - "Transport interception pattern: wrap inner transport, delegate handle_async_request, log asynchronously"
  - "URL-based provider inference: hostname label matching for openai/anthropic/google/bedrock/cohere"
  - "Path-based model hint: strip version prefix (v1), detect /models/{id} pattern, fallback to first two segments"

requirements-completed: [DETC-07]

# Metrics
duration: 3min
completed: 2026-04-10
---

# Phase 02 Plan 04: SDK Transport Interceptor Summary

**httpx AsyncBaseTransport wrapper that logs model, latency, and status code to ai_assets without consuming the response body, re-exported as burnlens.wrap()**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-04-10T13:08:01Z
- **Completed:** 2026-04-10T13:10:39Z
- **Tasks:** 1 (TDD: test commit + feat commit)
- **Files modified:** 3

## Accomplishments

- BurnLensTransport wraps any httpx.AsyncBaseTransport and logs metadata asynchronously via asyncio.create_task
- Response body is never consumed (status_code is a header-level attribute, safe to read)
- API key from Authorization header is SHA-256 hashed before passing to upsert_asset_from_detection
- wrap() replaces client._client._transport in place and returns the same client object
- burnlens.wrap() importable from package top-level (burnlens.__init__ updated)
- 8 tests all pass; full suite 407 passed / 1 skipped

## Task Commits

Each task was committed atomically:

1. **RED - Failing tests** - `0cc2a31` (test)
2. **GREEN - BurnLensTransport + wrap() implementation** - `55d748a` (feat)

_TDD plan: two commits (test → feat). No refactor commit needed._

## Files Created/Modified

- `burnlens/detection/wrapper.py` - BurnLensTransport class and wrap() function
- `tests/test_detection_wrapper.py` - 8 tests covering transport behavior and wrap() semantics
- `burnlens/__init__.py` - Added re-export of wrap for top-level access

## Decisions Made

- asyncio.create_task used (not asyncio.ensure_future) for fire-and-forget logging — response returned to caller before DB write completes
- response.status_code is read safely (it is a header-level attribute in httpx, not body-level); aread/read/stream never called
- Model extracted from URL path only; token counts are out of scope for SDK path (DETC-08 proxy path handles tokens)
- wrap() mutates client and returns same object for chaining ergonomics
- Sync clients: warning logged, client returned unmodified — Phase 2 scope is async only

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. All 8 specified test behaviors mapped cleanly to implementation. Pre-existing unrelated warnings (coroutine GeneratorExit in recommender tests) are out of scope.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- DETC-07 requirement complete: SDK wrapper detection path available
- burnlens.wrap() is importable and usable with AsyncOpenAI/AsyncAnthropic
- DETC-08 (proxy-based token counting) can proceed independently
- Phase 3 API layer can expose SDK-detected assets alongside proxy-detected ones

---
*Phase: 02-detection-engine*
*Completed: 2026-04-10*
