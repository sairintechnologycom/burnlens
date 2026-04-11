---
phase: 04-alert-system
plan: "01"
subsystem: alerts
tags: [email, alerts, queries, config, tdd]
dependency_graph:
  requires:
    - burnlens/storage/models.py (AiAsset, DiscoveryEvent)
    - burnlens/storage/database.py (init_db)
    - burnlens/config.py (EmailConfig, AlertsConfig)
  provides:
    - burnlens/alerts/types.py (DiscoveryAlert, SpendSpikeAlert, DigestPayload)
    - burnlens/alerts/email.py (EmailSender, send_email)
    - burnlens/storage/queries.py#get_new_shadow_events_since
    - burnlens/storage/queries.py#get_new_provider_events_since
    - burnlens/storage/queries.py#get_model_change_events_since
    - burnlens/storage/queries.py#get_inactive_assets
    - burnlens/storage/queries.py#get_asset_spend_history
    - burnlens/config.py#AlertsConfig.alert_recipients
  affects:
    - 04-02 (real-time alerts)
    - 04-03 (spend spike alerts)
    - 04-04 (digest emails)
tech_stack:
  added: []
  patterns:
    - asyncio.to_thread for blocking I/O in async context
    - smtplib (stdlib) for SMTP — no new pip dependency
    - Dynamic WHERE clause pattern (consistent with existing queries)
key_files:
  created:
    - burnlens/alerts/types.py
    - burnlens/alerts/email.py
    - tests/test_alerts.py
  modified:
    - burnlens/storage/queries.py
    - burnlens/config.py
decisions:
  - smtplib chosen over aiosmtplib to avoid adding 8th pip dependency
  - asyncio.to_thread wraps blocking smtplib for non-blocking event loop
  - Fail-open pattern applied to EmailSender.send() — exceptions logged, never raised
  - get_inactive_assets excludes status IN ('deprecated', 'inactive') per plan spec
  - get_asset_spend_history looks up asset model+provider then queries requests table
metrics:
  duration: "3 min"
  completed_date: "2026-04-11"
  tasks_completed: 2
  files_changed: 5
---

# Phase 4 Plan 1: Alert Foundation (Types, Email, Queries) Summary

**One-liner:** Discovery alert dataclasses + async smtplib email sender + 5 alert-focused query functions, zero new dependencies.

## What Was Built

### Task 1: Alert types, email sender, and config extension

Created the alert payload dataclasses needed by all three alert requirements:

- `DiscoveryAlert` — carries alert_type, AiAsset, DiscoveryEvent, and message for real-time shadow detection alerts
- `SpendSpikeAlert` — carries asset, current_spend, avg_spend, spike_ratio, period_days for anomaly detection
- `DigestPayload` — carries subject, items list, and generated_at for weekly digest emails

Created `EmailSender` in `burnlens/alerts/email.py`:
- Accepts `EmailConfig` in `__init__`
- `async send(to_addrs, subject, body_html)` wraps blocking `smtplib.SMTP` in `asyncio.to_thread()`
- Uses STARTTLS when port=587, plain SMTP otherwise
- No-op when `smtp_host` is None (logged at DEBUG level)
- All errors caught and logged — never propagated (fail-open)
- Module-level `send_email()` convenience function also provided

Extended `AlertsConfig` with `alert_recipients: list[str] = []` and updated `load_config()` to parse `alerts.alert_recipients` from YAML.

### Task 2: Discovery alert queries

Added 5 new async query functions to `burnlens/storage/queries.py`:

1. `get_new_shadow_events_since(db_path, since_iso)` — filters `discovery_events` on `event_type='new_asset_detected' AND detected_at >= since_iso`
2. `get_new_provider_events_since(db_path, since_iso)` — filters on `event_type='provider_changed' AND detected_at >= since_iso`
3. `get_model_change_events_since(db_path, since_iso)` — filters on `event_type='model_changed' AND detected_at >= since_iso`
4. `get_inactive_assets(db_path, inactive_days=30)` — returns assets where `last_active_at < date('now', '-N days') AND status NOT IN ('deprecated', 'inactive')`
5. `get_asset_spend_history(db_path, asset_id, days=30)` — looks up asset's model+provider, then `SUM(cost_usd)` from requests table within the period window

All functions use existing `_row_to_asset` / `_row_to_event` helpers for consistent deserialization.

## Test Results

26 tests written and passing:
- Dataclass construction tests (DiscoveryAlert, SpendSpikeAlert, DigestPayload)
- EmailSender: no-op when unconfigured, smtplib calls when configured, asyncio.to_thread usage, error handling
- AlertsConfig: default value, YAML parsing, absence handling
- Query functions: filtering by cutoff date, exclusion of deprecated/inactive assets, spend correlation, empty cases

## Deviations from Plan

None — plan executed exactly as written.

The 5 query functions (Task 2) and the alert types/email (Task 1) were developed in the same session but committed as separate atomic commits per the task boundaries.

## Self-Check: PASSED

All created files exist on disk. Both task commits (e1ffe04, 3ffac5f) verified in git log.
