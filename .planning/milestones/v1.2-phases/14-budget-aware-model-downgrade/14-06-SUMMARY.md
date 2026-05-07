---
plan: 14-06
status: complete
tasks_completed: 2
commits:
  - b374f84
  - 15c2426
---

## What Was Built

`burnlens routing` CLI command for viewing model downgrade events. Queries
the requests table for rows where `downgrade_reason IS NOT NULL`, displays
them in a Rich table with Timestamp, Original Model, Routed Model, Reason,
and Budget Left columns. Supports `--today` filter and `--json` output.

## Key Files Changed

- `burnlens/storage/database.py` — `get_routing_events()` async function:
  queries WHERE downgrade_reason IS NOT NULL, supports today_only filter
  via parameterized DATE(timestamp) = ?, returns list[dict], limit 200
- `burnlens/cli.py` — `routing()` Typer command: Rich table display,
  Budget Left as "18.3% / $9.20" format (or "-" when NULL), yellow
  warning when no events found, --json outputs raw JSON array

## Must-Have Verification

- [x] `burnlens routing` command exists in cli.py — `def routing` at line 1520
- [x] Table columns: Timestamp, Original Model, Routed Model, Reason, Budget Left
- [x] `--today` flag filters to today's downgrade rows only
- [x] `--json` flag outputs a raw JSON array
- [x] Query selects WHERE downgrade_reason IS NOT NULL ORDER BY timestamp DESC LIMIT 200
- [x] Budget Left shows "18.3% / $9.20" format when both budget fields present
- [x] Budget Left shows "-" when budget_remaining_usd/pct are NULL
- [x] No downgrade events → yellow warning message via typer.secho

## Self-Check: PASSED
