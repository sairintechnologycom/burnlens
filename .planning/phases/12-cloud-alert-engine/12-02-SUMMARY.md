---
phase: 12
plan: 02
subsystem: burnlens_cloud
tags: [alert-engine, slack, email, cron, fail-open]
dependency_graph:
  requires: [burnlens_cloud/email.py, burnlens_cloud/config.py, alert_rules table, alert_events table]
  provides: [burnlens_cloud/alert_engine.py, evaluate_all_workspaces, evaluate_workspace]
  affects: [POST /cron/evaluate-alerts (Plan 03)]
tech_stack:
  added: [httpx (Slack dispatch)]
  patterns: [fail-open exception handling, 24h dedup via alert_events, per-rule per-workspace isolation]
key_files:
  created: [burnlens_cloud/alert_engine.py]
  modified: []
decisions:
  - Used `from .config import settings` — confirmed by reading email.py and billing.py both use this path
  - Used `settings.burnlens_frontend_url` — confirmed attribute exists in email.py lines 132 and 268
  - `_SLACK_HOST_PREFIX` constant used for URL validation before any HTTP call
  - webhook_url never logged (security — it is a secret)
  - alert_events row written with status=sent|failed even on dispatch failure (audit trail)
metrics:
  duration: "~5 minutes"
  completed: "2026-05-02"
  tasks_completed: 1
  files_created: 1
---

# Phase 12 Plan 02: Alert Engine Summary

**One-liner:** Core alert evaluation engine with 24h dedup, per-rule fail-open isolation, and Slack/email dual-channel dispatch.

## What Was Done

Created `burnlens_cloud/alert_engine.py` — the evaluation engine called hourly by `POST /cron/evaluate-alerts` (wired in Plan 03).

### Functions created

| Function | Description |
|---|---|
| `_should_fire(conn, rule_id, now)` | 24h dedup: returns True only if no alert_events row exists for this rule in the last 24h |
| `_dispatch_email(...)` | Delegates to `send_usage_warning_email`; threshold validated as "80" or "100" by callee |
| `_dispatch_slack(...)` | POSTs to Slack webhook; validates `https://hooks.slack.com/` prefix; never logs URL |
| `evaluate_workspace(conn, ...)` | Evaluates all enabled rules for one workspace; per-rule try/except; writes alert_events |
| `evaluate_all_workspaces(db_pool)` | Main cron entry point; fetches non-free workspaces; per-workspace try/except; returns `{"evaluated": N, "fired": M}` |

### Key design decisions confirmed from source reads

- **Import path:** `from .config import settings` (not `.settings`) — confirmed from `email.py:11` and `billing.py:17`
- **Frontend URL attribute:** `settings.burnlens_frontend_url` — confirmed used at `email.py:132` and `email.py:268`
- **No f-string SQL:** All queries use `$N` parameterized placeholders — zero SQL injection surface

## Verification Results

```
Syntax check:           OK
Async functions (5):    5  ✓
_SLACK_HOST_PREFIX (≥2): 3  ✓
f-string SQL (must=0):  0  ✓
send_usage_warning_email refs (≥2): 2  ✓
```

## Commits

| Hash | Message |
|---|---|
| 02d65e1 | feat(phase-12): create alert_engine.py with evaluation logic + Slack/email dispatch (Plan 02) |

## Deviations from Plan

None - plan executed exactly as written.

The settings import path and `burnlens_frontend_url` attribute were confirmed before writing, matching the plan's instructions.

## Known Stubs

None. The module is complete and functional. It depends on `alert_rules` and `alert_events` DB tables (created in Plan 01) and the `/cron/evaluate-alerts` route (wired in Plan 03).

## Threat Flags

None beyond the plan's own threat model. The Slack webhook URL is treated as a secret: validated by prefix, never logged, and stored encrypted in DB (per Plan 01 schema). The `_SLACK_HOST_PREFIX` check prevents SSRF to non-Slack hosts.

## Self-Check: PASSED

- `burnlens_cloud/alert_engine.py` exists and parses cleanly
- Commit `02d65e1` confirmed in git log
