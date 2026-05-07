---
phase: 12
slug: cloud-alert-engine
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-05
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 + pytest-asyncio |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `pytest tests/test_phase12_alerts.py -x --tb=short` |
| **Full suite command** | `pytest tests/test_phase12_alerts.py tests/test_settings_api.py -v` |
| **Estimated runtime** | ~1 second |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_phase12_alerts.py -x --tb=short`
- **After every plan wave:** Run `pytest tests/test_phase12_alerts.py tests/test_settings_api.py -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 1 second

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 12-01-01 | 01 | 1 | ALERT-01 | T-12-05 | Seeding INSERT has NOT EXISTS guard — never double-seeds | static | `pytest tests/test_phase12_alerts.py::test_alert_rules_seeding_sql_present` | ✅ | ✅ green |
| 12-01-02 | 01 | 1 | ALERT-02 | T-12-04 | alert_events schema present + audit INSERT on fire | unit | `pytest tests/test_phase12_alerts.py::test_evaluate_workspace_fires_on_threshold` | ✅ | ✅ green |
| 12-02-01 | 02 | 2 | ALERT-04 | — | 24h dedup: _should_fire returns False when row exists within 24h | unit | `pytest tests/test_phase12_alerts.py::test_should_fire_false tests/test_phase12_alerts.py::test_evaluate_workspace_dedup_skips` | ✅ | ✅ green |
| 12-02-02 | 02 | 2 | ALERT-06 | T-12-13 | Email dispatch via send_usage_warning_email; fail-open bool return | unit | `pytest tests/test_phase12_alerts.py::test_evaluate_workspace_fires_on_threshold` | ✅ | ✅ green |
| 12-02-03 | 02 | 2 | ALERT-07 | T-12-07, T-12-08 | SSRF: slack URL validated before any HTTP call; URL not logged | unit | `pytest tests/test_phase12_alerts.py::test_dispatch_slack_ssrf_guard_invalid_host tests/test_phase12_alerts.py::test_dispatch_slack_ssrf_guard_empty tests/test_phase12_alerts.py::test_dispatch_slack_success tests/test_phase12_alerts.py::test_dispatch_slack_http_error` | ✅ | ✅ green |
| 12-02-04 | 02 | 2 | ALERT-05 | T-12-10 | Fail-open: per-rule exception caught, evaluate_workspace returns [] | unit | `pytest tests/test_phase12_alerts.py::test_evaluate_workspace_fail_open` | ✅ | ✅ green |
| 12-03-01 | 03 | 3 | ALERT-03 | T-12-14 | Cron endpoint: 401 without/wrong secret, 200 with correct secret | unit | `pytest tests/test_phase12_alerts.py::test_cron_endpoint_401_no_header tests/test_phase12_alerts.py::test_cron_endpoint_401_wrong_secret tests/test_phase12_alerts.py::test_cron_endpoint_200_with_correct_secret` | ✅ | ✅ green |
| 12-03-02 | 03 | 3 | ALERT-07 | T-12-15, T-12-16 | PUT /settings/slack-webhook: owner-only, SSRF URL validation, clear/set | unit | `pytest tests/test_settings_api.py::TestSlackWebhookEndpoints` | ✅ | ✅ green |

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Default 80%+100% rules seeded for existing cloud/teams workspaces on deploy | ALERT-01 | Seeding runs in `init_db()` against a live Postgres DB at deploy time; requires real DB + non-free workspaces present | After next Railway deploy, run: `SELECT workspace_id, threshold_pct, channel FROM alert_rules ORDER BY workspace_id, threshold_pct;` — every cloud/teams workspace should have exactly two rows (80 + 100, channel='email') |
| Email received by org owner when 80%/100% crossed | ALERT-06 | Requires live SendGrid + real workspace + a populated billing cycle | Manually trigger cron endpoint with correct CRON_SECRET; verify email delivery in SendGrid activity log |
| Slack notification received when Slack webhook configured | ALERT-07 | Requires live Slack workspace + real webhook URL | Set webhook via PUT /settings/slack-webhook; trigger cron; verify Slack message arrives |

---

## Validation Audit 2026-05-05

| Metric | Count |
|--------|-------|
| Requirements audited | 7 (ALERT-01–07) |
| Gaps found | 2 (ALERT-01 no seeding test, ALERT-07 no endpoint test) |
| Resolved | 2 |
| Escalated to manual-only | 3 (seeding live-DB, email delivery, Slack delivery) |
| Total tests | 14 (test_phase12_alerts) + 4 (test_settings_api::TestSlackWebhookEndpoints) = 18 |
| All tests green | ✅ 28/28 passing (full test files) |

---

## Validation Sign-Off

- [x] All tasks have automated verify or manual-only entry
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 1s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-05-05
