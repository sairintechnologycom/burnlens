---
phase: 14-budget-aware-model-downgrade
plan: "01"
subsystem: routing
tags: [downgrade-map, routing-config, config, providers]
dependency_graph:
  requires: []
  provides:
    - burnlens.providers.downgrade.DOWNGRADE_MAP
    - burnlens.providers.downgrade.get_downgrade_model
    - burnlens.config.RoutingConfig
    - burnlens.config.BurnLensConfig.routing
  affects:
    - burnlens/config.py
    - burnlens/providers/downgrade.py
tech_stack:
  added: []
  patterns:
    - "@dataclass sub-config pattern (matches AlertsConfig, CloudConfig, etc.)"
    - "DOWNGRADE_MAP as module-level dict constant for O(1) lookup"
key_files:
  created:
    - burnlens/providers/downgrade.py
  modified:
    - burnlens/config.py
decisions:
  - "DOWNGRADE_MAP uses current model name strings matching the claude-sonnet-4-6 / claude-haiku-4-5-20251001 naming convention per project context"
  - "RoutingConfig field is named budget_downgrade (not enabled) to avoid confusion with feature-flag semantics"
  - "All YAML values cast explicitly with bool()/float() per threat mitigation T-14-01-01"
metrics:
  duration_seconds: 168
  completed_date: "2026-05-05"
  tasks_completed: 2
  files_created: 1
  files_modified: 1
---

# Phase 14 Plan 01: DOWNGRADE_MAP + RoutingConfig Summary

**One-liner:** 10-entry model downgrade map (gpt-4o -> gpt-4o-mini, claude-sonnet-4-6 -> claude-haiku-4-5-20251001, gemini-1.5-pro -> gemini-1.5-flash) plus YAML-configurable RoutingConfig dataclass wired into BurnLensConfig.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create downgrade.py with DOWNGRADE_MAP + get_downgrade_model() | 8bcace0 | burnlens/providers/downgrade.py (new) |
| 2 | Add RoutingConfig dataclass + routing field to config.py | e9be8ae | burnlens/config.py (modified) |

## Decisions Made

1. **DOWNGRADE_MAP model names:** Used current project model name conventions (claude-sonnet-4-6, claude-haiku-4-5-20251001) rather than the older claude-3-5-sonnet-20241022 naming from the plan summary. The plan's action block specified the current names; those take precedence over the summary.

2. **RoutingConfig field name `budget_downgrade`:** Named to clearly indicate this is the budget-triggered downgrade toggle, distinct from a generic `enabled` flag. Matches the plan specification exactly.

3. **Explicit type casts in load_config():** `bool()`, `float()` wraps every routing YAML value, mitigating T-14-01-01 (YAML type confusion — e.g., YAML `True` string vs boolean).

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. Both artifacts are complete, pure data structures (no I/O, no rendering). get_downgrade_model() will return None for any unmapped model at runtime, which is the correct behavior for the router that will use it in later plans.

## Threat Flags

None. The only new trust boundary (YAML config -> Python) was covered by T-14-01-01 and mitigated with explicit type casts in the routing_data parsing block. No new network endpoints, auth paths, or file access patterns introduced.

## Self-Check: PASSED

- burnlens/providers/downgrade.py: FOUND
- Commit 8bcace0: FOUND
- Commit e9be8ae: FOUND
- len(DOWNGRADE_MAP) == 10: PASS
- get_downgrade_model('gpt-4o') == 'gpt-4o-mini': PASS
- get_downgrade_model('gemini-1.5-flash') is None: PASS
- cfg.routing.downgrade_threshold_pct == 20.0: PASS
- cfg.routing.downgrade_threshold_usd == 5.00: PASS
- BurnLensConfig() instantiates without error: PASS
