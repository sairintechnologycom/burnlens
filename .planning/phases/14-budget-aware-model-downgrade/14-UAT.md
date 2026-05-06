---
status: complete
phase: 14-budget-aware-model-downgrade
source: [14-01-SUMMARY.md, 14-02-SUMMARY.md, 14-03-SUMMARY.md, 14-04-SUMMARY.md, 14-05-SUMMARY.md, 14-06-SUMMARY.md, 14-07-SUMMARY.md]
started: 2026-05-06T02:13:36Z
updated: 2026-05-06T02:25:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Cold Start Smoke Test
expected: Kill any running burnlens server. Start fresh with `burnlens start`. The server boots without errors and responds to a health or basic request (e.g. open http://localhost:8420/ui or hit the dashboard). No crash, no migration errors, no missing column errors.
result: pass

### 2. Routing Config Loads from YAML
expected: Add a routing section to burnlens.yaml (e.g. `routing: {budget_downgrade: true, downgrade_threshold_pct: 80, downgrade_threshold_usd: 5.0}`) and start burnlens. No config parse error. Config loads cleanly and the proxy starts normally.
result: pass

### 3. Auto-Downgrade Activates at Budget Threshold
expected: With budget_downgrade enabled and a threshold set lower than current spend, make a proxied LLM request using a model that has a downgrade alternative (e.g. gpt-4o → gpt-4o-mini). The request completes successfully, but the actual upstream model used is the cheaper one. Check `burnlens routing` to confirm a downgrade event was recorded.
result: skipped

### 4. Pass-Through When Budget Is Healthy
expected: With budget_downgrade enabled but budget well above threshold, make a proxied LLM request. The original requested model is used (no substitution). `burnlens routing` shows no new downgrade event.
result: pass

### 5. Dashboard: Downgrades Today KPI Card
expected: Open http://localhost:8420/ui. A "Downgrades Today" stat card is visible on the dashboard (alongside the existing Cost Today / Requests Today cards). It shows a count of downgrade events for today (0 if none have happened yet).
result: pass

### 6. Dashboard: Routed Column in Recent Requests
expected: The Recent Requests table on the dashboard has a "Routed" column. For normal requests it shows a dash (-). For any downgraded request, it shows the original→routed model badge (e.g. "gpt-4o → gpt-4o-mini").
result: pass

### 7. CLI: burnlens routing Command
expected: Run `burnlens routing` in the terminal. It displays a Rich table with columns: Timestamp, Original Model, Routed Model, Reason, Budget Left. If no downgrade events exist, a yellow warning message appears. If events exist, they are listed.
result: pass

### 8. CLI: burnlens routing --today Filter
expected: Run `burnlens routing --today`. Only downgrade events from today are shown. If there are events from previous days in the DB, they are excluded from this view.
result: pass

### 9. CLI: burnlens routing --json Output
expected: Run `burnlens routing --json`. The output is a raw JSON array. Each element represents a downgrade event. The output is valid JSON (parseable with `python -m json.tool`).
result: pass

## Summary

total: 9
passed: 8
issues: 0
pending: 0
skipped: 1
blocked: 0

## Gaps

[none yet]
