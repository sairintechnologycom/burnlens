---
phase: 13
slug: alert-management-ui
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-05
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 + pytest-asyncio |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `pytest tests/test_phase13_alerts_api.py -x --tb=short` |
| **Full suite command** | `pytest tests/test_phase13_alerts_api.py tests/test_phase12_alerts.py -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_phase13_alerts_api.py -x --tb=short`
- **After every plan wave:** Run `pytest tests/test_phase13_alerts_api.py tests/test_phase12_alerts.py -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 13-01-01 | 01 | 1 | ALERT-08 | IDOR | GET scoped to workspace_id only | unit | `pytest tests/test_phase13_alerts_api.py::test_list_alert_rules_200 -x` | ❌ W0 | ⬜ pending |
| 13-01-02 | 01 | 1 | ALERT-08 | — | viewer role can read rules | unit | `pytest tests/test_phase13_alerts_api.py::test_list_rules_viewer_allowed -x` | ❌ W0 | ⬜ pending |
| 13-01-03 | 01 | 1 | ALERT-08 | IDOR | GET returns only own workspace rules | unit | `pytest tests/test_phase13_alerts_api.py::test_list_rules_scoped_to_workspace -x` | ❌ W0 | ⬜ pending |
| 13-01-04 | 01 | 1 | ALERT-09 | IDOR | PATCH rule from different workspace → 404 | unit | `pytest tests/test_phase13_alerts_api.py::test_patch_idor_protection -x` | ❌ W0 | ⬜ pending |
| 13-01-05 | 01 | 1 | ALERT-09 | — | PATCH enabled toggle succeeds | unit | `pytest tests/test_phase13_alerts_api.py::test_patch_toggle_enabled -x` | ❌ W0 | ⬜ pending |
| 13-01-06 | 01 | 1 | ALERT-09 | — | PATCH threshold_pct=50 → 422 | unit | `pytest tests/test_phase13_alerts_api.py::test_patch_invalid_threshold -x` | ❌ W0 | ⬜ pending |
| 13-01-07 | 01 | 1 | ALERT-09 | — | PATCH extra_emails replaces full array | unit | `pytest tests/test_phase13_alerts_api.py::test_patch_extra_emails -x` | ❌ W0 | ⬜ pending |
| 13-01-08 | 01 | 1 | ALERT-09 | — | viewer role cannot PATCH → 403 | unit | `pytest tests/test_phase13_alerts_api.py::test_patch_viewer_forbidden -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_phase13_alerts_api.py` — stubs for all ALERT-08 + ALERT-09 backend cases (Wave 0 creates with failing tests, Wave 1 makes them pass)
- [ ] Use `_make_alerts_app()` local factory pattern (same as `_make_cron_app()` in `tests/test_phase12_alerts.py`)

*Existing infrastructure: `pyproject.toml` pytest config, `tests/conftest.py` fixtures, pytest-asyncio already installed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| /alerts page renders rule list for owner | ALERT-08 | Frontend — no Playwright coverage in scope | Log in as cloud/teams user, navigate to /alerts, verify two rules (80%, 100%) are shown with enabled state |
| Toggle enabled/disabled updates immediately in UI | ALERT-09 | Frontend optimistic update | Click toggle on a rule, verify UI state flips; refresh page to confirm server persisted |
| Edit threshold dropdown only shows 80/100 | ALERT-09 | Frontend validation | Open edit mode, verify only 80% and 100% are selectable |
| Add/remove extra email recipient | ALERT-09 | Frontend chip management | Add an email, verify it appears; click X on it, verify it's removed; save, refresh to confirm |
| Alerts nav item appears in Sidebar Intelligence group | ALERT-08 | Frontend layout | Load any dashboard page, verify "Alerts" appears under Intelligence in left sidebar |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
