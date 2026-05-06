---
phase: 13-alert-management-ui
plan: "02"
subsystem: frontend
tags: [nextjs, react, alerts-ui, optimistic-ui, role-based-access]

# Dependency graph
requires:
  - phase: 13-alert-management-ui
    plan: "01"
    provides: GET /api/v1/alert-rules, PATCH /api/v1/alert-rules/{id} cloud endpoints
provides:
  - Cloud alert-rules management UI at /alerts (owner: toggle + edit; viewer: read-only)
  - Alerts nav item in Sidebar Intelligence group after Budgets
affects:
  - frontend/src/app/alerts/page.tsx (full replacement of v1.0 proxy-alert page)
  - frontend/src/components/Sidebar.tsx (one new nav item)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Optimistic UI toggle with revert on error — same pattern as useCallback/fetchRules in budgets/page.tsx"
    - "Role gate via session.isLocal: non-local (remote cloud) users treated as owners until role field added to AuthSession"
    - "Email chip input: Enter-key guard with e.preventDefault(), format validation, dedup before adding"
    - "Escape key modal close: useEffect with keydown listener scoped to editingRule dep"
    - "Modal overlay click-to-close + programmatic close on save/cancel"

key-files:
  created: []
  modified:
    - frontend/src/app/alerts/page.tsx
    - frontend/src/components/Sidebar.tsx

key-decisions:
  - "session.isLocal used as owner proxy — AuthSession has no role field; non-local (remote cloud) users treated as owners; viewer simulation requires logging in as a non-owner account"
  - "handleAddEmail uses { key, preventDefault } structural type instead of React.KeyboardEvent to avoid React namespace import (jsx:react-jsx project setting)"
  - "Explicit AlertRule type annotations on all setState callbacks to satisfy strict mode without React namespace"

# Metrics
duration: ~20 min
completed: 2026-05-06
---

# Phase 13 Plan 02: Alert Management UI — Frontend Summary

**Full replacement of alerts/page.tsx with cloud alert-rules management UI; Alerts nav item added to Sidebar Intelligence group after Budgets**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-05-06
- **Tasks:** 2 of 2
- **Files modified:** 2

## Accomplishments

- Replaced `frontend/src/app/alerts/page.tsx` entirely — no v1.0 fields (name, metric, threshold, webhook_url, /api/v1/alerts) remain
- New `AlertRule` interface uses cloud schema: `threshold_pct`, `channel`, `enabled`, `has_slack`, `extra_emails`
- Stat strip shows Total Rules and Enabled count
- Table columns: Threshold (amber/muted badge pills), Channel (provider-badge), Slack (webhook-set pill or dash), Recipients (count), Enabled (toggle or dot), Actions (owner only)
- Owner role: optimistic toggle with revert on API error; edit modal for threshold_pct (80/100 select) and extra_emails (chip input)
- Viewer role: static 8×8px dot instead of toggle; Actions th/td not rendered
- Edit modal: Escape key + overlay click close, email chip validation (format + dedup), Slack webhook link to Settings
- Added `{ href: "/alerts", label: "Alerts" }` to Sidebar Intelligence group immediately after Budgets (line 52 vs line 51)

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Replace alerts/page.tsx with cloud alert-rules UI | 277becc | frontend/src/app/alerts/page.tsx |
| 2 | Add Alerts to Sidebar Intelligence group | 4acec25 | frontend/src/components/Sidebar.tsx |

## Decisions Made

- Used `session.isLocal === false` as "owner" proxy since `AuthSession` has no `role` field — remote cloud users are owners; local proxy users see viewer UI. Backend enforces 403 independently.
- Used structural type `{ key: string; preventDefault: () => void }` for `handleAddEmail` param to avoid `React.KeyboardEvent` which requires the React namespace import (not available with `jsx: react-jsx`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] TypeScript implicit `any` in setState callbacks under strict mode**
- **Found during:** Task 1 TypeScript check
- **Issue:** `setRules((rs) => ...)` and `rules.filter((r) => ...)` lambdas had implicit `any` under `strict: true`
- **Fix:** Added explicit `AlertRule[]` and `AlertRule` type annotations to all relevant callbacks
- **Files modified:** frontend/src/app/alerts/page.tsx
- **Commit:** 277becc (included in task commit)

**2. [Rule 2 - Missing] `React.KeyboardEvent` unavailable — structural type used instead**
- **Found during:** Task 1 TypeScript check
- **Issue:** Plan specified `React.KeyboardEvent<HTMLInputElement>` but React namespace not available in `jsx: react-jsx` projects without explicit `import React from "react"`
- **Fix:** Used structural type `{ key: string; preventDefault: () => void }` for `handleAddEmail`
- **Files modified:** frontend/src/app/alerts/page.tsx
- **Commit:** 277becc (included in task commit)

## Threat Surface Scan

Plan's threat model was fully implemented:
- T-13-02-02: Optimistic revert + AuthError logout on PATCH failure ✓
- T-13-02-03: Client-side "@" + "." validation before chip added ✓
- T-13-02-04: `e.preventDefault()` on Enter in onKeyDown handler ✓
- T-13-02-05: `isOwner` gate on toggle button and Actions column ✓

No new threat surface introduced beyond the plan's trust boundaries.

## Known Stubs

None — all data flows from the real API (`/api/v1/alert-rules`). No hardcoded empty values or placeholder text.

## Self-Check

- [x] `frontend/src/app/alerts/page.tsx` exists
- [x] `frontend/src/components/Sidebar.tsx` exists with Alerts entry
- [x] Commit `277becc` exists (Task 1)
- [x] Commit `4acec25` exists (Task 2)
- [x] Old v1.0 endpoint `/api/v1/alerts` absent from new page (grep returns 0)
- [x] TypeScript errors in alerts/page.tsx: 0 (environment-level react/jsx type errors exist in all existing files; no code-level errors in this file)

## Self-Check: PASSED
