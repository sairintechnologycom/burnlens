---
phase: 12-cloud-alert-engine
plan: "01"
subsystem: burnlens_cloud/database
tags: [schema, migration, alerts, postgresql]
dependency_graph:
  requires: []
  provides: [alert_rules, alert_events, default_alert_seeding]
  affects: [Plan 02 alert_engine.py, Plan 03 cron_api.py]
tech_stack:
  added: []
  patterns: [CREATE TABLE IF NOT EXISTS, CREATE INDEX IF NOT EXISTS, INSERT ... WHERE NOT EXISTS, CROSS JOIN VALUES]
key_files:
  created: []
  modified:
    - burnlens_cloud/database.py
decisions:
  - "Insertion point: immediately after auth_tokens block (line 877), before plan_limits UPDATE block — matches Phase 11 Plan 01 pattern exactly"
  - "threshold_pct constrained to CHECK (threshold_pct IN (80, 100)) matching T-12-02 threat mitigation"
  - "Seeding uses CROSS JOIN (VALUES (80), (100)) with NOT EXISTS guard — idempotent on every deploy restart"
metrics:
  duration: "~3 minutes"
  completed: "2026-05-02"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 1
---

# Phase 12 Plan 01: Alert Schema Migration Summary

Added `alert_rules` and `alert_events` tables plus a default-seeding migration to `burnlens_cloud/database.py` inside the existing `init_db()` function. Unblocks Plan 02 (alert engine) which reads rules and writes dedup records.

## What Was Done

**Task 1 — Add alert_rules and alert_events tables in init_db()**

Inserted 4 `await conn.execute(...)` blocks immediately after the Phase 11 `auth_tokens` block (after `ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at`), before the Phase 9 `plan_limits UPDATE` block.

- `alert_rules` table: 9 columns — id UUID PK, workspace_id UUID FK (CASCADE), threshold_pct INT CHECK(80,100), channel TEXT CHECK(email/slack/both) DEFAULT 'email', enabled BOOLEAN DEFAULT TRUE, slack_webhook_url TEXT NULL, extra_emails TEXT[] DEFAULT '{}', created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ
- `idx_alert_rules_workspace` partial index on `alert_rules(workspace_id) WHERE enabled = TRUE`
- `alert_events` table: 8 columns — id UUID PK, rule_id UUID FK→alert_rules (CASCADE), workspace_id UUID FK→workspaces (CASCADE), threshold_pct INT, channel TEXT, recipient TEXT, fired_at TIMESTAMPTZ DEFAULT NOW(), status TEXT CHECK(sent/failed) DEFAULT 'sent'
- `idx_alert_events_rule_fired` composite index on `alert_events(rule_id, fired_at DESC)`

**Task 2 — Seed default alert rules**

Added seeding migration immediately after `idx_alert_events_rule_fired`. Uses `INSERT INTO alert_rules ... SELECT ... CROSS JOIN (VALUES (80), (100)) ... WHERE NOT EXISTS` — inserts exactly two rows (80%, 100% email) per cloud/teams workspace that has no rules yet. Idempotent on every deploy restart.

## Files Modified

- `burnlens_cloud/database.py` — 52 lines inserted (lines 879-929 in post-edit numbering)

## Verification Results

```
grep -c "CREATE TABLE IF NOT EXISTS alert_rules"   → 1  PASS
grep -c "CREATE TABLE IF NOT EXISTS alert_events"  → 1  PASS
grep -c "idx_alert_rules_workspace"                → 1  PASS
grep -c "idx_alert_events_rule_fired"              → 1  PASS
grep -c "CROSS JOIN (VALUES (80), (100))"          → 1  PASS
python -c "import ast; ast.parse(...); print('OK") → OK PASS
```

All 6 checks passed.

## Commit

`23172b2` — `feat(phase-12): add alert_rules + alert_events schema and default seeding (Plan 01)`

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- `burnlens_cloud/database.py` modified and verified to contain all required DDL
- Commit `23172b2` exists in git log
- Python AST parse: OK
- No unexpected file deletions
