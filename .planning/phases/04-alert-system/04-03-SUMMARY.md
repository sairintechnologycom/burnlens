---
phase: 04-alert-system
plan: "03"
subsystem: alerts
tags: [alerts, digests, scheduler, email, apscheduler]
dependency_graph:
  requires:
    - 04-01  # EmailSender, types (DigestPayload), storage queries (get_model_change_events_since, get_inactive_assets)
    - 04-02  # DiscoveryAlertEngine with run_all_checks()
  provides:
    - Daily digest email (model changes last 24h) — ALRT-03
    - Weekly digest email (inactive assets >30 days) — ALRT-04
    - Hourly discovery alert job on APScheduler — ALRT-01, ALRT-02, ALRT-05
    - Full alert system wired to FastAPI lifespan
  affects:
    - burnlens/proxy/server.py (lifespan creates DiscoveryAlertEngine, registers alert jobs)
    - burnlens/detection/scheduler.py (3 new jobs + wrapper functions)
tech_stack:
  added: []
  patterns:
    - APScheduler CronTrigger for 8 AM UTC daily/weekly jobs
    - Fail-open wrapper functions for all scheduled jobs
    - TDD (RED→GREEN) for digest functions
key_files:
  created:
    - burnlens/alerts/digests.py
    - tests/test_digests.py
  modified:
    - burnlens/detection/scheduler.py
    - burnlens/proxy/server.py
decisions:
  - register_alert_jobs separated from register_detection_jobs — single responsibility, each function registers its own concerns
  - Wrapper functions (_run_discovery_alerts, _run_daily_digest, _run_weekly_digest) isolate fail-open logic from job setup
  - Lazy imports in wrapper functions (from burnlens.alerts.digests import ...) avoid circular import at module load time
  - send_daily_digest returns 0 (not raises) when all events reference missing assets — consistent no-op contract
metrics:
  duration: "3 min"
  completed_date: "2026-04-11"
  tasks_completed: 2
  files_changed: 4
---

# Phase 04 Plan 03: Alert Scheduler Wiring Summary

**One-liner:** Digest generation (daily model changes, weekly inactive assets) and DiscoveryAlertEngine wired to APScheduler and FastAPI lifespan with three new fail-open cron/interval jobs.

## What Was Built

### burnlens/alerts/digests.py (new, 180 lines)

Two async digest functions:

- `send_daily_digest(db_path, email_sender, recipients)` — queries `model_changed` events from the last 24 hours, builds an HTML table, sends via EmailSender. Returns count of events sent. No-op if no recipients, no events, or all events reference missing assets.
- `send_weekly_digest(db_path, email_sender, recipients)` — queries assets inactive >30 days, builds HTML table with model/provider/team/last-active/status columns. No-op if no recipients or no assets.
- `_build_html_table` / `_build_digest_html` — helpers producing email-compatible inline-styled HTML with BurnLens branding.

### burnlens/detection/scheduler.py (extended)

Added `register_alert_jobs(scheduler, db_path, config, discovery_engine)` that registers:

| Job ID | Trigger | Action |
|--------|---------|--------|
| `discovery_alerts_hourly` | IntervalTrigger(hours=1), first run +1h | `_run_discovery_alerts` → `discovery_engine.run_all_checks()` |
| `daily_digest` | CronTrigger(hour=8, minute=0) | `_run_daily_digest` → `send_daily_digest` |
| `weekly_digest` | CronTrigger(day_of_week='mon', hour=8, minute=0) | `_run_weekly_digest` → `send_weekly_digest` |

Wrapper functions use lazy imports to avoid circular imports and swallow all exceptions (fail-open).

### burnlens/proxy/server.py (extended)

In the FastAPI lifespan:
- Creates `DiscoveryAlertEngine(config, config.db_path)` after `AlertEngine`
- Calls `register_alert_jobs(_scheduler, config.db_path, config, _discovery_alert_engine)` after `register_detection_jobs`

Full scheduler now manages 4 jobs total: `detection_hourly`, `discovery_alerts_hourly`, `daily_digest`, `weekly_digest`.

### tests/test_digests.py (new, 8 tests)

| Test | Coverage |
|------|----------|
| `test_daily_digest_returns_zero_no_recipients` | No-op path |
| `test_daily_digest_returns_zero_no_events` | No-op path |
| `test_daily_digest_sends_email_with_events` | Happy path — subject, HTML content |
| `test_daily_digest_skips_events_with_missing_asset` | Edge case: all events skipped |
| `test_weekly_digest_returns_zero_no_recipients` | No-op path |
| `test_weekly_digest_returns_zero_no_inactive_assets` | No-op path |
| `test_weekly_digest_sends_email_with_inactive_assets` | Happy path — subject, HTML content |
| `test_register_alert_jobs_adds_three_jobs` | Integration: 3 job IDs registered |

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

All created files verified on disk. Both task commits confirmed in git log:
- `a7caa0c` feat(04-03): implement daily and weekly digest email functions
- `d4e9424` feat(04-03): wire alert jobs to scheduler and server lifespan
