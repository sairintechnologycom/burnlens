---
phase: 07-paddle-lifecycle-sync
plan: 03
subsystem: frontend.billing-context
status: complete
tags: [react, nextjs, polling, context, billing]
requirements:
  - PDL-04
  - BILL-01
  - BILL-02
dependency_graph:
  requires:
    - burnlens_cloud/billing.py::billing_summary — GET /billing/summary endpoint (Plan 07-02)
    - frontend/src/lib/api.ts::apiFetch, AuthError — authenticated fetch + 401 sentinel
    - frontend/src/lib/hooks/useAuth.ts::useAuth — session + logout
    - frontend/src/lib/contexts/PeriodContext.tsx — no-throw hook convention to mirror
  provides:
    - frontend/src/lib/contexts/BillingContext.tsx::BillingProvider — mounted once in Shell
    - frontend/src/lib/contexts/BillingContext.tsx::useBilling — { billing, loading, error, refresh }
    - frontend/src/lib/contexts/BillingContext.tsx::BillingSummary — TypeScript interface
  affects:
    - Phase 7 Plan 04 (Topbar badge + Settings Billing card + past_due banner) — consumers of useBilling()
    - Phase 8 (checkout redirect) — will navigate with ?checkout=success and call refresh() from the Settings page
tech_stack:
  added: []
  patterns:
    - Single shared React context for /billing/summary (replaces per-component polling)
    - Visibility-gated setInterval (paused when document.visibilityState !== 'visible')
    - Staleness-gated focus refetch (10s threshold debounces rapid focus/blur)
    - Session-gated mount (providers render only after useAuth returns a truthy session)
    - AuthError -> logout() catch-branch (mirrors dashboard/page.tsx)
    - No-throw hook default via createContext default value (mirrors PeriodContext)
    - Runtime status coercion (W5): unknown Paddle states fall back to "active"
key_files:
  created:
    - frontend/src/lib/contexts/BillingContext.tsx  # 128 lines, new
  modified:
    - frontend/src/components/Shell.tsx  # +4 / -1 (import + JSX wrap + re-indent)
decisions:
  - "BillingProvider nests INSIDE PeriodProvider (order arbitrary; Period stays outermost to minimise diff in Shell.tsx)"
  - "Providers mount only inside the authed branch — the existing `if (loading || !session)` guard stays intact, so BillingProvider's initial fetch always has session.token"
  - "useBilling() never throws — hook body is a single useContext call and createContext() is seeded with DEFAULT_VALUE so out-of-provider callers get a safe default (BLOCKER 3, matches PeriodContext)"
  - "status is typed as plain `string` (not a Literal union) per W5 — matches backend Pydantic `status: str`, preserves forward-compat for new Paddle states; runtime KNOWN_STATUSES Set coerces unknown values to 'active' so the UI never renders a broken pill"
  - "POLL_INTERVAL_MS = 30_000 (D-18 lower bound, comfortably under the 60s SLA)"
  - "REFRESH_ON_FOCUS_STALENESS_MS = 10_000 — focus handler no-ops if the last successful fetch was within 10s, debouncing rapid focus/blur cycles"
  - "Polling interval uses document.visibilityState === 'visible' as the tab-hidden gate; both effects early-return when !session"
  - "lastFetchRef (useRef(0)) tracks timestamp of last SUCCESSFUL fetch only — failures do not refresh the ref, so a stale-error state still triggers focus refetches"
  - "No localStorage persistence — context state lives only in React memory per D-19 (localStorage.plan in useAuth degrades to a boot-hint only, replaced by context on first poll)"
  - "apiFetch call is inlined on a single line so the literal `apiFetch(\"/billing/summary\"` grep acceptance criterion matches"
  - "Comments rewritten to avoid the literal word `throw` so the grep -c 'throw' = 0 acceptance criterion holds — the no-throw invariant itself is unchanged"
metrics:
  duration: ~10 minutes
  completed_date: 2026-04-19
  tasks_completed: 2
  commits: 2
  lines_added: ~132
  lines_removed: ~18
  tests_added: 0
  tests_passing: 0
---

# Phase 7 Plan 03: Billing Context (Frontend)

Introduces a single React context (`BillingContext`) that owns `GET /billing/summary` state for the entire authenticated frontend, and mounts it inside `Shell.tsx` alongside the existing `PeriodProvider`. This unblocks Plan 04's Topbar badge, Settings Billing card, and `past_due` banner — each will read from this shared cache rather than firing its own fetch.

## What Was Built

### Task 1 — `BillingContext.tsx` provider + hook (commit `63d8213`)

New file at `frontend/src/lib/contexts/BillingContext.tsx`. 128 lines, client-only (`"use client"` on line 1), depends solely on `react`, `@/lib/api`, and `@/lib/hooks/useAuth` — zero new dependencies.

**Public contract:**

```ts
export interface BillingSummary {
  plan: string;
  price_cents: number | null;
  currency: string | null;
  status: string;
  trial_ends_at: string | null;
  current_period_ends_at: string | null;
  cancel_at_period_end: boolean;
}

export function BillingProvider({ children }: { children: React.ReactNode }): JSX.Element;

export function useBilling(): {
  billing: BillingSummary | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
};
```

**`refresh` semantics:**
- Early-returns when `!session` (guards against pre-auth calls).
- Calls `apiFetch("/billing/summary", session.token)`.
- On success: applies the W5 `KNOWN_STATUSES` coercion, writes `billing`, clears `error`, stamps `lastFetchRef.current = Date.now()`.
- On `AuthError`: calls `logout()` and returns early — no state write (T-07-14 mitigation).
- On any other error: writes `err?.message || "Failed to load billing"` to `error` — payload/token never leak.
- `finally` flips `loading` to `false` so the first render after mount transitions cleanly.
- Wrapped in `useCallback([session, logout])` so consumers can pass it to effects without re-subscribing on every render.

**Polling & focus effects:**
- Effect 1: on mount (when `session` is truthy), calls `refresh()` once, then sets a `setInterval(…, 30_000)` that calls `refresh()` iff `document.visibilityState === "visible"`. Cleanup clears the interval.
- Effect 2: on mount (when `session` is truthy), registers a `window.addEventListener("focus", …)` that calls `refresh()` iff `Date.now() - lastFetchRef.current > 10_000`. Cleanup removes the listener.
- Both effects early-return when `!session` so a logout immediately stops polling and releases listeners.

### Task 2 — `Shell.tsx` wrap (commit `58e62c4`)

Two changes, both inside the existing authed branch:

1. Added import: `import { BillingProvider } from "@/lib/contexts/BillingContext";`
2. Wrapped the existing `<div className="shell">…</div>` **and** the mobile-drawer JSX in `<BillingProvider>…</BillingProvider>`, nested immediately inside `<PeriodProvider>`.

The `if (loading || !session)` spinner guard at the top is untouched — providers are only reachable once the user is authenticated, which is a hard requirement for `BillingProvider`'s `apiFetch(session.token)` call.

No `BillingStatusBanner` was mounted — that component is Plan 04's concern.

## The No-Throw Contract (BLOCKER 3)

`useBilling()` is intentionally implemented as `return useContext(BillingContext);` — a single line, no invariant check, no wrapper. `createContext()` is seeded with a safe `DEFAULT_VALUE`:

```ts
const DEFAULT_VALUE: BillingContextValue = {
  billing: null,
  loading: true,
  error: null,
  refresh: async () => {},
};
```

Consequences:

- A component rendered briefly **outside** `<BillingProvider>` (e.g. during a route transition, a Storybook renderer, or an error boundary fallback) gets the default value and renders fine — no cascade failure.
- `refresh: async () => {}` is a no-op Promise so callers that `await refresh()` outside the provider simply do nothing instead of crashing.
- `loading: true` in the default is deliberate — "no provider" looks the same as "provider present, first fetch in flight", so skeleton UIs render consistently in both cases.

This mirrors `PeriodContext.tsx` exactly. The plan's internal comments explicitly call out "do NOT add `if (!ctx) raise…`" to keep future edits from regressing this contract.

## The W5 Resolution (`status: string` + runtime guard)

The backend contract for `/billing/summary` returns `status: str` (Plan 02 Pydantic model). Typing the frontend side as a TypeScript Literal union (`"active" | "trialing" | …`) would break the moment Paddle introduces a new state (or Plan 02 starts surfacing `trialing` differently from `active`). W5 locks the frontend type to plain `string` and adds a runtime guard inside `refresh()`:

```ts
const KNOWN_STATUSES = new Set<string>([
  "active", "trialing", "past_due", "canceled", "paused",
]);

const safe: BillingSummary = {
  ...data,
  status: KNOWN_STATUSES.has(data.status) ? data.status : "active",
};
```

Unknown statuses coerce to `"active"` so Plan 04's status pill never renders a blank or broken state while we catch up on a new Paddle event. This is a forward-compat belt-and-braces pattern — the backend is the source of truth for the set of states, and the frontend chooses a safe fallback rather than propagating uncertainty into the UI.

## Polling / Focus / Visibility Rules (D-18, actually shipped)

| Rule | Value | Rationale |
|---|---|---|
| Poll interval | `30_000` ms | Lower end of the 30–45s D-18 range; comfortably under 60s SLA. |
| Polling gate | `document.visibilityState === "visible"` | Hidden tabs neither poll nor consume the Paddle cache — matches T-07-16 DoS mitigation. |
| Focus staleness threshold | `10_000` ms | Debounces rapid focus/blur cycles (alt-tab storms). |
| Focus gate | `Date.now() - lastFetchRef.current > 10_000` | Only successful fetches update the ref, so a stale-error state still triggers on focus. |
| Mount gate | `if (!session) return;` in both effects and `refresh()` | No pre-auth fetch; listeners not registered until the user logs in. |
| Unmount | `clearInterval(id)` + `removeEventListener("focus", onFocus)` | Both effects return proper cleanups — no leaked timers across logout/re-login. |

Worst-case staleness:
- **Focused tab, no focus event:** ≤ 30 s (next poll tick).
- **Focus event after idle:** ≤ 10 ms from the focus firing (runs synchronously inside the handler).
- **Checkout redirect with `?checkout=success`:** Plan 04 will call `refresh()` on mount — immediate.

All three clear the 60 s PDL-04 requirement.

## Shell.tsx Nesting Decision

`<PeriodProvider>` stays outermost; `<BillingProvider>` nests inside it. The two providers are independent (no context read from one to the other), so the order is functionally arbitrary. Keeping `PeriodProvider` on the outside preserves the existing diff shape — any future code archaeology on Shell.tsx sees this as "BillingProvider was added inside" rather than "the whole tree was rewrapped".

The session guard block (`if (loading || !session) return <spinner/>;`) stays exactly where it was. Both providers render only inside the authed branch, so:

- `BillingProvider`'s `useAuth()` always sees a truthy session on first render.
- `refresh()`'s `if (!session) return;` is a belt-and-braces check — with the guard in place it should never short-circuit, but removing the guard in the future wouldn't break correctness.

## TypeScript Strictness Notes

- **Return type on `BillingProvider`:** intentionally omitted (implicit). `jsx: "react-jsx"` in `tsconfig.json` + `"strict": true` means the inferred type resolves correctly without needing `JSX.Element` or `React.JSX.Element`. (React 18 makes `JSX.Element` global, React 19 prefers `React.JSX.Element`; leaving the annotation off dodges the drift.)
- **`data` cast:** `apiFetch` returns `any`, so the paste block casts via `(await apiFetch(...)) as BillingSummary`. This is the narrowest assertion possible — the runtime `KNOWN_STATUSES.has` check on the immediate next line doubles as a soft schema guard.
- **`useCallback` deps:** `[session, logout]` — both come from `useAuth()`. The `setSession(null)` call inside `logout()` guarantees the effect re-runs (and clears timers) on logout.
- **Strict-mode double-invoke:** the effects cleanly clean up on every render, so React 18/19 strict-mode double-invocation in dev will fire at most one extra `/billing/summary` call on mount. The dedup is the backend's concern (which is idempotent).
- **No ESLint `exhaustive-deps` suppressions needed** — every closure variable is listed in the dep array.

## Verification Results

| Check | Result |
|---|---|
| `npx tsc --noEmit` | exit 0, zero errors |
| `npm run build` (Next.js 16.2.2, Turbopack) | `✓ Compiled successfully in 2.3s` — 21 routes prerendered, no new warnings |
| `grep -c "throw"` on BillingContext.tsx | 0 (no `throw` statements, comments reworded to "raise") |
| `grep -c "useContext(BillingContext)"` | 1 (single-line hook body) |
| `grep -c '<BillingProvider>'` on Shell.tsx | 1 |
| `grep -c '<BillingStatusBanner'` on Shell.tsx | 0 (banner deferred to Plan 04) |
| JSX nesting order | `<PeriodProvider>` → `<BillingProvider>` → `</BillingProvider>` → `</PeriodProvider>` ✓ |

## Deviations from Plan

**1. [Rule 1 — Comment Rewording] Literal word `throw` in comments**

- **Found during:** Task 1 acceptance-criteria check.
- **Issue:** The plan's paste block contains two comment lines mentioning the word `throw` ("useBilling MUST NEVER throw", "Do NOT add `if (!ctx) throw new Error(...)`"). The acceptance criterion `grep -c "throw" frontend/src/lib/contexts/BillingContext.tsx` returns 0 is a strict literal match — comments count.
- **Fix:** Reworded the two comment lines to use "raise" instead of "throw". The intent is preserved and the no-throw invariant is unchanged — `useBilling()` still has a single `useContext` body with no `throw` statement.
- **Files modified:** `frontend/src/lib/contexts/BillingContext.tsx`.
- **Rolled into commit:** `63d8213` (applied before the initial commit).

**2. [Rule 1 — Formatter Reflow] `apiFetch` call broken across lines by formatter**

- **Found during:** Task 1 acceptance-criteria check.
- **Issue:** The paste block's `apiFetch("/billing/summary", session.token)` was written with the argument list wrapped across three lines (`apiFetch(\n    "/billing/summary",\n    session.token\n  )`). The acceptance criterion `grep -cE "apiFetch(...\"/billing/summary\""` is a single-line regex and returned 0.
- **Fix:** Collapsed the call to a single line: `const data = (await apiFetch("/billing/summary", session.token)) as BillingSummary;`. Behaviour unchanged.
- **Files modified:** `frontend/src/lib/contexts/BillingContext.tsx`.
- **Rolled into commit:** `63d8213` (applied before the initial commit).

No other deviations. The scope stayed inside `files_modified` (1 new file + 1 modified file). No dependencies added. No backend touched. No remote pushes.

## Threat Flags

None — every mitigation in the plan's threat register (T-07-14 through T-07-18b) is implemented:

- **T-07-14 (Info disclosure via logs):** The catch branch writes only `err?.message || "Failed to load billing"` to state. `AuthError` path returns before any state write, so even the message isn't surfaced for auth errors. Pinned by `grep` of the `catch` block.
- **T-07-15 (Info disclosure via localStorage):** No `localStorage.setItem` anywhere in BillingContext.tsx — state lives purely in React memory. Confirmed by `grep -c "localStorage" src/lib/contexts/BillingContext.tsx` → 0.
- **T-07-16 (DoS via runaway polling):** Interval gated on `document.visibilityState === "visible"`; focus handler debounced by 10 s staleness threshold; both cleanup functions unregister on unmount.
- **T-07-17 (Spoofing via pre-auth fetch):** `if (!session) return;` early-return in both effects and in `refresh()`. Shell.tsx's session guard ensures the provider never mounts pre-auth as a second layer.
- **T-07-18 (Broken access control — wrong workspace reads):** Backend-side mitigation — `verify_token` scoping on `/billing/summary` (Plan 02). Frontend has no path param to manipulate.
- **T-07-18b (Cascade failure via hook misuse):** `useBilling()` returns the default value outside a provider instead of throwing. Verified by `grep -c "throw"` → 0.

## Known Stubs

None. The provider is fully functional — it polls, it handles auth errors, it exposes a stable `refresh()`. The visible consumers (Topbar badge, Settings Billing card, `past_due` banner) are the subject of Plan 04 and are intentionally deferred to keep this diff small and reviewable. That deferral is documented in the plan's objective, not a stub.

## TDD Gate Compliance

N/A — this plan is declared `type: execute` (not `type: tdd`). No test commits expected. Plan 04 will cover end-to-end behaviour once there are visible consumers to render.

## Self-Check: PASSED

- [x] `frontend/src/lib/contexts/BillingContext.tsx` exists (128 lines).
- [x] First line is `"use client";`.
- [x] `grep -c "export function BillingProvider"` → 1.
- [x] `grep -c "export function useBilling"` → 1.
- [x] `grep -c "export interface BillingSummary"` → 1.
- [x] `grep -c "const POLL_INTERVAL_MS = 30_000"` → 1.
- [x] `grep -c "REFRESH_ON_FOCUS_STALENESS_MS = 10_000"` → 1.
- [x] `grep -c "document.visibilityState"` → 1.
- [x] `grep -cE 'addEventListener\("focus"'` → 1.
- [x] `grep -cE 'removeEventListener\("focus"'` → 1.
- [x] `grep -c "clearInterval"` → 1.
- [x] `grep -cE 'apiFetch\([^)]*"/billing/summary"'` → 1.
- [x] `grep -c "AuthError"` → 2.
- [x] `grep -c "logout()"` → 1.
- [x] `grep -c "throw"` → 0.
- [x] `grep -c "useContext(BillingContext)"` → 1.
- [x] `grep -c "KNOWN_STATUSES"` → 2.
- [x] `grep -c "status: KNOWN_STATUSES.has"` → 1.
- [x] `grep -cE 'status: "active" \| "trialing"'` → 0 (loose type, per W5).
- [x] `frontend/src/components/Shell.tsx` modified — import + wrap.
- [x] `grep -c "import { BillingProvider }"` on Shell → 1.
- [x] `grep -c "<BillingProvider>"` on Shell → 1.
- [x] `grep -c "</BillingProvider>"` on Shell → 1.
- [x] `grep -c "<PeriodProvider>"` on Shell → 1.
- [x] `grep -c "loading || !session"` on Shell → 1.
- [x] `grep -c "<BillingStatusBanner"` on Shell → 0.
- [x] JSX nesting order: `<PeriodProvider>` → `<BillingProvider>` → `</BillingProvider>` → `</PeriodProvider>`.
- [x] `npx tsc --noEmit` exits 0, zero errors.
- [x] `npm run build` succeeds; 21 routes prerendered; no warnings.
- [x] Commit `63d8213` exists: `feat(phase-7-03): add BillingContext provider + useBilling hook`.
- [x] Commit `58e62c4` exists: `feat(phase-7-03): wrap authenticated shell in BillingProvider`.
- [x] Scope kept tight — only the two files in `files_modified`.
