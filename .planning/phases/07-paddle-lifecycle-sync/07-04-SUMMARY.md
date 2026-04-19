---
phase: 07-paddle-lifecycle-sync
plan: 04
subsystem: frontend.billing-surfaces
status: complete
tags: [react, nextjs, ui, settings, paddle]
requirements:
  - PDL-04
  - BILL-01
  - BILL-02
dependency_graph:
  requires:
    - frontend/src/lib/contexts/BillingContext.tsx::useBilling — consumed by all three surfaces (Plan 07-03)
    - frontend/src/lib/contexts/BillingContext.tsx::BillingSummary — TypeScript contract (Plan 07-03)
    - burnlens_cloud/billing.py::billing_summary — GET /billing/summary (Plan 07-02)
  provides:
    - frontend/src/components/BillingStatusBanner.tsx — amber past_due banner mounted in Shell
    - frontend/src/app/settings/page.tsx::BillingCardBody — Settings → Billing card (loading/error/ready variants)
    - frontend/src/app/settings/page.tsx::statusDisplay — W2 canceled/paused resilience helper
    - Post-checkout refresh handoff for Phase 8 (?checkout=success listener in Settings mount effect)
  affects:
    - Phase 8 (checkout + self-serve billing) — will flip `Manage billing` / `Upgrade to Cloud` from disabled stubs to live CTAs; will navigate to /settings?checkout=success to trigger immediate billing refresh.
    - Every authenticated route — Shell.tsx banner mount covers /dashboard, /models, /teams, /customers, /waste, /settings in one pass (I2).
tech_stack:
  added: []
  patterns:
    - Inline token-only styling (var(--amber), var(--cyan), var(--bg2), var(--bg3), var(--border), var(--text), var(--muted))
    - color-mix(in srgb, var(--amber) 12%, var(--bg2)) for amber-tinted banner surface
    - window.location.search + history.replaceState for ?checkout=success handoff (no next/navigation required)
    - Explicit canceled/paused early return in statusDisplay() (W2 webhook-race resilience)
    - Marker-comment-delimited region ({/* Billing — Phase 7 */} ... {/* /Billing — Phase 7 */}) for greppable hex-literal invariant (W3)
    - BillingSummary imported via inline `import(...)` type-only expression to avoid adding a named import to the page
key_files:
  created:
    - frontend/src/components/BillingStatusBanner.tsx  # 48 lines, new
  modified:
    - frontend/src/components/Shell.tsx  # +2 / -0 (import + JSX sibling)
    - frontend/src/components/Topbar.tsx  # +3 / -2 (useBilling import + fallback chain)
    - frontend/src/app/settings/page.tsx  # +246 / -15 (imports + listener + Billing card + BillingCardBody + helpers + Tier removal + grid collapse)
decisions:
  - "BillingStatusBanner renders as a direct sibling after <Topbar /> and before <div className='shell-main'> — I2 covers all authenticated routes with a single mount."
  - "Topbar plan pill fallback order: billing?.plan ?? session?.plan ?? 'free' — context wins when populated, localStorage-derived session.plan serves only as first-render hint (D-19)."
  - "?checkout=success listener lives in SettingsContent mount effect (Claude-discretion §5, CONTEXT.md) — keeps the concern local to the page that reads the param, synchronous strip via history.replaceState beats useSearchParams (no server-render stale value)."
  - "Poll interval inherited from BillingContext = 30s; focus-staleness threshold = 10s. Comfortably clears the 60s PDL-04 SLA."
  - "statusDisplay() has an EXPLICIT branch for `canceled` OR `paused` returning the Active appearance. This is the W2 webhook-race window — the backend has flipped plan='free' via _handle_subscription_canceled but subscription_status still carries 'canceled' or 'paused' for a short window. Rendering as Active preserves D-22/D-23 intent (the post-cancellation steady state IS free+active)."
  - "W3 region-scoped hex-literal invariant: the Billing card is bracketed by marker comments and the region contains zero hex literals. Verified via awk/python region extract + regex count = 0."
  - "Error surface strategy for dedup races: a single best-effort refresh() call + a lightweight text-button 'Retry' in the error state. No toasts on plan-state change (UI-SPEC hard rule)."
  - "BillingCardBody receives billing/loading/error/onRetry as props rather than reading useBilling() directly — makes the subcomponent trivially unit-testable without a provider, and keeps the hook call co-located with SettingsContent where the ?checkout=success listener already lives."
  - "Date formatting uses toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' }) — locked by UI-SPEC §Copywriting Contract (Month D, YYYY)."
  - "Price formatting: USD integers render as '$29/mo'/'$99/mo' (Number.isInteger fast path); non-integer USD renders with .toFixed(2); non-USD uses Intl.NumberFormat with the payload currency; null renders '$0'. isFree path short-circuits to '$0' regardless of price_cents."
  - "Disabled CTAs carry `disabled` + `aria-disabled='true'` + `title` for tooltip. Paid: 'Manage billing →' with self-serve tooltip; Free: 'Upgrade to Cloud' with checkout tooltip. Both stubs wait on Phase 8."
  - "Organization card grid collapsed from '1fr 1fr' to '1fr' after the Tier block removal — Org name now spans the row alone. Settings-card padding stays at 18px (off-grid but unchanged in this phase; Phase 10 reconciles)."
metrics:
  duration: ~15 minutes
  completed_date: 2026-04-19
  tasks_completed: 3
  commits: 3
  lines_added: ~296
  lines_removed: ~17
  tests_added: 0
  tests_passing: 0
---

# Phase 7 Plan 04: Paddle Lifecycle UI Surfaces Summary

Lands the three user-visible surfaces that consume Plan 03's `BillingContext`: the Topbar plan pill (data-source swap), the Settings → Billing summary card (fresh card + legacy Tier removal + `?checkout=success` handoff), and the new `past_due` amber banner mounted once in `Shell.tsx`. No backend changes. No new dependencies. Token-only styling with a region-scoped hex-literal invariant (W3).

## What Was Built

### Task 1 — `BillingStatusBanner.tsx` (commit `313c56b`)

New client component at `frontend/src/components/BillingStatusBanner.tsx` (48 lines). Returns `null` unless `billing?.status === "past_due"`. When visible, it renders a single 40px horizontal bar:

- **Surface:** `color-mix(in srgb, var(--amber) 12%, var(--bg2))` background, `3px solid var(--amber)` left border, `1px solid var(--border)` bottom border.
- **Content:** `AlertTriangle` from `lucide-react` (14px, `var(--amber)`, `aria-hidden="true"`) + a single `<p>` containing `Payment failed — update billing` where `update billing` is a `<Link href="/settings#billing">` inline, `var(--amber)` + `fontWeight: 600` + `textDecoration: none`.
- **a11y:** `role="status"` + `aria-live="polite"` on the outer container so screen readers announce the banner when it appears.

Zero new CSS. Zero hex literals. No dependency additions (`lucide-react` was already in `package.json`).

### Task 2 — Shell banner mount + Topbar pill rewire (commit `2e5ac85`)

**`Shell.tsx`:** imported `BillingStatusBanner` and mounted it as a direct sibling after `<Topbar />` and before `<div className="shell-main">`. Because `Shell` wraps every authenticated route (dashboard, models, teams, customers, alerts, settings), the single mount delivers the banner everywhere with no per-route work (I2).

**`Topbar.tsx`:** added `import { useBilling } from "@/lib/contexts/BillingContext"` and swapped the plan-key derivation to:

```tsx
const { session } = useAuth();
const { billing } = useBilling();
const planKey = (billing?.plan ?? session?.plan ?? "free").toLowerCase();
```

`session.plan` (populated from `localStorage` by `useAuth`) remains as the first-render hint so the pill never flashes empty while `/billing/summary` is in flight (D-19). Everything below that — `PLAN_LABELS` lookup, `isFree`, the `<Link>` to `/settings#billing` with `plan-pill` / `plan-pill-free` / `plan-pill-paid` / `plan-pill-upgrade` classes — stayed verbatim.

### Task 3 — Settings Billing card + listener + Tier removal (commit `793a89f`)

Five edits to `frontend/src/app/settings/page.tsx`:

1. **Imports:** `useBilling` from `@/lib/contexts/BillingContext`.
2. **Hook usage in `SettingsContent`:** destructured `{ billing, loading: billingLoading, error: billingError, refresh: refreshBilling }`.
3. **`?checkout=success` listener:** a new `useEffect(..., [refreshBilling])` reads `window.location.search`, calls `refreshBilling()`, then strips the `checkout` param via `history.replaceState`. Server-render guard is `typeof window === "undefined"` early-return; synchronous strip beats `useSearchParams()` which can return stale values on first client render.
4. **Billing card rendered at the top** (before Organization), delimited by `{/* Billing — Phase 7 */}` and `{/* /Billing — Phase 7 */}` marker comments for the W3 region-scoped grep.
5. **Legacy Tier removal:** the hardcoded `Free` Tier block (previously at lines 81–93) is deleted; the Organization card's inner grid collapses from `"1fr 1fr"` to `"1fr"` so `Org name` spans the row alone.

The card body is a dedicated subcomponent (`BillingCardBody`) with three state variants and two helper functions (`formatPrice`, `formatDate`) plus `statusDisplay()` — all defined above `export default function SettingsPage`.

## Billing Card Shape (three variants)

**Loading (first load, while `loading && !billing`):**
- Row 1: two `.skeleton` blocks — plan/price placeholder (140×14, `borderRadius: 3`) on the left + status-pill placeholder (72×24, `borderRadius: 999`) on the right.
- Row 2: one `.skeleton` line (160×13, `borderRadius: 3`).
- Row 3: disabled `.btn` reading `Manage billing →` with the Phase-8 tooltip.

**Error (when `error || !billing`):**
- Row 1: `Billing info unavailable` in `var(--muted)` at 12px.
- Row 2: inline text-button `Retry` in `var(--cyan)` with underline, calling `onRetry` (which is `refreshBilling`).
- Row 3: disabled `.btn` still rendered so the card shape is stable across states.

**Ready (filled `billing`):**
- Row 1: `<plan-label> · <price>` on the left + status pill on the right. Plan label is `planKey.charAt(0).toUpperCase() + planKey.slice(1)` → `Free`/`Cloud`/`Teams`. Status pill is 24px tall with `var(--bg3)` background, `1px solid var(--border)`, `999px` border radius, dot color from `statusDisplay()`, `aria-label="Subscription status: <label>"`.
- Row 2: hidden for Free. Paid renders `Next billing: {Month D, YYYY}` in `var(--muted)`. Trialing renders `Trial ends: {Month D, YYYY}` in `var(--amber)`. `isTrialing = status === "trialing" && !!trial_ends_at` so missing dates don't accidentally render a broken row.
- Row 3: disabled CTA. Paid users → `Manage billing →` with self-serve tooltip; Free users → `Upgrade to Cloud` with checkout tooltip.

Free-state short-circuit: `isFree ? "$0" : formatPrice(billing.price_cents, billing.currency)` in Row 1 guarantees the `$0` literal for free workspaces regardless of what the backend returns for `price_cents`, matching UI-SPEC §Copywriting Contract.

## Resolved Claude's-discretion Items

| Item | Choice | Rationale |
|------|--------|-----------|
| Poll interval | 30 s (inherited from `BillingContext` Plan 03) | Lower end of the D-18 30–45 s range; comfortably under 60 s SLA. |
| Banner mount point | `Shell.tsx`, below `<Topbar />` | Single place covers every authed route via I2; Topbar is structural chrome and should not assume layout responsibility for conditional banners. |
| `?checkout=success` listener location | `SettingsContent` mount effect | Phase 8 always navigates to `/settings?checkout=success`; co-locating the listener with the page that renders the Billing card keeps the concern local and removes any global-auth-boundary coupling. |
| Error-surface strategy for dedup races | Single best-effort `refreshBilling()` + text-button `Retry` | Matches UI-SPEC §State Matrix; no toasts on plan-state change per UI-SPEC hard rule. |

## W2 — canceled/paused statusDisplay Branch

`statusDisplay(status: string)` has an explicit branch for `status === "canceled" || status === "paused"` that returns `{ label: "Active", dot: "var(--cyan)", labelColor: "var(--text)" }`. This covers the webhook-race window where `_handle_subscription_canceled` has already downgraded `plan='free'` but `subscription_status` still carries the cancellation value for a short time — the card renders cleanly as Active, preserving D-22/D-23 intent (the Plan-free state IS the post-cancellation steady state in our data model). Without this branch, the fall-through would still produce Active visually, but the W2 invariant wants the branch to be EXPLICIT and greppable so future state additions don't accidentally invert the behaviour.

## W3 — Billing Card Region Is Hex-Free (verifiable)

The Billing card region is delimited by a pair of marker comments:

```
{/* Billing — Phase 7 */}
  <div id="billing" className="card" ...> ... </div>
{/* /Billing — Phase 7 */}
```

Verified with region-scoped grep: `awk '/\{\/\* Billing — Phase 7 \*\/\}/,/\{\/\* \/Billing — Phase 7 \*\/\}/'` returns **0** `#[0-9a-fA-F]{3,8}` matches inside. All colours flow through CSS tokens (`var(--text)`, `var(--muted)`, `var(--bg3)`, `var(--border)`, `var(--amber)`, `var(--cyan)`). Every future edit to the region MUST preserve this invariant.

## UI-SPEC Dimensions Passed Without Reconciliation

- **Copywriting** — every locked string from UI-SPEC §Copywriting Contract appears verbatim: `Payment failed`, `update billing`, `Manage billing →`, `Upgrade to Cloud`, `Billing info unavailable`, `Retry`, `Next billing:`, `Trial ends:`, Phase-8 tooltips.
- **Visuals** — banner 40px / `padding: 0 24px` / `3px solid var(--amber)` left border; status pill 24px fixed height / `padding: 0 8px` / `border-radius: 999px`; Billing card `padding: 16`.
- **Color** — 60/30/10 system preserved. Accent `var(--cyan)` for active/trialing dots; warning `var(--amber)` for past_due and trial-ends copy; no `var(--red)` used (Phase 8 reserved).
- **Typography** — only `400` and `600` weights. 9px section header, 10px pill, 12px body/button/banner, 13px plan+price row.
- **Spacing** — multiples of 4 throughout (4/8/16/24). No off-grid values added.
- **Registry Safety** — zero new npm packages. `lucide-react` was already a dep.

Zero UI-SPEC dimensions required reconciliation during build — the spec dropped in cleanly.

## Verification Snapshot

| State | Card Row 1 | Card Row 2 | Card Row 3 | Banner | Topbar pill |
|-------|------------|------------|------------|--------|-------------|
| Free / active | `Free · $0` + ● Active | hidden | `Upgrade to Cloud` disabled | hidden | `Free · Upgrade` |
| Cloud / active | `Cloud · $29/mo` + ● Active | `Next billing: May 19, 2026` (muted) | `Manage billing →` disabled | hidden | `Cloud` |
| Cloud / trialing | `Cloud · $29/mo` + ● Trialing (amber dot) | `Trial ends: May 26, 2026` (amber) | `Manage billing →` disabled | hidden | `Cloud` |
| Cloud / past_due | `Cloud · $29/mo` + ● Past due (amber dot) | `Next billing: May 19, 2026` | `Manage billing →` disabled | **visible amber** | `Cloud` |
| Canceled race (plan='free', status='canceled') | `Free · $0` + ● Active (W2 explicit) | hidden | `Upgrade to Cloud` disabled | hidden | `Free · Upgrade` |
| Loading | two skeletons | one skeleton line | disabled placeholder | hidden | falls back to `session.plan` |
| Error | `Billing info unavailable` | `Retry` text-button | disabled placeholder | hidden | falls back to `session.plan` |

Live browser screenshots are deferred to QA — Agent-Browser was not invoked in this run.

## Verification Results

| Check | Result |
|-------|--------|
| `cd frontend && npx tsc --noEmit` | exit 0, zero errors |
| `cd frontend && npm run build` | `✓ Compiled successfully in 1498ms`; 21 routes prerendered; no warnings |
| Billing region hex-literal grep | 0 matches inside marker comments |
| `grep -c 'id="billing"' settings/page.tsx` | 1 |
| `grep -c 'Tier' settings/page.tsx` | 0 (legacy block removed) |
| `grep -c 'params.get("checkout") === "success"'` | 1 |
| `grep -c 'history.replaceState'` | 1 |
| `grep -c '<BillingStatusBanner />' Shell.tsx` | 1 |
| `<Topbar /> → <BillingStatusBanner /> → <div className="shell-main">` JSX order | confirmed via awk |
| `grep -c 'const { billing } = useBilling()' Topbar.tsx` | 1 |
| `grep -c 'billing?.plan ?? session?.plan' Topbar.tsx` | 1 |
| W2 explicit canceled/paused branch | 1 (`grep -cE 'status === "canceled" \\|\\| status === "paused"'`) |

## Deviations from Plan

None in substance. Plan executed exactly as written — the authoritative paste blocks from the plan + UI-SPEC were adopted verbatim. A few grep-literal acceptance criteria in the plan have slightly inaccurate wording (e.g., `grep -c "plan-pill-free\\|plan-pill-paid"` expected 2 while the classes live on a single line so the line-count is 1; `grep -c "Link.*href=\"/settings#billing\""` expected ≥1 while the `<Link>` + `href` spans two lines so a single-line regex sees 0). These are wording issues, not plan violations — the underlying invariants (both pill classes present, `<Link>` with hash anchor preserved) are satisfied. Flagged here for transparency.

No Rule 1–3 auto-fixes were needed. No architectural decisions escalated.

## Threat Flags

None — every mitigation in the plan's threat register (T-07-19 through T-07-25) is satisfied by the shipped code:

- **T-07-19 (Spoofed ?checkout=success):** listener only calls `refreshBilling()` and a benign `history.replaceState` — no state mutation, no external call, no cost surface.
- **T-07-20 (XSS via Paddle fields):** all `plan`, `status`, `currency`, `trial_ends_at`, `current_period_ends_at` render via JSX text interpolation or `Intl.NumberFormat` / `toLocaleDateString` — React escapes by default.
- **T-07-21 (Clickjacking on disabled CTA):** both CTAs are `disabled` + `aria-disabled="true"` — receive no click events.
- **T-07-22 (Banner persistence leak):** banner returns `null` when status leaves `past_due`; no sessionStorage/localStorage caching.
- **T-07-23 (Plan-label spoof):** client-side only affects UI; Phase-9 entitlement middleware is server-side.
- **T-07-24 (Wrong-workspace reads):** `/billing/summary` is workspace-scoped by `verify_token` (Plan 02).
- **T-07-25 (Banner-link phishing):** `href="/settings#billing"` is same-origin relative, no `target="_blank"`.

## Known Stubs

Two intentional disabled stubs per D-15:

- `Manage billing →` in the paid-state Billing card + loading/error variants — tooltip `Coming soon — self-serve billing ships in Phase 8`.
- `Upgrade to Cloud` in the free-state Billing card — tooltip `Coming soon — checkout ships in Phase 8`.

Both carry `disabled` + `aria-disabled="true"` + `title` so they are keyboard-inert and screen-reader-correct. Phase 8 will wire the first to the existing `/billing/portal` endpoint and the second to the new `/checkout` flow.

## TDD Gate Compliance

N/A — this plan is declared `type: execute` / `autonomous: true`, not `type: tdd`. No `test(...)` commit expected. Manual smoke per plan's `<verification>` section is the accepted gate; Agent-Browser visual verification is deferred to QA.

## Self-Check: PASSED

- [x] `frontend/src/components/BillingStatusBanner.tsx` exists (48 lines, `"use client";` on line 1).
- [x] `grep -c 'import { AlertTriangle } from "lucide-react"'` → 1.
- [x] `grep -c 'import { useBilling }' banner` → 1.
- [x] `grep -c 'billing?.status !== "past_due"'` → 1.
- [x] `grep -c 'Payment failed'` → 1.
- [x] `grep -c 'update billing'` → 1.
- [x] `grep -c '/settings#billing'` → 1.
- [x] `grep -c 'role="status"'` → 1.
- [x] `grep -c 'aria-live="polite"'` → 1.
- [x] `grep -c 'aria-hidden="true"'` → 1.
- [x] `grep -c 'var(--amber)'` → 4 (≥3 required).
- [x] `grep -c 'var(--bg2)'` → 1.
- [x] `grep -c 'var(--text)'` → 1.
- [x] `grep -c 'var(--border)'` → 1.
- [x] `grep -cE "#[0-9a-fA-F]{3,8}"` on banner → 0.
- [x] Shell.tsx: `import BillingStatusBanner` → 1, `<BillingStatusBanner />` → 1.
- [x] Shell.tsx JSX order: `<Topbar />` → `<BillingStatusBanner />` → `<div className="shell-main">`.
- [x] Topbar.tsx: `import { useBilling }` → 1, `const { billing } = useBilling()` → 1, `billing?.plan ?? session?.plan` → 1, `const { session } = useAuth()` → 1.
- [x] settings/page.tsx: `import { useBilling }` → 1, hook destructure → 1, `id="billing"` → 1.
- [x] settings/page.tsx: `function BillingCardBody` → 1, `function formatPrice` → 1, `function formatDate` → 1.
- [x] settings/page.tsx: `toLocaleDateString("en-US"` → 1, `Intl.NumberFormat` → 1.
- [x] settings/page.tsx: `Manage billing` → 3, `Upgrade to Cloud` → 1.
- [x] settings/page.tsx: `Coming soon — self-serve billing ships in Phase 8` → 3 (≥2 required).
- [x] settings/page.tsx: `Coming soon — checkout ships in Phase 8` → 1.
- [x] settings/page.tsx: `Next billing:` → 1, `Trial ends:` → 1, `Payment failed` → 0 (owned by banner).
- [x] settings/page.tsx: `params.get("checkout") === "success"` → 1, `history.replaceState` → 1.
- [x] settings/page.tsx: legacy Tier block removed (`grep -c "Tier"` → 0).
- [x] settings/page.tsx: `gridTemplateColumns: "1fr"` → 1 (Organization card adjusted).
- [x] settings/page.tsx: W2 explicit `status === "canceled" || status === "paused"` branch → 1.
- [x] Billing region hex-literal count (between marker comments) → 0.
- [x] Marker comments: opening → 1, closing → 1.
- [x] `cd frontend && npx tsc --noEmit` → exit 0, zero errors.
- [x] `cd frontend && npm run build` → ✓ Compiled successfully; 21 routes prerendered; no warnings.
- [x] Commit `313c56b` — `feat(phase-7-04): add BillingStatusBanner past_due component`.
- [x] Commit `2e5ac85` — `feat(phase-7-04): mount past_due banner + rewire Topbar pill to useBilling`.
- [x] Commit `793a89f` — `feat(phase-7-04): replace Settings Tier block with Billing summary card`.
- [x] Scope kept tight — exactly the four files in `files_modified`. No globals.css touched.
- [x] Zero new dependencies.
