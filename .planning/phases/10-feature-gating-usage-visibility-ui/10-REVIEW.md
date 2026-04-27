---
phase: 10-feature-gating-usage-visibility-ui
reviewed: 2026-04-27T22:30:00Z
depth: standard
files_reviewed: 17
files_reviewed_list:
  - tests/test_billing_usage.py
  - tests/test_billing_webhook_phase7.py
  - burnlens_cloud/models.py
  - burnlens_cloud/billing.py
  - frontend/src/components/UsageMeter.tsx
  - frontend/src/lib/hooks/usePlanSatisfies.ts
  - frontend/src/lib/contexts/BillingContext.tsx
  - frontend/src/components/Sidebar.tsx
  - frontend/src/app/globals.css
  - frontend/src/components/LockedPanel.tsx
  - frontend/src/app/teams/page.tsx
  - frontend/src/app/customers/page.tsx
  - frontend/src/components/charts/VerticalBar.tsx
  - frontend/src/components/UsageCard.tsx
  - frontend/src/components/NewApiKeyModal.tsx
  - frontend/src/components/ApiKeysCard.tsx
  - frontend/src/app/settings/page.tsx
findings:
  critical: 0
  warning: 4
  info: 7
  total: 11
status: issues_found
---

# Phase 10: Code Review Report

**Reviewed:** 2026-04-27T22:30:00Z
**Depth:** standard
**Files Reviewed:** 17
**Status:** issues_found

## Summary

Phase 10 ships frontend feature-gating (LockedPanel, locked sidebar items, dynamic
402-driven CTAs), the sidebar usage meter, and a Settings drill-down with a daily
usage chart and full API Keys management. The backend extends `/billing/summary`
with three additive subobjects and adds `GET /billing/usage/daily`.

Overall the implementation is careful and well-commented:

- **Plaintext API key hygiene** is solid in `NewApiKeyModal` / `ApiKeysCard`:
  the freshly-minted key lives in a single React state cell, no
  `localStorage` / `sessionStorage` / `window` writes, no `console.log`,
  no `useRef` stash. Modal is blocking with no Esc/backdrop close. The
  contract invariants in the file headers match the implementation.
- **Plan-derivation for upgrade CTAs** correctly uses `nextPlanFor()` when a
  402 lacks `required_plan`, never blindly defaults to "cloud", and Teams
  users (top tier) are explicitly handled (no upsell shown).
- **Backend tenant isolation** is enforced — every workspace-scoped SELECT in
  `/billing/summary` and `/billing/usage/daily` parameterizes on
  `token.workspace_id` (asyncpg `$N` placeholders, no string interpolation).
  Tests `test_summary_api_keys_workspace_isolation` and
  `test_usage_daily_workspace_isolation` actively assert WS_B never appears
  in SQL args even when smuggled via `?workspace_id=…`.
- **XSS surface** is clean — every rendered API value (numerics, dates,
  plan labels, plaintext key) goes through React text-child auto-escaping.
  No raw-HTML escape hatches are used. No `innerHTML`, no `eval`.

The findings below are quality and defensive-hardening items — none rise to
the security-critical level. **IN-06 is a likely real functional bug** — the
sidebar usage meter never leaves loading state because the frontend
`BillingSummary.usage` shape disagrees with the backend wire shape; verify
in dev and consider promoting to Warning if confirmed.

## Warnings

### WR-01: Pre-existing API-key plaintext written to `localStorage` survives in reviewed file

**File:** `frontend/src/app/settings/page.tsx:65`
**Issue:** The `handleRegenerate` flow (legacy Phase ≤8 code) does
`localStorage.setItem("burnlens_api_key", data.api_key)` immediately after
the regenerate-key endpoint returns the new plaintext. Phase 10's stated
plaintext-once contract (D-13 / D-24) for the new `ApiKeysCard` modal is
correctly enforced, but this *legacy* sibling code path on the same page
violates that same principle for the workspace-level "regenerate API key"
flow. Plaintext now persists in browser storage indefinitely, accessible
to any same-origin script (XSS, browser extensions, devtools).
This was not introduced by Phase 10, but Phase 10 makes the contract
mismatch worse by sitting next to a brand-new `ApiKeysCard` that
explicitly forbids the same pattern.
**Fix:**
```ts
// Drop the localStorage write. Adopt the same NewApiKeyModal pattern:
// store plaintext in component state only, force a one-time copy/save
// modal, and clear on dismiss. Then trigger the existing reload via
// session refresh rather than a hard window.location.reload() so the
// in-memory plaintext is GC'd cleanly.
const data = await apiFetch("/api/v1/orgs/regenerate-key", session.token, { method: "POST" });
setRegeneratedPlaintext(data.api_key); // local state only
showToast("API key regenerated", "success");
// Do NOT: localStorage.setItem("burnlens_api_key", data.api_key);
// Do NOT: window.location.reload();  // breaks plaintext-once contract
```
Track as a Phase 11 follow-up if a same-PR fix is too risky.

### WR-02: `setBilling` consumer name in context value is misleading vs Pydantic-coerced applier

**File:** `frontend/src/lib/contexts/BillingContext.tsx:60-70, 129-137, 164`
**Issue:** The exposed context value uses `setBilling: applyBilling`. From
a consumer perspective, `setBilling(next)` looks like a raw state setter
(`React.Dispatch<SetStateAction<...>>`), but the underlying function
*coerces unknown statuses to `"active"`* and *bumps `lastFetchRef`*. A
caller passing a value with an invalid status will silently get a
different status back on the next render — surprising and not
discoverable from the type signature. The `DEFAULT_VALUE.setBilling = () => {}`
fallback also silently no-ops outside a Provider.
**Fix:**
```ts
// Rename for clarity:
interface BillingContextValue {
  billing: BillingSummary | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  applyBilling: (next: BillingSummary) => void; // ← rename
}
// ...and update the two call sites in settings/page.tsx accordingly.
```
The name `applyBilling` matches the internal symbol and signals the
coercion side-effect.

### WR-03: `scheduleRefresh` cleanup return value is discarded — timers fire on unmounted parent

**File:** `frontend/src/app/settings/page.tsx:292-299, 310, 364, 382`
**Issue:** `scheduleRefresh()` schedules two `window.setTimeout` calls and
returns a cleanup closure. All three callers (`handleReactivate`,
`handleChangePlan`, `handleCancelSuccess`) discard the returned cleanup.
If the user navigates away before the 3s/10s timers fire, the timers
will still execute `onRetry()` (which calls `refresh()` from
`BillingContext`). `refresh()` itself is safe (it `setState`s on an
unmounted parent only when the provider is still mounted), but you'll
still get unnecessary network calls and a React "set state on unmounted"
warning if the provider also unmounts. The retained cleanup function is
dead code today.
**Fix:**
```ts
// Track the returned cleanup in a ref and run it on unmount.
const refreshCleanupRef = useRef<(() => void) | null>(null);
useEffect(() => () => refreshCleanupRef.current?.(), []);

const scheduleRefresh = useCallback(() => {
  refreshCleanupRef.current?.(); // cancel any prior scheduled pair
  const t1 = window.setTimeout(() => onRetry(), 3000);
  const t2 = window.setTimeout(() => onRetry(), 10000);
  refreshCleanupRef.current = () => {
    window.clearTimeout(t1);
    window.clearTimeout(t2);
  };
}, [onRetry]);
```

### WR-04: `NewApiKeyModal` copy-feedback timer not cleared on unmount

**File:** `frontend/src/components/NewApiKeyModal.tsx:45`
**Issue:** `handleCopy` fires `setTimeout(() => setCopied(false), 2000)`
but never clears it. If the user clicks Copy and then immediately clicks
"I've saved it" (which unmounts the modal because the parent sets
`plaintextKey` back to `null`), the pending `setCopied(false)` callback
will run on an unmounted component → React "Can't perform a React state
update on an unmounted component" warning. Not a security or correctness
issue, but the modal is the only place plaintext lives, so any pending
React work that re-runs after unmount is a smell to eliminate.
**Fix:**
```ts
const copyTimerRef = useRef<number | null>(null);
useEffect(() => {
  return () => {
    if (copyTimerRef.current !== null) window.clearTimeout(copyTimerRef.current);
  };
}, []);

const handleCopy = async () => {
  try {
    await navigator.clipboard.writeText(plaintextKey);
    setCopied(true);
    if (copyTimerRef.current !== null) window.clearTimeout(copyTimerRef.current);
    copyTimerRef.current = window.setTimeout(() => setCopied(false), 2000);
  } catch { /* ... */ }
};
```

## Info

### IN-01: `usePlanSatisfies` `PLAN_ORDER` ranking ignores hierarchical relationships explicitly

**File:** `frontend/src/lib/hooks/usePlanSatisfies.ts:8-27`
**Issue:** The hardcoded `["free", "cloud", "teams"]` array makes the
linear-rank assumption explicit but is brittle if a future `enterprise`
or `solo` tier lands between `cloud` and `teams`. Also, mismatched
casing (`"Free"` vs `"free"`) silently fails closed (returns false). The
Sidebar consumer correctly lowercases the plan, but other future
consumers may not.
**Fix:** Add a `// PLAN_ORDER must remain ordered low→high tier` comment,
and consider exporting a `normalizePlan(s: string): PlanName | null`
helper that does the lowercase + lookup so consumers cannot forget.

### IN-02: `nextPlanFor("Cloud")` (capitalized) returns `"cloud"` instead of `"teams"`

**File:** `frontend/src/lib/hooks/usePlanSatisfies.ts:46-53`
**Issue:** `nextPlanFor` does case-sensitive string comparison on
`current === "free"` / `current === "cloud"`. If a caller passes the
capitalized `"Cloud"` (which `Sidebar` does NOT, but `ApiKeysCard.tsx:89`
passes `billing?.plan` raw from the API — currently lowercase by
backend convention, but not guaranteed), the function falls through to
`return "cloud"` — i.e., a Cloud user would be told to upgrade *to
Cloud*. The backend currently emits lowercase plan slugs so this is
latent, but worth hardening.
**Fix:**
```ts
export function nextPlanFor(
  current: string | null | undefined,
): "cloud" | "teams" | null {
  const c = (current ?? "").toLowerCase();
  if (!c || c === "free") return "cloud";
  if (c === "cloud") return "teams";
  return null;
}
```

### IN-03: `UsageMeter` does not show overage band when `pct > 100` and `isEmptyCycle` is true

**File:** `frontend/src/components/UsageMeter.tsx:55-60, 80-85`
**Issue:** If `current === 0` AND the cycle is < 24h old, `isEmptyCycle`
is true and the colored fill is skipped. But if `cap === 0`
(misconfigured plan or backend race) and `current === 0`, `pct === 0`,
`band === "green"`, and the bar renders empty — fine. However, if
`current === 0` due to a brand-new cycle but `cap === 0` because the
backend's `_resolve_current_cycle` returned `monthly_request_cap=0`
(per `billing.py:763-765` fallback), then displaying "0 / 0" with
"first cycle" is technically incorrect — it should say "loading…" or
"unmetered". Edge case but worth a defensive fall-through to the
loading skeleton.
**Fix:**
```ts
if (cap === 0 && current === 0) {
  // Treat as not-yet-resolved rather than "first cycle".
  return /* loading skeleton */;
}
```

### IN-04: `useMemo` deps in `ApiKeysCard.cap` don't track `nextPlanFor` reference

**File:** `frontend/src/components/ApiKeysCard.tsx:85-92`
**Issue:** `useMemo(() => { ... nextPlanFor(billing?.plan) ... }, [billing?.api_keys, billing?.plan, capFromError])`
omits `nextPlanFor` from the deps. ESLint's react-hooks/exhaustive-deps
would flag this. `nextPlanFor` is a module-level pure function so it's
safe, but if it's ever refactored to a hook or curried function the
memo could go stale. Add an eslint-disable comment with a one-liner
justification, or pull `nextPlanFor(billing?.plan)` to a separate
`useMemo` for readability.

### IN-05: Type-narrowing via `as unknown as` in settings/page.tsx defeats TypeScript

**File:** `frontend/src/app/settings/page.tsx:339-342, 454-457`
**Issue:** Two `as unknown as { scheduled_plan?: string | null; … }`
casts work around `BillingSummary` not yet exposing those fields in the
public type. The fields ARE in the Pydantic model
(`burnlens_cloud/models.py:239-240`) and they ARE NOT in the typed
`BillingSummary` interface (`BillingContext.tsx:42-54` was updated for
`usage`/`available_plans`/`api_keys` but not for
`scheduled_plan`/`scheduled_change_at`). Either add those two optional
fields to the TypeScript interface (preferred — single source of truth)
or remove the comment that references "Plan 08-08" since the data shape
has been live for a while.
**Fix:**
```ts
// frontend/src/lib/contexts/BillingContext.tsx
export interface BillingSummary {
  // ...existing fields...
  scheduled_plan?: string | null;
  scheduled_change_at?: string | null;
  usage?: UsageCurrentCycle | null; // see IN-06 — flat, not wrapped
  available_plans?: AvailablePlan[];
  api_keys?: ApiKeysSummary | null;
}
```
Then drop the `billingAny` / `nextAny` casts.

### IN-06: `BillingSummary.usage` shape mismatch — frontend wraps in `{ current_cycle }`, backend returns flat `UsageCurrentCycle`

**File:** `frontend/src/lib/contexts/BillingContext.tsx:51`,
`burnlens_cloud/billing.py:766-771,800`,
`frontend/src/components/UsageMeter.tsx:25`
**Issue:** Frontend type says `usage?: { current_cycle: UsageCurrentCycle } | null`
and `UsageMeter` reads `billing?.usage?.current_cycle`. Backend at
`billing.py:766-771,800` returns `usage=UsageCurrentCycle(...)` — a
*flat* object, not wrapped in `{ current_cycle: ... }`. So at runtime
`billing.usage` is a `UsageCurrentCycle` (has `start`/`end`/
`request_count`/`monthly_request_cap`), but the frontend expects
`billing.usage.current_cycle.<field>`. This means `UsageMeter` falls
through to the loading skeleton ALWAYS (`cycle` is always `undefined`),
and `UsageCard.tsx:86-88`'s fallback `billing?.usage?.current_cycle?.…`
also always evaluates to undefined. The card still works because the
`/billing/usage/daily` round-trip provides `data.current` / `data.cap`
authoritatively, but the meter never leaves loading until the daily
fetch lands. **This is a real functional bug — flag higher than Info if
verified.** Verify by hitting `/billing/summary` in dev and inspecting
the returned `usage` shape.
**Fix:** Either:
- (preferred) Change the frontend type + reads to `billing.usage.start`
  etc. — matches the backend wire shape and the
  `test_summary_includes_usage_current_cycle` assertions on
  `body["usage"]["request_count"]` (flat).
- Or change the backend to nest: `usage={"current_cycle":
  UsageCurrentCycle(...)}` — but this also breaks the existing tests.

The tests directly assert flat shape (`body["usage"]["request_count"]`,
`body["usage"]["monthly_request_cap"]`, `body["usage"]["start"]`), so
the **frontend is wrong** and should be fixed.

### IN-07: `_resolve_current_cycle` ignores `monthly_request_cap=0` vs `None` distinction

**File:** `burnlens_cloud/billing.py:763-765, 850-854`
**Issue:** `monthly_request_cap = resolved.monthly_request_cap if resolved and resolved.monthly_request_cap is not None else 0`
collapses both "no plan_limits row" and "plan limits row exists with
cap=0 (unlimited?)" to `0`. The `ApiKeysSummary.limit` field uses `None`
for unlimited, but `UsageCurrentCycle.monthly_request_cap` uses `0` for
the "missing" case — inconsistent. Frontend treats `cap === 0` as a
divide-by-zero guard (good) but cannot tell "I don't have a cap" from
"cap was misconfigured to zero". Consider making `monthly_request_cap:
Optional[int] = None` on `UsageCurrentCycle` to align with
`ApiKeysSummary.limit`, then have the meter render a friendly
"Unmetered" subtitle when null.

---

_Reviewed: 2026-04-27T22:30:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
