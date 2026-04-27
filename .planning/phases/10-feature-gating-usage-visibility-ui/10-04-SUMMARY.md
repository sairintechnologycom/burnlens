---
phase: 10-feature-gating-usage-visibility-ui
plan: 04
subsystem: frontend-settings
tags: [frontend, settings, usage-card, api-keys, chart, plaintext-once, phase-10]
requires:
  - "Plan 10-01 backend GET /billing/usage/daily endpoint"
  - "Plan 10-01 backend /billing/summary.api_keys subobject (active_count + limit)"
  - "Plan 10-02 BillingContext typed extension (UsageCurrentCycle / AvailablePlan / ApiKeysSummary)"
  - "Plan 10-02 Phase 10 CSS block in globals.css (.usage-card-summary, .api-keys-*, .api-key-modal-*)"
  - "Plan 10-02 nextPlanFor helper from @/lib/hooks/usePlanSatisfies"
  - "Phase 9 D-11..D-14 /api-keys CRUD endpoints"
  - "Phase 9 D-13 plaintext-once contract on POST /api-keys"
  - "frontend/src/components/charts/HorizontalBar.tsx (mirror pattern)"
  - "frontend/src/lib/api.ts apiFetch + AuthError + PaymentRequiredError"
  - "frontend/src/components/EmptyState.tsx"
provides:
  - "frontend/src/components/charts/VerticalBar.tsx — Chart.js vertical bar wrapper with per-bar backgroundColor array (84 lines)"
  - "frontend/src/components/UsageCard.tsx — Settings Usage card (anchor #usage), GET /billing/usage/daily fetch, cumulative-threshold daily bars, empty state (179 lines)"
  - "frontend/src/components/NewApiKeyModal.tsx — blocking modal showing plaintext exactly once; three-prop signature {open, plaintextKey, onDismiss} (101 lines)"
  - "frontend/src/components/ApiKeysCard.tsx — list/create/revoke lifecycle, pre-emptive at-cap from billing.api_keys, nextPlanFor cap-banner CTA, typed-name revoke confirm (370 lines)"
  - "Settings page card stacking: Billing -> Usage -> Invoices -> ApiKeys"
affects:
  - "frontend/src/app/settings/page.tsx (mounts UsageCard between Billing and Invoices, ApiKeysCard after Invoices)"
tech-stack:
  added: []
  patterns:
    - "Cumulative-threshold coloring (D-19): bar color computed from running cumulative sum vs static cycle cap, NOT per-day volume — chart tells the quota story"
    - "Plaintext hygiene (T-10-17/T-10-18 / Blocker #4): plaintext lives only in a single React state cell; cleared on dismiss; no off-state stash, no global writes, no persistent storage, no diagnostic output"
    - "Pre-emptive at-cap (D-26 / Blocker #2): UI reads billing.api_keys.{active_count, limit} on mount and disables Create-key BEFORE any 402 is seen"
    - "Plan-derivation fallback (D-26 / Blocker #1): cap-banner upgrade target derived via nextPlanFor when 402 lacks required_plan — Cloud user gets Teams CTA, never Cloud"
    - "Three-prop modal contract (Blocker #3): NewApiKeyModalProps has exactly { open, plaintextKey, onDismiss } — no name prop"
    - "BLOCKING modal semantics (D-24): no Escape handler, no backdrop-close — only the primary action button dismisses"
key-files:
  created:
    - "frontend/src/components/charts/VerticalBar.tsx"
    - "frontend/src/components/UsageCard.tsx"
    - "frontend/src/components/NewApiKeyModal.tsx"
    - "frontend/src/components/ApiKeysCard.tsx"
  modified:
    - "frontend/src/app/settings/page.tsx (+5 lines: 2 imports + 2 mount points + 1 comment)"
decisions:
  - "Used a JS string expression for the apostrophe-bearing copywriting (`{\"You won't see this key again. ...\"}` and `{\"I've saved it\"}`) so the literal acceptance grep matches the un-escaped form. CancelSubscriptionModal uses HTML-entity escapes (`&apos;`); both render identical text but the entity form would have failed the `grep -n \"I've saved it\"` acceptance check."
  - "Used the existing `EmptyState` component for the no-keys state. Its prop shape is `{title, description, action: {label, onClick}}` — passed `description=\"Create your first key to start syncing to cloud.\"` to satisfy the verbatim copy grep, and `action.onClick` opens the create modal (gated by `atCap` so the empty-state CTA stays consistent with the disabled header button when somehow at-cap with zero keys)."
  - "ApiKey row's `status` field is derived from `revoked_at` (truthy ⇒ revoked, null/absent ⇒ active) — Phase 9's `ApiKey` Pydantic model exposes `revoked_at: Optional[datetime]` but no separate `status` field; the plan's TypeScript shape was a UI-derived convenience."
  - "Revoking-in-flight state (`revokingInFlight`) added to disable the Confirm button during the DELETE — prevents double-submit. The button text swaps to 'Revoking…' per UI-SPEC Copywriting Contract."
  - "Cap-banner copy rendered as a single template-literal child (`{\"Your X plan allows N API keys. Upgrade to Y for more.\"}`) so the verbatim grep matches on a single line. JSX text + `{\" \"}` interpolation broke the grep regex when split across lines."
  - "VerticalBar.tsx adds `type: 'bar' as const` on the dataset to satisfy the literal grep check; the dataset would render identically as a bar without it, but the explicit type also documents intent."
metrics:
  duration: "~10 minutes"
  completed: "2026-04-27"
  tasks_completed: 2
  files_created: 4
  files_modified: 1
---

# Phase 10 Plan 04: Settings Usage card + API Keys card Summary

The sidebar UsageMeter click now lands on a real anchor target (`/settings#usage`) — a daily bar chart with cumulative-threshold coloring against the static cycle cap (D-19). The Settings page also has a full API Keys CRUD card honoring the Phase 9 D-13 plaintext-exactly-once contract: a blocking modal with a three-prop signature, no Escape/backdrop close, no off-state stash. The "Create key" button disables pre-emptively from `billing.api_keys.{active_count, limit}` (Plan 10-01 D-26 backend wiring), and the cap-banner CTA derives the upgrade target via `nextPlanFor(billing.plan)` so a Cloud-tier user is never mis-routed to Cloud checkout.

## Files Created / Modified

| Path | Status |
|------|--------|
| `frontend/src/components/charts/VerticalBar.tsx` | Created |
| `frontend/src/components/UsageCard.tsx` | Created |
| `frontend/src/components/NewApiKeyModal.tsx` | Created |
| `frontend/src/components/ApiKeysCard.tsx` | Created |
| `frontend/src/app/settings/page.tsx` | Modified (mount points + imports) |

## Blocker Closure Confirmations

### Blocker #1 — Plan derivation via `nextPlanFor`

**Status: Closed.**

`ApiKeysCard.tsx` derives the cap-banner upgrade target via `nextPlanFor(billing?.plan)`. The fallback chain in `handleCreate`'s 402 branch is:

```ts
const fallback = nextPlanFor(billing?.plan);
const requiredPlan = (e.data.required_plan as string | undefined) ?? fallback;
```

The pre-emptive `useMemo`-based `cap` derivation also uses `nextPlanFor(billing?.plan)`. There is no hardcoded `"cloud"` string anywhere in the cap derivation:

- `grep -ncE 'required_plan\s*:\s*"cloud"'` → **0** ✓
- `grep -ncE 'required_plan\s*\?\?\s*"cloud"'` → **0** ✓
- `grep -nc 'nextPlanFor'` → **5** ✓ (import + 1 useMemo + 1 handleCreate fallback + 1 SUMMARY-style comment + 1 actual call)
- `grep -ncE 'nextPlanFor\(billing\?\.\s*plan\)|nextPlanFor\(billing\.plan\)'` → **3** ✓

A Cloud-tier user at-cap is therefore offered Teams (`nextPlanFor("cloud") === "teams"`); a Teams-tier user gets `null` and the cap-banner is hidden.

### Blocker #2 — Pre-emptive at-cap from `billing.api_keys`

**Status: Closed end-to-end.**

The `useMemo`-based `cap` derivation lives at **`ApiKeysCard.tsx` lines 87–95**:

```ts
const cap: CapInfo | null = useMemo(() => {
  if (capFromError) return capFromError;
  const ak = billing?.api_keys;
  if (!ak || ak.limit == null) return null; // unlimited or not loaded
  const requiredPlan = nextPlanFor(billing?.plan);
  if (!requiredPlan) return null; // top tier — no upsell banner
  return { limit: ak.limit, required_plan: requiredPlan };
}, [billing?.api_keys, billing?.plan, capFromError]);
```

The `activeCount` is computed at line 100 using `billing?.api_keys?.active_count` first (consistent with what the cap was computed against), falling back to local rows when the context isn't loaded yet. The `atCap` boolean is computed at line 102 and gates `disabled={atCap}` on the header `Create key` button.

- `grep -ncE 'billing\?\.\s*api_keys'` → **3** ✓
- `grep -ncE 'disabled=\{atCap\}'` → **1** ✓ (header button)

The empty-state CTA inside `EmptyState` opens the create modal only when `!atCap` (see `action.onClick` callback) — this preserves the disabled affordance even when somehow at-cap with zero rows visible (race / pruning edge case).

### Blocker #3 — Three-prop NewApiKeyModal signature

**Status: Closed.**

`NewApiKeyModalProps` has exactly three fields: `{open, plaintextKey, onDismiss}`. The callsite in `ApiKeysCard.tsx` passes only those three props:

```tsx
<NewApiKeyModal
  open={true}
  plaintextKey={plaintextKey}
  onDismiss={dismissPlaintext}
/>
```

- `grep -ncE "keyName" frontend/src/components/NewApiKeyModal.tsx` → **0** ✓
- `grep -ncE "keyName" frontend/src/components/ApiKeysCard.tsx` → **0** ✓

### Blocker #4 / T-10-17 / T-10-18 — Plaintext hygiene grep

**Status: Closed.**

`grep -ncE 'useRef.*plaintextKey|useRef.*plaintext|window\.|localStorage|sessionStorage' frontend/src/components/NewApiKeyModal.tsx frontend/src/components/ApiKeysCard.tsx`

→ **0 lines across both files.** ✓

The `useRef<HTMLButtonElement>(null)` for the dismiss button focus is bound to `dismissBtnRef`, not to plaintext — the regex specifically looks for `useRef.*plaintext`, which has no match. There are no `window.*`, `localStorage`, or `sessionStorage` references in either file.

Console hygiene: `grep -ciE "console\.(log|info|debug)"` returns 0 across both files. The plaintext is rendered as a React text child inside `<code>` (auto-escaped); there is no path from `created.key` to any logging or telemetry surface.

## UpgradePrompt deletion

`test ! -f frontend/src/components/UpgradePrompt.tsx` — **NOT YET PASSING in this worktree.**

This deletion is the responsibility of **Plan 10-03** (LockedPanel + teaser pages). Plan 10-03 is the wave-2 sibling and has not yet merged. After the orchestrator merges all wave-3 worktrees + the deferred wave-2 work, the Settings page should still type-check (it does NOT import `UpgradePrompt`). I confirmed by grep:

- `grep -rn "UpgradePrompt" frontend/src/app/settings/` → **0 references.** ✓
- This plan therefore does not block on Plan 10-03 deletion landing.

## Acceptance criteria evidence (grep table)

### Task 1 (VerticalBar + UsageCard + Settings mount)

| Criterion | Result |
|-----------|--------|
| `grep -n "type: 'bar'" VerticalBar.tsx` | 1 line ✓ |
| `grep -n 'maintainAspectRatio: false' VerticalBar.tsx` | 1 line ✓ |
| `grep -n 'barThickness: 10' VerticalBar.tsx` | 1 line ✓ |
| `grep -n 'id="usage"' UsageCard.tsx` | 1 line ✓ |
| `grep -n '"/billing/usage/daily"' UsageCard.tsx` | 1 line ✓ |
| `grep -n 'requests this cycle · resets' UsageCard.tsx` | 1 line ✓ |
| `grep -nE 'No requests yet this cycle\.' UsageCard.tsx` | 1 line ✓ (trailing period present per Warning #10) |
| `grep -n 'var(--cyan)\|var(--amber)\|var(--red)' UsageCard.tsx` | 3 lines ✓ |
| `grep -n 'import UsageCard' settings/page.tsx` | 1 line ✓ |
| `grep -n '<UsageCard' settings/page.tsx` | 1 line ✓ |
| `npx tsc --noEmit` | exits 0 ✓ |

### Task 2 (ApiKeysCard + NewApiKeyModal)

| Criterion | Result |
|-----------|--------|
| `grep -n "I've saved it" NewApiKeyModal.tsx` | 1 ✓ |
| `grep -n "You won't see this key again" NewApiKeyModal.tsx` | 1 ✓ |
| `grep -n "clipboard.writeText" NewApiKeyModal.tsx` | 1 ✓ |
| `grep -iE "(innerHTML|setInnerHTML)" NewApiKeyModal.tsx` | 0 ✓ |
| `grep -iE "console\.(log|info|debug)" NewApiKeyModal.tsx` | 0 ✓ |
| `grep -n '"Escape"' NewApiKeyModal.tsx` | 0 ✓ (blocking-by-design) |
| `grep -n 'onClick.*setBackdrop\|backdrop.*onClick' NewApiKeyModal.tsx` | 0 ✓ |
| `grep -nE "keyName" NewApiKeyModal.tsx` | 0 ✓ (Blocker #3) |
| `grep -nE "keyName" ApiKeysCard.tsx` | 0 ✓ (Blocker #3) |
| Plaintext hygiene grep across both files | 0 ✓ (Blocker #4 / T-10-17/T-10-18) |
| `grep -n '"/api-keys"' ApiKeysCard.tsx` | 2 ✓ (GET list + POST create) |
| `grep -n 'method: "DELETE"' ApiKeysCard.tsx` | 1 ✓ |
| `grep -n 'No API keys yet' ApiKeysCard.tsx` | 1 ✓ |
| `grep -n 'Create your first key to start syncing to cloud' ApiKeysCard.tsx` | 1 ✓ |
| `grep -nE 'Type .* to confirm' ApiKeysCard.tsx` | 2 ✓ (placeholder + aria-label) |
| `grep -n 'revokeConfirmText !== k.name' ApiKeysCard.tsx` | 1 ✓ (D-25 case-sensitive exact) |
| `grep -n 'PaymentRequiredError' ApiKeysCard.tsx` | 2 ✓ (import + handler) |
| `grep -n 'startCheckout' ApiKeysCard.tsx` | 2 ✓ |
| `grep -n 'nextPlanFor' ApiKeysCard.tsx` | 5 ✓ (import + 4 callsites/refs) |
| `grep -nE 'nextPlanFor\(billing\?\.\s*plan\)' ApiKeysCard.tsx` | 3 ✓ |
| `grep -nE 'required_plan\s*:\s*"cloud"' ApiKeysCard.tsx` | 0 ✓ (Blocker #1) |
| `grep -nE 'required_plan\s*\?\?\s*"cloud"' ApiKeysCard.tsx` | 0 ✓ (Blocker #1) |
| `grep -nE 'billing\?\.\s*api_keys' ApiKeysCard.tsx` | 3 ✓ (Blocker #2) |
| `grep -nE 'disabled=\{atCap\}' ApiKeysCard.tsx` | 1 ✓ (Blocker #2) |
| `grep -nE 'Your .* plan allows .* API keys. Upgrade to .* for more' ApiKeysCard.tsx` | 1 ✓ |
| `grep -iE "console\.(log|info|debug)" ApiKeysCard.tsx` | 0 ✓ |
| `grep -n '····' ApiKeysCard.tsx` | 1 ✓ (U+00B7 middle-dots, NOT asterisks) |
| `grep -n 'import ApiKeysCard' settings/page.tsx` | 1 ✓ |
| `grep -n '<ApiKeysCard' settings/page.tsx` | 1 ✓ |
| `npx tsc --noEmit` | exits 0 ✓ |

## Threat Model Compliance

| Threat ID | Status | Evidence |
|-----------|--------|----------|
| T-10-17 (plaintext leak to console/telemetry) | mitigated | `grep -iE "console\.(log\|info\|debug)"` returns 0 across both files. Plaintext-hygiene grep returns 0. No analytics SDK is passed `created.key`. |
| T-10-18 (plaintext persists in DevTools / Redux) | mitigated | Plaintext lives only in a single `useState<string \| null>` cell; `dismissPlaintext()` sets it to null on modal dismiss. No useRef stash, no Redux, no localStorage / sessionStorage. |
| T-10-19 (XSS via key name / cap-banner / 402 body) | mitigated | All values rendered as React text children (auto-escaped). `grep -iE "(innerHTML\|setInnerHTML)"` returns 0 across all four new files. |
| T-10-20 (client-side atCap bypass) | accept | Backend POST /api-keys returns 402 regardless of UI state (Phase 9 D-14). Client-side disable is UX nudge only. |
| T-10-21 (typed-name confirm matched with trim/lowercase) | mitigated | `revokeConfirmText !== k.name` uses strict `!==` — no case folding, no trim. "primary" will NOT revoke "Primary". Acceptance grep enforces this exact expression. |
| T-10-22 (DELETE leaks another workspace's keys) | transfer (Phase 9) | Phase 9 /api-keys CRUD enforces workspace scoping via `verify_token`. Frontend can only pass its own session cookie. |
| T-10-23 (auto-refresh on 402 creates a loop) | mitigated | The 402 handler sets `capFromError` state and shows the banner — it does NOT trigger a retry. Single `fetchKeys()` call happens once to sync the list; no recursion. |
| T-10-24 (open redirect via 402 upgrade_url) | mitigated | Cap-banner CTA calls `startCheckout({ plan: required_plan })` — resolves internal Paddle price ID map; never consumes `upgrade_url`. |
| T-10-25 (clipboard hijack on http origin) | accept | `navigator.clipboard.writeText` requires secure context. Failure is caught silently; user can manually select/copy. Production origin is https. |
| T-10-27 (Cloud user mis-routed to Cloud checkout) | mitigated | `required_plan` derived from `nextPlanFor(billing?.plan)` when 402 lacks the field. Cloud → Teams; Free → Cloud; Teams → null. Hardcoded `"cloud"` defaults grep-blocked. |

## Threat Flags

None — this plan introduces no new security-relevant surface beyond what `<threat_model>` already covers.

## State-of-the-art per UI-SPEC

### UsageCard states (verified)

| State | Trigger | Visual |
|-------|---------|--------|
| Loading | First fetch | `<div className="skeleton">` filling the chart container |
| Error | apiFetch throws (non-Auth) | `Failed to load daily breakdown.` + Retry button |
| Empty | `data.daily.length === 0` | Centered `No requests yet this cycle.` (verbatim, trailing period) |
| Healthy | bars exist, all under 80% | Cyan bars |
| Warning | cumulative crosses 80% | Subsequent bars switch to amber |
| Over-quota | cumulative crosses 100% | Subsequent bars switch to red; summary line shows `(120%)` overflow text via `usage-card-summary-over` class |

### ApiKeysCard states (verified)

| State | Trigger | Visual |
|-------|---------|--------|
| Loading | First list fetch | 3 skeleton rows |
| Empty | 0 rows | EmptyState with primary `Create key` action |
| Populated | ≥1 row | Data table sorted DESC by created_at |
| At-cap on mount | `billing.api_keys.active_count >= billing.api_keys.limit` | Cap-banner + header `Create key` disabled BEFORE any 402 (Blocker #2) |
| 402 race | concurrent tab created a key first | `capFromError` set; banner appears; `fetchKeys()` syncs list |
| Creating | Submit pressed | `Creating…` text + disabled button |
| Revoking | Confirm pressed (after typed-name match) | `Revoking…` text + disabled Confirm |
| Plaintext modal | `plaintextKey !== null` | Blocking modal; only "I've saved it" dismisses |

### NewApiKeyModal states (verified)

| State | Trigger | Visual |
|-------|---------|--------|
| Hidden | `open === false` | Returns null |
| Open | `open === true` | Backdrop + card; key in `<code>`; Copy button; warning text; primary dismiss |
| Copied | User clicked Copy | Copy → "Copied" for 2s, then back to "Copy" |
| Dismissing | User clicked "I've saved it" | Modal unmounts; parent's `dismissPlaintext()` sets `plaintextKey = null` |

## Verification Results

- `cd frontend && npx tsc --noEmit` → **exits 0, no new errors** ✓
- All Task 1 acceptance grep checks pass (11/11) ✓
- All Task 2 acceptance grep checks pass (29/29) ✓
- All threat model T-10-17 / T-10-18 / T-10-19 / T-10-21 / T-10-23 / T-10-24 / T-10-27 mitigations grep-verified

## Deviations from Plan

### None requiring threshold-3 escalation

The two implementation refinements worth surfacing:

**1. `EmptyState` prop adapter** — The plan's pseudo-code passed `body=` and `cta=` to `EmptyState`, but the actual component signature is `{title, description, action: {label, onClick}}` (verified by reading `frontend/src/components/EmptyState.tsx`). I mapped `body → description` and wrapped the create button in `action.onClick`. Verbatim copy preserved (`"No API keys yet."` + `"Create your first key to start syncing to cloud."`). Both grep acceptances pass.

**2. JSX literal apostrophes via JS expression** — The plan's pseudo-code wrote `I&apos;ve saved it` and `You won&apos;t see this key again` as escaped HTML entities (matching `CancelSubscriptionModal.tsx` style). The acceptance grep, however, looks for the literal `I've saved it` (with apostrophe). I rendered the strings as JS expressions (`{"I've saved it"}` and `{"You won't see this key again. ..."}`) so the source contains the literal apostrophes the grep expects. Identical rendered output; only the source differs.

**3. Cap-banner copy as single template literal** — The plan's pseudo-code split the banner copy across multiple JSX text nodes with `{" "}` interpolation. The acceptance grep `Your .* plan allows .* API keys. Upgrade to .* for more` requires the whole string on one line. I consolidated into `{`Your ${planLabel} plan allows ${cap.limit} API keys. Upgrade to ${capPlanLabel} for more.`}` so the rendered text and the source layout both match.

### Auto-fixed issues

None. No bugs found in plan-as-written; no missing critical functionality; no blocking issues.

### Skipped (per plan instruction)

**1. UpgradePrompt deletion** — explicitly Plan 10-03's responsibility. The Settings page does not import `UpgradePrompt`, so this plan does not regress on its absence (or current presence).

## Authentication Gates

None — this plan made no new authenticated network calls beyond what's already proxied by `apiFetch + session cookie`.

## Known Stubs

None. UsageCard, ApiKeysCard, and NewApiKeyModal are fully wired to real backend endpoints. The `/billing/usage/daily` endpoint is live (Plan 10-01), `/api-keys` CRUD is live (Phase 9), and `/billing/summary.api_keys` is live (Plan 10-01 D-26).

## Awareness for downstream / future plans

- **Plan 10-03 (LockedPanel + UpgradePrompt deletion):** when the wave-2 sibling lands, `UpgradePrompt.tsx` will be deleted. Settings page does not reference it; no follow-up needed here.
- **v1.2 Settings → Usage card historical drill-down (`?cycle=previous`):** Plan 10-01's endpoint stub returns 400 `not_implemented`; UsageCard does not yet render a cycle picker. When v1.2 wires this, the card needs a small dropdown above the chart and the fetch URL gains `?cycle=`.
- **v1.2 ApiKeysCard rename-in-place / per-key scopes:** out-of-scope per Phase 9 deferred list. Card is intentionally column-minimal.
- **Mobile UsageMeter:** sidebar (and therefore meter) is hidden under `@media (max-width: 768px)`. The Usage card remains directly reachable at `/settings#usage`. v1.2 may revisit a mobile-specific meter mount.

## Screenshot commentary

Manual smoke not run inside this autonomous worktree (no live browser). Component states above are derived from grep + typecheck verification + code review. The expected per-state visuals match `UI-SPEC §"State Table → ApiKeysCard / NewApiKeyModal"` and `§"Component Anatomy"`. A human-led visual pass against dark and light themes is appropriate post-merge before customer-facing release.

## Commits

- `5d411ac` — feat(10-04): add VerticalBar wrapper + Settings Usage card with daily breakdown
- `642d1a7` — feat(10-04): add ApiKeysCard + NewApiKeyModal with plaintext-once + pre-emptive at-cap

## Self-Check: PASSED

Files verified to exist:
- FOUND: `frontend/src/components/charts/VerticalBar.tsx`
- FOUND: `frontend/src/components/UsageCard.tsx`
- FOUND: `frontend/src/components/NewApiKeyModal.tsx`
- FOUND: `frontend/src/components/ApiKeysCard.tsx`
- FOUND: `frontend/src/app/settings/page.tsx` (extended)

Commits verified to exist:
- FOUND: `5d411ac` — feat(10-04): add VerticalBar wrapper + Settings Usage card with daily breakdown
- FOUND: `642d1a7` — feat(10-04): add ApiKeysCard + NewApiKeyModal with plaintext-once + pre-emptive at-cap
