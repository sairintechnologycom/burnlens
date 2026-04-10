---
phase: 02-detection-engine
plan: 03
subsystem: detection-scheduler, proxy-interceptor
tags: [apscheduler, detection, proxy, asset-upsert, shadow-discovery]
dependency_graph:
  requires: [02-01, 02-02]
  provides: [detection-scheduler, proxy-asset-upsert]
  affects: [proxy/server.py, proxy/interceptor.py]
tech_stack:
  added: [APScheduler AsyncIOScheduler, IntervalTrigger]
  patterns: [scheduler-singleton, fail-open-async, non-blocking-create-task]
key_files:
  created:
    - burnlens/detection/scheduler.py
  modified:
    - burnlens/proxy/server.py
    - burnlens/proxy/interceptor.py
    - tests/test_detection_billing.py
    - tests/test_proxy.py
decisions:
  - first_run_deferred_by_one_hour: Deferred first detection run by 1 hour per research guidance — avoids immediate run on startup before proxy has processed traffic
  - module_singleton_with_reset: _scheduler module-level singleton with reset_scheduler() for testability — avoids recreating scheduler on each request
  - original_headers_passed_through: original_headers param added to _handle_non_streaming and _handle_streaming — required to extract raw auth token for hashing before headers are cleaned
  - streaming_upsert_after_stream_close: Asset upsert fires inside _stream_generator finally block after stream ends — ensures non-blocking and correct sequencing
metrics:
  duration_minutes: 4
  completed_date: "2026-04-10"
  tasks_completed: 2
  files_created: 1
  files_modified: 4
---

# Phase 02 Plan 03: Scheduler Wiring and Proxy Asset Upsert Summary

**One-liner:** APScheduler hourly detection runs wired into FastAPI lifespan + proxy interceptor upserts ai_assets SHA-256-keyed row on every forwarded request via non-blocking asyncio.create_task.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | APScheduler wiring + server lifespan integration | 45b58f9 | burnlens/detection/scheduler.py, burnlens/proxy/server.py, tests/test_detection_billing.py |
| 2 | Proxy interceptor asset upsert extension | 363ff10 | burnlens/proxy/interceptor.py, tests/test_proxy.py |

## What Was Built

### scheduler.py (new)

Module-level `AsyncIOScheduler` singleton exposed via `get_scheduler()` / `reset_scheduler()`. `register_detection_jobs()` registers one hourly job (`id="detection_hourly"`) with `next_run_time = now + 1 hour` — the first run is deferred so startup is not impacted. `run_detection()` calls `run_all_parsers` + `classify_new_assets` in sequence, wrapping everything in a try/except that logs and swallows all exceptions (fail open).

### server.py (updated)

Lifespan now imports `get_scheduler` / `register_detection_jobs` lazily (avoiding circular imports), starts the scheduler after AlertEngine setup, and shuts it down with `wait=False` during shutdown — before the httpx client is closed.

### interceptor.py (updated)

Two new private functions:
- `_extract_api_key_hash(headers)` — extracts token from `Authorization: Bearer <token>` or `x-api-key` header, returns SHA-256 hex digest or None.
- `_upsert_asset(db_path, provider_name, model, endpoint_url, api_key_hash)` — thin fail-open wrapper around `upsert_asset_from_detection` from Plan 02.

Both `_handle_non_streaming` and `_handle_streaming` accept a new `original_headers` parameter (passed from `handle_request` before header cleaning). After forwarding, `asyncio.create_task(_upsert_asset(...))` fires — zero latency added to the proxy path.

## Tests Added

**test_detection_billing.py (3 new):**
- `test_scheduler_registers_job` — verifies detection_hourly job exists with IntervalTrigger, first run 55–65 min from now
- `test_run_detection_calls_parsers` — mocks run_all_parsers + classify_new_assets, verifies both called with correct args
- `test_run_detection_swallows_errors` — verifies run_detection does not raise when parsers fail

**test_proxy.py (5 new):**
- `test_proxy_upserts_asset` — end-to-end: handle_request creates ai_assets row with correct provider/model/endpoint, key is hashed
- `test_proxy_upserts_asset_no_duplicate` — two requests → exactly one asset row
- `test_extract_api_key_hash_bearer` — Bearer token hashed correctly
- `test_extract_api_key_hash_x_api_key` — x-api-key header hashed correctly
- `test_extract_api_key_hash_no_auth_returns_none` — returns None with no auth header

## Verification

Full test suite: **412 passed, 1 skipped** (pre-existing skip unrelated to this plan).

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written. One minor implementation note: `original_headers` parameter was added to both `_handle_non_streaming` and `_handle_streaming` (plan only specified the non-streaming path explicitly) to ensure consistent API key capture for streaming requests. This is consistent with the plan's design intent.

## Self-Check: PASSED

- burnlens/detection/scheduler.py: FOUND
- burnlens/proxy/server.py modified with scheduler: FOUND (contains register_detection_jobs)
- burnlens/proxy/interceptor.py modified with _upsert_asset: FOUND
- Commits 45b58f9 and 363ff10: FOUND
