---
phase: 04-alert-system
plan: 02
subsystem: alerts
tags: [slack, email, discovery, shadow-detection, spend-spike, deduplication]

# Dependency graph
requires:
  - phase: 04-alert-system/04-01
    provides: EmailSender, DiscoveryAlert, SpendSpikeAlert types, email.py, types.py
  - phase: 01-data-foundation
    provides: AiAsset, DiscoveryEvent models, storage queries
  - phase: 02-detection-engine
    provides: shadow detection, new_asset_detected and provider_changed events
provides:
  - DiscoveryAlertEngine with check_shadow_alerts, check_new_provider_alerts, check_spend_spikes, run_all_checks
  - Slack payload builders for shadow, new provider, and spend spike alert types
  - SlackWebhookAlert.send_discovery and send_spend_spike methods
  - _build_alert_email_html helper for email dispatch
  - Deduplication via _fired_events and _fired_spikes sets
affects:
  - 05-dashboard
  - any future scheduler integration

# Tech tracking
tech-stack:
  added: []
  patterns:
    - DiscoveryAlertEngine orchestrates multi-channel dispatch (Slack + email) with fail-open per check
    - Deduplication sets stored in engine instance (process-lifetime persistence, not DB-backed)
    - Slack payload builder functions are module-level helpers (not methods) for testability
    - TYPE_CHECKING guard used for alert type imports in slack.py to avoid circular imports

key-files:
  created:
    - burnlens/alerts/discovery.py
    - tests/test_discovery_alerts.py
  modified:
    - burnlens/alerts/slack.py

key-decisions:
  - "Deduplication uses in-memory sets for process lifetime — no DB persistence needed for alert dedup"
  - "Deprecated/inactive assets excluded from spend spike checks — already known dormant, avoid re-alerting"
  - "Slack payload builders are module-level functions (not class methods) for easier standalone testing"
  - "run_all_checks wraps each sub-check individually in try/except — failure in one check does not block others"
  - "Spend spike threshold is ratio > 2.0 (200%) of 30-day average spend, zero avg spend is skipped (no baseline)"

patterns-established:
  - "Alert engine pattern: query since last_check → deduplicate by ID set → dispatch to Slack + email → track fired ID"
  - "Slack payload builder: module-level _build_X_payload(alert) → dict, matched to send method by alert_type"
  - "Fail-open dispatch: each send method catches Exception and logs warning, never raises to caller"

requirements-completed: [ALRT-01, ALRT-02, ALRT-05]

# Metrics
duration: 3min
completed: 2026-04-11
---

# Phase 4 Plan 02: Discovery Alert Engine Summary

**DiscoveryAlertEngine dispatching shadow, new-provider, and spend-spike alerts to Slack and email with process-lifetime deduplication**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-11T00:51:34Z
- **Completed:** 2026-04-11T00:54:30Z
- **Tasks:** 2 (both TDD)
- **Files modified:** 3

## Accomplishments

- Three Slack payload builders (_build_shadow_payload, _build_new_provider_payload, _build_spend_spike_payload) producing valid Slack block structures with appropriate emojis and alert details
- SlackWebhookAlert extended with send_discovery (routing by alert_type) and send_spend_spike methods, both fail-open
- DiscoveryAlertEngine class with three check methods (shadow, provider, spend spike), run_all_checks orchestrator, and per-process deduplication sets
- 31 tests covering payload structure, webhook dispatch, deduplication, fail-open behavior, and threshold logic

## Task Commits

Each task was committed atomically:

1. **Task 1: Slack payload builders for discovery alerts** - `3e6efa9` (feat)
2. **Task 2: DiscoveryAlertEngine with deduplication and dispatch** - `cbdc17c` (feat)

_Note: TDD tasks — tests written first (RED), implementation followed (GREEN), all 31 tests pass_

## Files Created/Modified

- `burnlens/alerts/slack.py` — Extended with _build_shadow_payload, _build_new_provider_payload, _build_spend_spike_payload, send_discovery, send_spend_spike
- `burnlens/alerts/discovery.py` — New: DiscoveryAlertEngine class with full check/dispatch/dedup logic, _build_alert_email_html helper
- `tests/test_discovery_alerts.py` — New: 31 tests covering all payload builders, dispatch methods, engine checks, and edge cases

## Decisions Made

- Deduplication uses in-memory sets for process lifetime — no DB persistence needed for dedup; the engine is expected to be a long-running singleton process
- Deprecated/inactive assets are excluded from spend spike checks to avoid re-alerting on already-known dormant assets
- Slack payload builder functions are module-level (not class methods) for easier standalone unit testing
- run_all_checks wraps each check method individually in try/except — a DB failure in shadow check does not prevent provider or spend-spike checks
- Spend spike threshold is ratio > 2.0 (200% of baseline), zero avg_spend is skipped (no baseline available yet)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- DiscoveryAlertEngine is ready to be integrated into the APScheduler hourly job in Phase 5 / the proxy server
- All dispatch methods are fail-open and safe to call from the proxy event loop
- Phase 5 (Dashboard) can reference discovery alerts for real-time alert feed display

---
*Phase: 04-alert-system*
*Completed: 2026-04-11*
