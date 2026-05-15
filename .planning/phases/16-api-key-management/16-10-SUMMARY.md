---
phase: 16-api-key-management
plan: 10
subsystem: governance
tags: [roadmap, verification, override, viewer-role, api-keys]

requires:
  - phase: 16-09
    provides: "Re-verification report flagging SC-5 ↔ D-04 contract divergence as deferred"
provides:
  - "Resolved the SC-5 ↔ D-04 contradiction by reconciling ROADMAP wording with D-04 (path-b)"
  - "Single source of truth for APIKEY-05 — server-side viewer-creator scoping is now the documented contract"
  - "Override recorded in 16-VERIFICATION.md so the next milestone planner does not inherit the ambiguity"
affects: [milestone-planning, governance, viewer-role-policy]

tech-stack:
  added: []
  patterns:
    - "Override-recorded resolution for ROADMAP/Decision divergence (no production code change)"

key-files:
  created:
    - .planning/phases/16-api-key-management/16-10-SUMMARY.md
  modified:
    - .planning/ROADMAP.md
    - .planning/phases/16-api-key-management/16-VERIFICATION.md

key-decisions:
  - "path-b selected by human: ROADMAP SC-5 wording moves to match D-04; implementation unchanged"
  - "Server-side viewer-creator scoping (_viewer_creator_filter) is security-equivalent to a UI gate; UI need not be tightened"
  - "Override recorded in 16-VERIFICATION.md with rationale, accepting the ROADMAP rewording as the resolution"

patterns-established:
  - "Doc-only resolution: when a ROADMAP success criterion contradicts a later locked decision (D-XX), the older artefact moves and the override is recorded in the phase verification report"

requirements-completed:
  - APIKEY-05

duration: 5min
completed: 2026-05-15
---

# Phase 16 Plan 10: SC-5 ↔ D-04 Contract Reconciliation — Summary

**Resolved the only remaining gap from 16-VERIFICATION.md by updating ROADMAP SC-5 to match D-04 (path-b) — no production code touched.**

## Path Selected

**path-b — Update ROADMAP wording to match D-04 (RECOMMENDED)**

Selected by human via checkpoint:decision in Task 1. Rationale:
- Server-side enforcement (`_viewer_creator_filter` on GET/PATCH/DELETE) is security-equivalent to a UI gate.
- D-04 is the more recent locked decision and matches what shipped.
- Re-tightening working UI code would be rework, not value.
- Verifier had already suggested this resolution.

## Accomplishments

- ROADMAP Phase 16 Success Criterion #5 reworded to match D-04 (viewers may self-create and self-revoke their own keys; cross-creator access returns 404 indistinguishability).
- `16-VERIFICATION.md` frontmatter incremented `overrides_applied` (1 → 2) and a new `overrides:` entry was recorded with rule, rationale, and date.
- `gaps:` SC-5 entry status changed from `deferred` to `resolved_via_override` with a `resolution:` field pointing back to this plan.
- Zero production code modified: `git diff --name-only frontend/ burnlens/ burnlens_cloud/ tests/` is empty.

## Task Commits

1. **Task 1: checkpoint:decision** — no commit (decision-only)
2. **Task 2: update ROADMAP + record override** — single commit covering both files

Task 3 (UI role-gates + Playwright spec for path-a) was **intentionally skipped** per plan instructions ("Exactly one path is taken — never both").

## Files Created/Modified

- `.planning/ROADMAP.md` — SC-5 wording for Phase 16 updated to reference D-04 (1 line).
- `.planning/phases/16-api-key-management/16-VERIFICATION.md` — `overrides_applied` bumped, new override block appended, SC-5 gap status moved to `resolved_via_override`.
- `.planning/phases/16-api-key-management/16-10-SUMMARY.md` — this file.

## Acceptance Criteria — all passed

| AC | Check | Result |
|----|-------|--------|
| 1 | Old SC-5 wording gone from ROADMAP | `grep -c "cannot access the create or revoke actions"` = 0 ✓ |
| 2 | New SC-5 wording references D-04 | `grep -c "per D-04"` ≥ 1 ✓ |
| 3 | `overrides_applied` incremented | Now `2` (was `1` from deferral override; intent met) ✓ |
| 4 | `resolved_via_override` recorded | `grep -c "resolved_via_override"` ≥ 1 ✓ |
| 5 | Changes confined to two files | `git diff --stat` shows only ROADMAP.md and 16-VERIFICATION.md ✓ |
| 6 | Zero source code changes | `git diff --name-only frontend/ burnlens/ burnlens_cloud/ tests/` empty ✓ |

## Self-Check: PASSED

Plan goal — eliminate the documented contract/code disagreement on APIKEY-05 — is achieved. ROADMAP, decision log, and implementation are now mutually consistent. The next milestone planner inherits a single source of truth.
