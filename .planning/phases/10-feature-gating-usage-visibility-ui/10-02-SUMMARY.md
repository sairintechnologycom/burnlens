---
phase: 10-feature-gating-usage-visibility-ui
plan: 02
subsystem: frontend-chrome
tags: [frontend, sidebar, meter, gating, css, billing-context, phase-10]
requires:
  - "Plan 10-01 backend additions (/billing/summary.usage / .available_plans / .api_keys)"
  - "frontend BillingContext (Phase 7 D-18 — refresh + polling skeleton)"
  - "frontend useAuth (session.plan)"
  - "frontend globals.css tokens: --cyan --amber --red --sev-h-bg --bg2 --border --border2 --muted --card-bg --text --font-sans --font-mono"
provides:
  - "frontend/src/lib/hooks/usePlanSatisfies.ts — PLAN_ORDER, planSatisfies(have, need), LOCKED_NAV map, nextPlanFor(current) helper"
  - "Extended BillingSummary TypeScript type (UsageCurrentCycle, AvailablePlan, ApiKeysSummary subobjects — all optional, additive)"
  - "BillingContext poll cadence bumped from 30_000ms to 60_000ms (D-17 override of Phase 7 D-18) — visibility-gating preserved"
  - "frontend/src/components/UsageMeter.tsx — sidebar-footer widget with threshold coloring + over-quota clamp + ARIA progressbar"
  - "Sidebar.tsx with SidebarItem.lockedForPlan + lock glyph render + planSatisfies-driven affordance"
  - "Complete Phase 10 CSS block appended to globals.css (file-ownership boundary — Plans 03 / 04 do NOT touch CSS)"
affects:
  - "frontend/src/app/globals.css (additive append at EOF)"
  - "frontend/src/components/Sidebar.tsx (extended)"
  - "frontend/src/components/UsageMeter.tsx (new)"
  - "frontend/src/lib/contexts/BillingContext.tsx (extended types + cadence bump)"
  - "frontend/src/lib/hooks/usePlanSatisfies.ts (new)"
tech-stack:
  added: []
  patterns:
    - "Single file-ownership boundary for Phase 10 CSS in globals.css (Plans 03/04 reference classes; never edit CSS) — prevents merge serialization."
    - "Helper-based gating: planSatisfies(have, need) is the single source of plan-rank truth (consumed by Sidebar; will be consumed by LockedPanel + ApiKeysCard in Plans 03/04)."
    - "BillingContext as single poll surface — UsageMeter consumes context rather than starting its own setInterval (T-10-10 mitigation)."
    - "Fail-closed plan resolution: currentPlan defaults to 'free' when billing+session both null, so locks render visible during loading."
key-files:
  created:
    - "frontend/src/components/UsageMeter.tsx (95 lines)"
    - "frontend/src/lib/hooks/usePlanSatisfies.ts (54 lines)"
  modified:
    - "frontend/src/lib/contexts/BillingContext.tsx (+34 lines: new types + comment-bumped cadence)"
    - "frontend/src/components/Sidebar.tsx (+78 lines: lockedForPlan support + lock glyph + UsageMeter mount)"
    - "frontend/src/app/globals.css (+157 lines: Phase 10 CSS block at EOF)"
decisions:
  - "Did NOT change BillingContext's REFRESH_ON_FOCUS_STALENESS_MS (10_000ms). Plan only required POLL_INTERVAL_MS to flip; the focus-staleness threshold is a separate refresh trigger and stays at 10s."
  - "currentPlan resolution is `(billing?.plan ?? session?.plan ?? 'free').toLowerCase()` — Topbar.tsx uses the same chain, keeping a single resolution pattern. Lowercase guard is defensive against any future backend casing drift."
  - "Used a small `LockGlyph` component inside Sidebar.tsx rather than inlining the SVG twice. Single SVG block keeps the JSX readable and the markup DRY; identical visual result to the plan's inline example."
  - "Empty-cycle detection branches off `current === 0 && (now - cycle.start) < 24h`. When true we skip rendering the fill `<div>` entirely (width 0 with no element) — slightly cleaner DOM than width:0% and matches the UI-SPEC empty-cycle state."
  - "`formatResetDate` defends against an unparseable cycle.end ISO string with a `'next cycle'` fallback. Cheap insurance against any future backend timezone bug."
metrics:
  duration: "~4 minutes"
  completed: "2026-04-25"
  tasks_completed: 2
  files_created: 2
  files_modified: 3
---

# Phase 10 Plan 02: Frontend Chrome Foundation Summary

Frontend now has every dashboard page rendering a sidebar usage meter with threshold coloring, plan-rank-driven lock affordances on `/teams` and `/customers`, and `BillingContext` typed end-to-end against the Plan 01 backend response (including the `api_keys` subobject for Plan 04). The complete Phase 10 CSS block is appended to `globals.css` so Plans 03 and 04 can reference classes without touching CSS — eliminating a merge serialization point.

## Final Import Paths (for Plans 03 / 04)

Plans 03 (LockedPanel) and 04 (ApiKeysCard) should use these imports:

```typescript
import {
  PLAN_ORDER,
  planSatisfies,
  LOCKED_NAV,
  nextPlanFor,
  type PlanName,
} from "@/lib/hooks/usePlanSatisfies";

import {
  useBilling,
  type BillingSummary,
  type UsageCurrentCycle,
  type AvailablePlan,
  type ApiKeysSummary,
} from "@/lib/contexts/BillingContext";
```

## Poll Cadence Confirmation (D-17)

**Confirmed:** `POLL_INTERVAL_MS` flipped from `30_000` to `60_000` in `frontend/src/lib/contexts/BillingContext.tsx:79`.

The 30_000 value is **gone** — not commented out, deleted (acceptance criterion verified by `grep -cnE "POLL_INTERVAL_MS\s*=\s*30_?000"` returning 0).

The cadence-change comment at the constant explicitly notes the Phase 7 → Phase 10 override:

```ts
// Phase 10 D-17: bumped from Phase 7 D-18's 30_000ms to 60_000ms.
// Rationale: the sidebar usage meter is the most prominent live counter and
// it just needs "freshish" — a 60s tick is plenty for a million-request-per-
// month cap and halves the polling load. The visibility-gating below
// (document.visibilityState === "visible") is unchanged.
```

`REFRESH_ON_FOCUS_STALENESS_MS` (10s) was deliberately NOT changed — separate refresh trigger, not in scope per plan.

## File Locations (definitive)

| Purpose | Path |
|---------|------|
| Plan-rank helper | `frontend/src/lib/hooks/usePlanSatisfies.ts` |
| Sidebar usage meter | `frontend/src/components/UsageMeter.tsx` |
| Extended sidebar | `frontend/src/components/Sidebar.tsx` |
| Extended billing types | `frontend/src/lib/contexts/BillingContext.tsx` |
| Phase 10 CSS block | `frontend/src/app/globals.css` (appended at EOF after the existing `@media (max-width:640px)` block) |

## CSS Tokens Audit

**Required tokens — all present in `:root.theme-dark` and `:root.theme-light`:**

| Token | Dark | Light | Verified |
|-------|------|-------|----------|
| `--cyan` | `#2dd4bf` | `#0d7a6e` | ✓ |
| `--amber` | `#f5a623` | `#b45309` | ✓ |
| `--red` | `#f04060` | `#c0392b` | ✓ |
| `--sev-h-bg` | `rgba(245,166,35,0.12)` | `#fffbeb` | ✓ |
| `--bg2` | `#181b24` | `#e8e4dc` | ✓ |
| `--border` | `#1d2130` | `#dedad0` | ✓ |
| `--border2` | `#262b3c` | `#ccc8bc` | ✓ |
| `--muted` | `#7b86a0` | `#6b6460` | ✓ |
| `--card-bg` | `#0e1018` | `#ffffff` | ✓ |
| `--text` | `#e4e7ef` | `#1a1a1f` | ✓ |
| `--font-sans` / `--font-mono` | (existing) | (existing) | ✓ |

**No new hex values were invented** (per UI-SPEC "Color: No new hex values" rule). No additional tokens needed.

## Threshold Coloring Verification

Logic in `UsageMeter.tsx`:

```ts
const pct = cap > 0 ? (current / cap) * 100 : 0;
const widthPct = Math.min(100, pct);          // D-14: bar width clamped
const band: "green" | "amber" | "red" =
  pct > 100 ? "red" : pct >= 80 ? "amber" : "green";
```

| Caller plan | cap | current | pct | band | bar width | numeric label |
|-------------|-----|---------|-----|------|-----------|---------------|
| Free        | 100K | 50K | 50% | green (cyan) | 50% | "50,000 / 100,000" |
| Free        | 100K | 85K | 85% | amber | 85% | "85,000 / 100,000" |
| Free        | 100K | 110K | 110% | red | **100% (clamped)** | "110,000 / 100,000 **(110%)**" |
| Cloud       | 1M | 12.4K | 1.24% | green | 1.24% | "12,400 / 1,000,000" |
| Teams       | 10M | 7.2M | 72% | green | 72% | "7,200,000 / 10,000,000" |
| Empty cycle | 1M | 0 | 0% | (no fill rendered) | 0 | "0 / 1,000,000" + "first cycle" subtitle |

**ARIA `aria-live="polite"`** is set when band is amber or red (so screen readers announce when usage crosses 80% or 100%).

## Lock Affordance Verification

`Sidebar.tsx` resolves `currentPlan` via `(billing?.plan ?? session?.plan ?? "free").toLowerCase()`, then renders the lock glyph + "Teams plan" subtitle when `planSatisfies(currentPlan, item.lockedForPlan)` is false.

| Caller plan | `/teams` icon | `/customers` icon | Both clickable? |
|-------------|---------------|-------------------|-----------------|
| free        | 🔒 + "Teams plan" | 🔒 + "Teams plan" | ✓ (D-10 — clicking lands on teaser) |
| cloud       | 🔒 + "Teams plan" | 🔒 + "Teams plan" | ✓ |
| teams       | (no icon) | (no icon) | ✓ |
| enterprise (unknown) | 🔒 + "Teams plan" | 🔒 + "Teams plan" | ✓ (PLAN_ORDER unknown → fail-closed) |

D-10 invariant preserved: locked items remain `<Link>` elements with no `preventDefault`, no `aria-disabled`. Backend `require_feature` middleware remains the authoritative gate (T-10-08 accept-documented).

## Threat Model Compliance

| Threat ID | Status | Evidence |
|-----------|--------|----------|
| T-10-07 (XSS via API-derived numerics) | mitigated | `grep -ciE "(innerHTML\|setInnerHTML)" UsageMeter.tsx` returns 0; every value rendered as React text child (auto-escaped). Same `grep` on Sidebar.tsx returns 0. |
| T-10-08 (client-side gate as sole entitlement) | accept (documented) | LOCKED_NAV map docstring + Sidebar comment both explicitly state "backend require_feature middleware is the authoritative gate; this is purely UI affordance." Phase 9 GATE-05 is the security boundary. |
| T-10-09 (cross-org meter leak) | transferred to Plan 01 | `/billing/summary` is workspace-scoped via `verify_token`; Plan 01 test `test_summary_api_keys_workspace_isolation` covers this. Frontend has no API path to request another workspace. |
| T-10-10 (DoS via tight poll loop) | mitigated | UsageMeter consumes BillingContext rather than starting a second poller; the existing visibility-gated poller (lines 121–127) is the only setInterval. Cadence bumped to 60s halves attack surface. |
| T-10-11 (missing CSS tokens → undefined colors) | mitigated | Pre-flight grep on `:root.theme-dark` confirmed every referenced token exists; no new hex values invented. |

## Verification Results

- `cd frontend && npx tsc --noEmit` → **exits 0, no errors** (clean).
- All Task 1 acceptance grep checks pass:
  - `PLAN_ORDER`, `planSatisfies`, `LOCKED_NAV`, `nextPlanFor` each found exactly once.
  - `UsageCurrentCycle` (×2), `available_plans` (×1), `ApiKeysSummary` (×2), `api_keys?:` (×1).
  - `POLL_INTERVAL_MS = 60_000` ×1; `POLL_INTERVAL_MS = 30_000` ×0.
  - All Phase 10 CSS classes present (`usage-meter-fill--green/amber/red`, `.locked-panel-overlay`, `.sidebar-item--locked`, `.api-keys-cap-banner`, `.api-key-modal-backdrop`, `prefers-reduced-motion`).
- All Task 2 acceptance grep checks pass:
  - UsageMeter: `role="progressbar"` (×2 — loading + main), `href="/settings#usage"` (×2), `usage-meter-fill--`, `toLocaleString` (×2), `"first cycle"` (×1), `"resets "` (×1), `Math.min(100,` (×1), `innerHTML` (×0).
  - Sidebar: `lockedForPlan` (7 lines), `lockedForPlan: "teams"` (×2 — teams + customers), `planSatisfies` (×2), `sidebar-item--locked` (×1), `<UsageMeter` (×1), `innerHTML` (×0).

## Commits

- `f993ec4` — feat(10-02): extend BillingContext types, add planSatisfies helper, add Phase 10 CSS
- `ee8351b` — feat(10-02): add UsageMeter component and extend Sidebar with lockedForPlan

## Deviations from Plan

None — plan executed as written.

A few small implementation choices worth surfacing (not deviations, just confirmations):

1. **`REFRESH_ON_FOCUS_STALENESS_MS` left at 10_000ms** — the plan only required `POLL_INTERVAL_MS` to flip, and the focus-staleness threshold is a separate refresh trigger.
2. **Lock glyph factored into a small `LockGlyph()` component** instead of inlined twice in JSX — identical render output, slightly cleaner code.
3. **Empty-cycle state skips fill `<div>` entirely** when `request_count === 0` and the cycle is < 24h old, instead of rendering a width-0 fill. Matches the UI-SPEC "no fill" empty state visually.
4. **`formatResetDate` falls back to `"next cycle"`** if `Date(cycle.end)` is unparseable. Defensive against any future timezone bug.

## Authentication Gates

None — this plan made no network calls (consumes BillingContext on existing /billing/summary endpoint already wired in Phase 7).

## Known Stubs

None. The meter, lock glyph, and sidebar mount are fully wired. The `/settings#usage` anchor target (where the meter click lands) is not yet implemented — that's Plan 04's responsibility, called out as expected behavior in this plan's `<verify>` block ("anchor will 404 until Plan 04 adds the card; that's expected").

## Awareness for Downstream Plans

- **Plan 10-03 (LockedPanel + teaser pages):**
  - Import `planSatisfies` from `@/lib/hooks/usePlanSatisfies`.
  - All `.locked-panel*` CSS classes exist in globals.css (do NOT add CSS — file-ownership boundary).
  - The teaser must catch backend 402s and render `<LockedPanel>` — backend middleware is the authoritative entitlement gate.
- **Plan 10-04 (Settings → Usage card + ApiKeysCard):**
  - Read `billing.usage.current_cycle` (typed as `UsageCurrentCycle | undefined`) for the Usage card summary line.
  - Read `billing.api_keys.active_count` and `billing.api_keys.limit` for the pre-emptive at-cap banner. `limit === null` means unlimited (don't disable Create).
  - Read `billing.available_plans` for upsell pricing on the cap banner.
  - Use `nextPlanFor(billing.plan)` as the fallback when a 402 doesn't carry `required_plan`.
  - All `.usage-card-*`, `.api-keys-*`, `.api-key-modal-*` CSS classes exist (do NOT add CSS).
  - The meter's `href="/settings#usage"` requires Plan 04 to add an `id="usage"` anchor on the Usage card so click-from-meter scrolls to it.
- **General:** BillingContext now polls every 60s (visibility-gated). Plans 03/04 should NOT add a second poller; consume `useBilling()`.

## Self-Check: PASSED

Files verified to exist:
- FOUND: `frontend/src/lib/hooks/usePlanSatisfies.ts`
- FOUND: `frontend/src/components/UsageMeter.tsx`
- FOUND: `frontend/src/components/Sidebar.tsx` (extended)
- FOUND: `frontend/src/lib/contexts/BillingContext.tsx` (extended)
- FOUND: `frontend/src/app/globals.css` (extended)

Commits verified to exist:
- FOUND: f993ec4 — feat(10-02): extend BillingContext types, add planSatisfies helper, add Phase 10 CSS
- FOUND: ee8351b — feat(10-02): add UsageMeter component and extend Sidebar with lockedForPlan
