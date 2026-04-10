---
phase: 02-detection-engine
verified: 2026-04-10T14:00:00Z
status: passed
score: 14/14 must-haves verified
re_verification: false
gaps: []
human_verification:
  - test: "Run burnlens start and send a real OpenAI/Anthropic API call through the proxy"
    expected: "An ai_assets row is created in the database for the provider/model used"
    why_human: "End-to-end proxy upsert path requires a live server, real HTTP traffic, and database inspection"
  - test: "Call burnlens.wrap(AsyncOpenAI()) then make an API call"
    expected: "An ai_assets row appears with provider=openai, model extracted from URL"
    why_human: "SDK transport path requires a real async OpenAI client instance to exercise the transport replacement"
---

# Phase 02: Detection Engine Verification Report

**Phase Goal:** BurnLens automatically detects AI assets by parsing billing APIs and proxy traffic, classifies shadow usage, and schedules recurring detection runs
**Verified:** 2026-04-10T14:00:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | OpenAI billing parser returns asset records with model, api_key_id, and token counts from mocked API response | VERIFIED | `fetch_openai_usage` in billing.py lines 90-134; tested in test_detection_billing.py (14 tests, 35 detection tests pass) |
| 2 | Anthropic billing parser returns asset records with model and token counts from mocked API response | VERIFIED | `fetch_anthropic_usage` in billing.py lines 142-181; proper x-api-key + anthropic-version headers; paginated |
| 3 | Google billing parser returns empty list without error (proxy-only detection) | VERIFIED | `fetch_google_usage` in billing.py lines 189-206; returns [] with info log; design accepted in RESEARCH.md Pattern 4 |
| 4 | Parsers handle pagination (has_more + next_page) correctly | VERIFIED | `_paginate_usage` helper at billing.py lines 27-82; follows has_more + next_page cursor across all pages |
| 5 | Missing or invalid admin keys cause skip with warning, not crash | VERIFIED | Both `fetch_openai_usage` and `fetch_anthropic_usage` check `if admin_key is None` and return [] with logger.warning |
| 6 | An endpoint URL matching a provider_signatures pattern returns the correct provider name | VERIFIED | `match_provider` in classifier.py lines 43-66; fnmatch glob matching against all 7 seeded providers |
| 7 | An unknown endpoint URL returns None from match_provider | VERIFIED | classifier.py line 66: `return None` when no signature matches |
| 8 | A new asset with unrecognized provider/key is classified as shadow with a new_asset_detected event | VERIFIED | `upsert_asset_from_detection` classifier.py lines 69-134; creates AiAsset(status="shadow") + DiscoveryEvent(event_type="new_asset_detected") |
| 9 | An existing approved asset is never demoted back to shadow | VERIFIED | classifier.py lines 128-134: existing match goes to `_update_last_active` only, never changes status |
| 10 | APScheduler registers an hourly detection job that calls run_detection | VERIFIED | scheduler.py lines 51-80; IntervalTrigger(hours=1), id="detection_hourly"; run_detection calls run_all_parsers + classify_new_assets |
| 11 | Scheduler starts in FastAPI lifespan and stops on shutdown | VERIFIED | server.py lines 69-74 (start) and lines 79-81 (shutdown with wait=False) |
| 12 | First detection run is deferred (not immediate on startup) | VERIFIED | scheduler.py line 67: `first_run = datetime.now(timezone.utc) + timedelta(hours=1)`; passed as next_run_time |
| 13 | Proxy interceptor upserts an ai_assets row for each forwarded request | VERIFIED | interceptor.py lines 291-311 (`_upsert_asset`); called via `asyncio.create_task` in both `_handle_non_streaming` (line 458) and `_handle_streaming` (line 549) |
| 14 | burnlens.wrap(client) returns the same client object with intercepted transport | VERIFIED | wrapper.py lines 199-250; `__init__.py` re-exports wrap; BurnLensTransport replaces client._client._transport in place |

**Score:** 14/14 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `burnlens/detection/__init__.py` | Detection package init | VERIFIED | Exists, 91 bytes |
| `burnlens/detection/billing.py` | Billing API parsers for OpenAI, Anthropic, Google | VERIFIED | 306 lines; exports fetch_openai_usage, fetch_anthropic_usage, fetch_google_usage, run_all_parsers |
| `burnlens/config.py` | Admin key config fields | VERIFIED | openai_admin_key and anthropic_admin_key at lines 95-96; env var support at lines 228-231 |
| `tests/test_detection_billing.py` | Billing parser tests (min 80 lines) | VERIFIED | 558 lines; 35 tests pass |
| `burnlens/detection/classifier.py` | Provider signature matching and shadow classification | VERIFIED | 167 lines; exports match_provider, classify_new_assets, upsert_asset_from_detection |
| `tests/test_detection_classifier.py` | Classifier tests (min 60 lines) | VERIFIED | 206 lines; 10 tests pass |
| `burnlens/detection/scheduler.py` | APScheduler wiring for hourly detection | VERIFIED | 102 lines; exports get_scheduler, register_detection_jobs, run_detection |
| `burnlens/proxy/server.py` | Scheduler lifecycle in FastAPI lifespan | VERIFIED | Lines 69-81; contains get_scheduler, register_detection_jobs, scheduler.start(), scheduler.shutdown() |
| `burnlens/proxy/interceptor.py` | Asset upsert on proxy request | VERIFIED | Lines 291-311; _upsert_asset wraps upsert_asset_from_detection; called in both streaming and non-streaming paths |
| `burnlens/detection/wrapper.py` | SDK wrapper transport for async clients | VERIFIED | 250 lines; exports wrap, BurnLensTransport |
| `tests/test_detection_wrapper.py` | SDK wrapper tests (min 50 lines) | VERIFIED | 276 lines; 8 tests pass |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| billing.py | config.py | openai_admin_key, anthropic_admin_key | WIRED | billing.py imports BurnLensConfig; reads config.openai_admin_key and config.anthropic_admin_key in run_all_parsers |
| billing.py | storage/database.py | insert_asset, insert_discovery_event | WIRED | billing.py line 16-17: direct import; called in run_all_parsers lines 267, 274 |
| classifier.py | storage/queries.py | get_provider_signatures, get_assets | WIRED | classifier.py line 17: imports both; get_provider_signatures called in match_provider, get_assets called in upsert_asset_from_detection |
| classifier.py | storage/database.py | insert_asset, insert_discovery_event | WIRED | classifier.py line 15-16: imports both; called in upsert_asset_from_detection lines 111, 122 |
| scheduler.py | billing.py | run_all_parsers | WIRED | scheduler.py line 15: `from burnlens.detection.billing import run_all_parsers`; called in run_detection line 98 |
| scheduler.py | classifier.py | classify_new_assets | WIRED | scheduler.py line 16: `from burnlens.detection.classifier import classify_new_assets`; called in run_detection line 99 |
| server.py | scheduler.py | get_scheduler, register_detection_jobs | WIRED | server.py line 69 (lazy import); called lines 71-73 and 80 |
| interceptor.py | classifier.py | upsert_asset_from_detection | WIRED | interceptor.py lines 307-309: lazy import inside _upsert_asset; called in asyncio.create_task at lines 458-460 and 549-551 |
| wrapper.py | classifier.py | upsert_asset_from_detection | WIRED | wrapper.py line 33: `from burnlens.detection.classifier import upsert_asset_from_detection`; called in _log_metadata line 172 |
| burnlens/__init__.py | wrapper.py | wrap re-export | WIRED | __init__.py line 5: `from burnlens.detection.wrapper import wrap` |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| DETC-01 | 02-01 | System parses OpenAI billing API to detect models, usage volumes, and API key identifiers | SATISFIED | fetch_openai_usage calls /v1/organization/usage/completions with group_by[]=model,api_key_id; api_key_id SHA-256 hashed |
| DETC-02 | 02-01 | System parses Anthropic billing API to detect models, usage volumes, and API key identifiers | SATISFIED | fetch_anthropic_usage calls /v1/organizations/usage_report/messages with x-api-key + anthropic-version headers |
| DETC-03 | 02-01 | System parses Google AI billing API to detect models, usage volumes, and API key identifiers | SATISFIED (proxy-only) | fetch_google_usage returns [] by design; Google assets detected via proxy traffic (DETC-08). No Google billing API exists for Gemini Developer API tier — accepted design decision per RESEARCH.md Pattern 4 |
| DETC-04 | 02-02 | System matches endpoint URLs and headers against provider_signatures to auto-identify providers | SATISFIED | match_provider uses fnmatch glob against all 7 seeded provider signatures; case-insensitive; scheme-stripped |
| DETC-05 | 02-02 | System classifies endpoint as shadow if API key, model, provider, or team is unregistered/unapproved | SATISFIED | upsert_asset_from_detection creates AiAsset(status="shadow") for all new detections; approved assets never demoted |
| DETC-06 | 02-03 | System runs detection on a scheduled basis (hourly via APScheduler) | SATISFIED | AsyncIOScheduler with IntervalTrigger(hours=1), id="detection_hourly", first run deferred 1 hour |
| DETC-07 | 02-04 | SDK wrapper (burnlens.wrap(client)) intercepts calls and logs metadata without modifying payloads | SATISFIED | BurnLensTransport wraps httpx transport; response.aread() never called; status_code only (header-level); re-exported as burnlens.wrap() |
| DETC-08 | 02-03 | Proxy mode forwards AI SDK traffic and logs metadata only (model, tokens, latency, status code) | SATISFIED | _upsert_asset in interceptor.py; asyncio.create_task fires after response returned; both streaming and non-streaming paths covered |

All 8 requirement IDs claimed in plan frontmatter accounted for. No orphaned requirements detected.

### Anti-Patterns Found

None detected. Scanned billing.py, classifier.py, scheduler.py, wrapper.py, server.py, interceptor.py for TODO/FIXME/placeholder, empty implementations, and stub returns. All files contain substantive production code.

### Human Verification Required

#### 1. Proxy Asset Upsert End-to-End

**Test:** Start BurnLens (`burnlens start`), route an OpenAI API call through the proxy (`OPENAI_BASE_URL=http://localhost:8420/proxy/openai`), then query the SQLite database (`SELECT * FROM ai_assets`)
**Expected:** A row exists with provider="openai", model matching the requested model, endpoint_url="https://api.openai.com", and status="shadow"
**Why human:** Requires a live proxy server, a real or mocked upstream, and database inspection — not possible with unit-test grep-based verification

#### 2. SDK wrap() End-to-End

**Test:** `import burnlens; from openai import AsyncOpenAI; client = AsyncOpenAI(); burnlens.wrap(client)` then make a completion call
**Expected:** An ai_assets row appears in the database for provider="openai" with the model extracted from the URL path
**Why human:** Requires a real AsyncOpenAI client instance (or a compatible mock with _client._transport attribute) and database inspection

### Gaps Summary

No gaps. All 14 must-have truths are verified. All 11 artifacts exist with substantive implementation (not stubs). All 10 key links are wired with confirmed imports and call sites. All 8 requirement IDs are satisfied. All 8 documented commits are present in git history. Test suite is green: 412 passed, 1 pre-existing skip.

The only note worth flagging is DETC-03 (Google billing): the requirement text says "parses Google AI billing API" but the implementation is a documented proxy-only stub. This was an accepted design decision recorded in RESEARCH.md before implementation began (Pattern 4, lines 209-215). The REQUIREMENTS.md already marks DETC-03 as `[x]` complete, consistent with this scoping. It is not a gap.

---

_Verified: 2026-04-10T14:00:00Z_
_Verifier: Claude (gsd-verifier)_
