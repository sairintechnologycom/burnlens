---
phase: 10-feature-gating-usage-visibility-ui
verified: 2026-04-27T22:45:00Z
status: human_needed
score: 5/5 must-haves verified
must_haves_total: 5
must_haves_verified: 5
overrides_applied: 0
re_verification: null
requirements_coverage:
  - id: GATE-01
    source_plan: 10-03
    description: "Free-tier workspaces locked out of Teams + Customers with upgrade CTA"
    status: satisfied
    evidence: "frontend/src/app/teams/page.tsx + customers/page.tsx wrap real content in <LockedPanel> on PaymentRequiredError; LockedPanel CTA invokes startCheckout({plan: requiredPlan})"
  - id: GATE-02
    source_plan: 10-03
    description: "Cloud-tier sees Teams locked with Upgrade-to-Teams CTA; Teams-tier unlocked"
    status: satisfied
    evidence: "Backend Phase 9 require_feature middleware emits 402 with required_plan='teams'; frontend forwards locked.required_plan into LockedPanel, which derives planLabel='Teams'. Teams-tier users hit the unlocked branch (no PaymentRequiredError → setLocked never called)"
  - id: GATE-03
    source_plan: 10-03
    description: "Customer attribution requires Teams plan; Free/Cloud see CTA"
    status: satisfied
    evidence: "frontend/src/app/customers/page.tsx wraps CustomersContent in LockedPanel with featureKey='customers_view' fallback; LockedPanel renders dynamic copy from 402 body's required_feature/required_plan"
  - id: METER-01
    source_plan: 10-01, 10-02
    description: "Sidebar usage meter on every dashboard page"
    status: satisfied
    evidence: "frontend/src/components/Sidebar.tsx:142 mounts <UsageMeter /> in aside footer; Sidebar is rendered by Shell which wraps every dashboard page. UsageMeter reads billing.usage.{request_count, monthly_request_cap}"
  - id: METER-02
    source_plan: 10-01, 10-02
    description: "Color thresholds: green <80%, amber 80-100%, red >100%"
    status: satisfied
    evidence: "UsageMeter.tsx:53-54 sets band variable: pct>100 → red, pct>=80 → amber, else green. CSS in globals.css maps usage-meter-fill--{green,amber,red} to var(--cyan), var(--amber), var(--red). 'green' class intentionally uses cyan token per UI-SPEC."
  - id: METER-03
    source_plan: 10-01, 10-04
    description: "Click meter → Settings → Usage with daily breakdown"
    status: satisfied
    evidence: "UsageMeter.tsx wraps content in <Link href='/settings#usage'>; UsageCard.tsx mounts with id='usage' on the .card div; UsageCard fetches /billing/usage/daily and renders VerticalBar with cumulative-threshold coloring"
human_verification:
  - test: "Free-tier user lands on /teams"
    expected: "Frosted-glass TeamsSkeleton visible behind LockedPanel overlay; title 'Team breakdowns requires Teams plan'; CTA 'Upgrade to Teams' opens Paddle checkout overlay (no router hop)"
    why_human: "Visual frosted-glass effect (opacity/blur/grayscale), Paddle overlay launch, focus-on-mount behavior cannot be verified programmatically"
  - test: "Cloud-tier user clicks Create key in API Keys card after creating one key"
    expected: "Create-key button is disabled pre-emptively (no 402 round-trip); cap-banner shows 'Your Cloud plan allows 1 API keys. Upgrade to Teams for more.'; Upgrade button opens Paddle checkout for Teams plan, NOT Cloud"
    why_human: "Pre-emptive at-cap state requires live Paddle subscription + multiple keys created; nextPlanFor derivation only observable in browser"
  - test: "Usage meter color transitions across thresholds"
    expected: "At 79% bar shows cyan/green; at 80% transitions to amber; at 100% transitions to red with overflow percentage label '(120%)' shown; bar width clamps to 100%"
    why_human: "Visual color transitions require seeded usage data + actual rendering; thresholds are coded but visual confirmation needed"
  - test: "Click sidebar usage meter from any dashboard page"
    expected: "Browser navigates to /settings#usage and scrolls/anchors to Usage card; daily bar chart loads with cumulative-color bars from /billing/usage/daily"
    why_human: "Hash-anchor scroll behavior + chart rendering is a runtime browser concern"
  - test: "Create then revoke an API key"
    expected: "Create key shows plaintext modal exactly once; backdrop click and Esc do NOT dismiss; only 'I've saved it' button dismisses; after dismiss plaintext is cleared from React state. Revoke requires typing exact key name (case-sensitive)"
    why_human: "Modal blocking behavior (no Esc/backdrop close), plaintext lifecycle, and typed-name confirm UX require interactive testing"
---

# Phase 10: Feature Gating & Usage Visibility UI — Verification Report

**Phase Goal:** "The dashboard makes it obvious what plan a user is on, what features are locked, and how close they are to their quota — with a clear upgrade path at every friction point."

**Verified:** 2026-04-27T22:45:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| #   | Truth (Success Criterion)                                                                                                                                          | Status     | Evidence                                                                                                                                                                                                                                                                       |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | A Free-tier user sees the Teams and Customers views as locked panels with an inline "Upgrade" CTA; clicking the CTA opens Paddle checkout for the required tier.   | ✓ VERIFIED | teams/page.tsx + customers/page.tsx catch `PaymentRequiredError` and render `<LockedPanel>` with the 402 body. `LockedPanel.handleUpgrade` calls `startCheckout({plan: requiredPlan})` directly — no router hop. CTA label dynamically reads "Upgrade to {planLabel}".          |
| 2   | A Cloud-tier user sees Teams locked with an "Upgrade to Teams" CTA; a Teams-tier user sees it unlocked.                                                            | ✓ VERIFIED | Phase 9 backend middleware emits 402 with `required_plan='teams'` for Cloud users hitting `/api/v1/usage/by-team`. teams/page.tsx forwards `locked.required_plan` to LockedPanel which derives "Teams" label. Teams-tier users do not trip the 402 branch — real data renders.  |
| 3   | Every dashboard page displays a usage meter in the sidebar showing `current month requests / plan limit` with a progress bar.                                      | ✓ VERIFIED | Sidebar.tsx:142 mounts `<UsageMeter />` in aside footer. Sidebar is consumed by Shell which wraps every dashboard page. UsageMeter reads `billing.usage.{request_count, monthly_request_cap}` and renders `usage-meter-bar > usage-meter-fill` plus numeric label.              |
| 4   | The usage meter bar is green below 80%, amber from 80% to 100%, and red above 100% of quota.                                                                       | ✓ VERIFIED | UsageMeter.tsx:53-54: `band = pct > 100 ? "red" : pct >= 80 ? "amber" : "green"`. `widthPct = Math.min(100, pct)` clamps over-quota to 100% width; numeric label appends `({Math.round(pct)}%)` overflow. CSS in globals.css wires the three classes to var(--cyan/amber/red).  |
| 5   | Clicking the usage meter navigates to Settings → Billing → Usage with a daily breakdown of requests for the current cycle.                                         | ✓ VERIFIED | UsageMeter.tsx wraps in `<Link href="/settings#usage">`. UsageCard.tsx mounts with `id="usage"` on the .card div, fetches `/billing/usage/daily`, renders VerticalBar with cumulative-threshold colored bars (cyan/amber/red) — D-19 coloring matches sidebar thresholds.       |

**Score:** 5/5 must-haves verified

### Required Artifacts (Three-Level Verification)

| Artifact                                              | Expected                                                  | Exists | Substantive | Wired | Data Flow | Status     |
| ----------------------------------------------------- | --------------------------------------------------------- | ------ | ----------- | ----- | --------- | ---------- |
| `burnlens_cloud/billing.py` (`/billing/summary` ext)  | Adds usage + available_plans + api_keys subobjects        | ✓      | ✓           | ✓     | ✓         | ✓ VERIFIED |
| `burnlens_cloud/billing.py` (`GET /billing/usage/daily`) | Returns daily group-by-date counts within cycle bounds | ✓      | ✓           | ✓     | ✓         | ✓ VERIFIED |
| `burnlens_cloud/models.py`                            | UsageCurrentCycle, AvailablePlan, ApiKeysSummary, UsageDailyEntry/Response, extended BillingSummary | ✓ | ✓ | ✓ | ✓ | ✓ VERIFIED |
| `burnlens_cloud/database.py`                          | `idx_request_records_workspace_ts` index migration        | ✓      | ✓           | ✓     | n/a       | ✓ VERIFIED |
| `tests/test_billing_usage.py`                         | Pytest coverage incl workspace isolation + 400 contract   | ✓      | ✓ (17 tests)| n/a   | n/a       | ✓ VERIFIED |
| `frontend/src/components/UsageMeter.tsx`              | Sidebar-footer usage meter w/ thresholds + click-to-settings | ✓   | ✓           | ✓     | ✓         | ✓ VERIFIED |
| `frontend/src/components/Sidebar.tsx`                 | lockedForPlan support + lock glyph + UsageMeter mount     | ✓      | ✓           | ✓     | ✓         | ✓ VERIFIED |
| `frontend/src/lib/contexts/BillingContext.tsx`        | Extended BillingSummary type (usage + available_plans + api_keys); 60s visibility-gated poll | ✓ | ✓ | ✓ | ✓ | ✓ VERIFIED |
| `frontend/src/lib/hooks/usePlanSatisfies.ts`          | planSatisfies + nextPlanFor + PLAN_ORDER                  | ✓      | ✓           | ✓     | n/a       | ✓ VERIFIED |
| `frontend/src/components/LockedPanel.tsx`             | Frosted-glass shape-preserving wrapper w/ 402-driven copy | ✓      | ✓           | ✓     | ✓         | ✓ VERIFIED |
| `frontend/src/app/teams/page.tsx`                     | Migrated to LockedPanel pattern w/ TeamsSkeleton           | ✓      | ✓           | ✓     | ✓         | ✓ VERIFIED |
| `frontend/src/app/customers/page.tsx`                 | Migrated to LockedPanel pattern w/ CustomersSkeleton       | ✓      | ✓           | ✓     | ✓         | ✓ VERIFIED |
| `frontend/src/components/UpgradePrompt.tsx`           | DELETED (deprecated)                                       | ✓ deleted | n/a      | n/a   | n/a       | ✓ VERIFIED |
| `frontend/src/components/charts/VerticalBar.tsx`      | Chart.js bar wrapper for daily breakdown                  | ✓      | ✓           | ✓     | ✓         | ✓ VERIFIED |
| `frontend/src/components/UsageCard.tsx`               | Settings Usage card w/ #usage anchor + daily chart        | ✓      | ✓           | ✓     | ✓         | ✓ VERIFIED |
| `frontend/src/components/ApiKeysCard.tsx`             | List/create/revoke + pre-emptive at-cap + nextPlanFor CTA | ✓      | ✓           | ✓     | ✓         | ✓ VERIFIED |
| `frontend/src/components/NewApiKeyModal.tsx`          | Blocking modal, 3-prop signature, plaintext-once           | ✓      | ✓           | ✓     | ✓         | ✓ VERIFIED |
| `frontend/src/app/settings/page.tsx`                  | Mounts UsageCard + ApiKeysCard in stacking order          | ✓      | ✓           | ✓     | ✓         | ✓ VERIFIED |
| `frontend/src/app/globals.css`                        | All Phase 10 CSS classes (usage-meter*, locked-panel*, sidebar-item--locked, api-keys-*) | ✓ | ✓ | ✓ | n/a | ✓ VERIFIED |

### Key Link Verification

| From                                | To                                                    | Via                                | Status   |
| ----------------------------------- | ----------------------------------------------------- | ---------------------------------- | -------- |
| GET /billing/summary handler        | resolve_limits + workspaces + api_keys count          | composed serializer (billing.py:790-803) | ✓ WIRED |
| GET /billing/summary `api_keys`     | api_keys table (workspace_id-scoped, revoked_at IS NULL) + plan_limits.api_key_count | execute_query + ApiKeysSummary | ✓ WIRED |
| GET /billing/usage/daily handler    | request_records GROUP BY date_trunc('day', ts)        | execute_query (billing.py:856-867) | ✓ WIRED |
| BillingContext refresh              | apiFetch("/billing/summary")                          | useEffect on session/visibility    | ✓ WIRED |
| Sidebar.tsx                         | useBilling().billing.usage                            | useBilling() consumed by UsageMeter| ✓ WIRED |
| Sidebar.tsx (LOCKED_NAV map)        | useAuth().session.plan + planSatisfies                | planSatisfies(currentPlan, lockedForPlan) | ✓ WIRED |
| UsageMeter click                    | /settings#usage                                       | Next.js `<Link href="/settings#usage">` | ✓ WIRED |
| LockedPanel CTA onClick             | usePaddleCheckout.startCheckout                       | direct hook invocation `{plan: requiredPlan}` | ✓ WIRED |
| teams/customers page `.catch`       | LockedPanel render                                    | PaymentRequiredError → setLocked   | ✓ WIRED |
| LockedPanel title/body/CTA          | PaymentRequiredError.data + BillingContext.available_plans | props + useBilling() lookup    | ✓ WIRED |
| UsageCard.tsx                       | GET /billing/usage/daily                              | apiFetch within useEffect          | ✓ WIRED |
| ApiKeysCard.tsx                     | GET/POST/DELETE /api-keys                             | apiFetch                           | ✓ WIRED |
| ApiKeysCard.tsx (pre-emptive at-cap)| billing.api_keys.{active_count, limit}                | useBilling() + useMemo derivation  | ✓ WIRED |
| ApiKeysCard.tsx (cap-banner CTA)    | nextPlanFor(billing.plan)                             | fallback when 402 lacks required_plan | ✓ WIRED |
| NewApiKeyModal                      | navigator.clipboard.writeText                         | Copy button click handler          | ✓ WIRED |

### Data-Flow Trace (Level 4)

| Artifact         | Data Variable      | Source                                        | Real Data? | Status      |
| ---------------- | ------------------ | --------------------------------------------- | ---------- | ----------- |
| UsageMeter       | `billing.usage`    | BillingContext refresh → /billing/summary → backend reads workspaces + workspace_usage_cycles | Yes — backend pulls from real Postgres tables (billing.py:759-771) | ✓ FLOWING |
| UsageCard        | `data` (daily)     | apiFetch /billing/usage/daily → backend reads request_records GROUP BY date | Yes — real DB query w/ workspace isolation (billing.py:856-867) | ✓ FLOWING |
| LockedPanel      | `billing.available_plans` | BillingContext → /billing/summary → _build_available_plans() reads plan_limits | Yes — real query, hardcoded price_cents (constants until v1.2 column) | ✓ FLOWING |
| Sidebar lock     | `currentPlan`      | useBilling().billing.plan ?? useAuth().session.plan ?? "free" | Yes — fallback chain ensures non-null | ✓ FLOWING |
| ApiKeysCard rows | `keys`             | apiFetch /api-keys → Phase 9 endpoint reads api_keys table | Yes — Phase 9 endpoint live | ✓ FLOWING |
| ApiKeysCard cap  | `billing.api_keys` | BillingContext → /billing/summary → COUNT(*) FROM api_keys | Yes — workspace-scoped count (billing.py:779-788) | ✓ FLOWING |

### Behavioral Spot-Checks

Spot-checks SKIPPED — Phase 10 ships frontend code requiring a running Next.js dev server + Paddle sandbox session + seeded multi-tier workspace data. None of these are runnable in a one-shot pytest/curl context. Backend endpoints have full pytest coverage (17 tests in `tests/test_billing_usage.py`) which the verifier treats as the substitute for behavioral checks at this layer.

### Requirements Coverage

| Requirement | Source Plan(s) | Description                                                                | Status      | Evidence                                                                 |
| ----------- | -------------- | -------------------------------------------------------------------------- | ----------- | ------------------------------------------------------------------------ |
| GATE-01     | 10-03          | Free-tier locked from Teams + Customers w/ upgrade CTA                     | ✓ SATISFIED | teams/page.tsx + customers/page.tsx wrap real content in LockedPanel; CTA invokes Paddle checkout |
| GATE-02     | 10-03          | Cloud → Teams locked w/ Upgrade-to-Teams CTA; Teams unlocked               | ✓ SATISFIED | Phase 9 middleware emits 402; LockedPanel renders dynamic plan label    |
| GATE-03     | 10-03          | Customer attribution requires Teams plan                                   | ✓ SATISFIED | customers/page.tsx defaults featureKey='customers_view' requiredPlan='teams' |
| METER-01    | 10-01, 10-02   | Sidebar meter on every dashboard page                                      | ✓ SATISFIED | Sidebar mounts UsageMeter; Shell wraps every dashboard route             |
| METER-02    | 10-01, 10-02   | Color thresholds green<80, amber 80-100, red>100                           | ✓ SATISFIED | UsageMeter.tsx band derivation + globals.css class wiring                |
| METER-03    | 10-01, 10-04   | Click meter → Settings Usage drill-down                                    | ✓ SATISFIED | UsageMeter Link href=/settings#usage; UsageCard with id='usage' + daily chart |

**No orphaned requirements.** All six requirement IDs (GATE-01..03, METER-01..03) declared in plan frontmatter are mapped to phase 10 in REQUIREMENTS.md and have evidence in the codebase.

### IN-06 Contract Mismatch — Re-Verified Post-Fix

The code review (`10-REVIEW.md` §IN-06) flagged a latent functional bug: the frontend `BillingSummary.usage` type previously wrapped fields in a `current_cycle` subobject while the backend (`burnlens_cloud/billing.py:766-771`) returns them flat on `usage`. This was fixed in commit `a635944`.

**Re-verification:**
- `grep -rn "current_cycle" frontend/src/` — **0 matches** (wrapper completely removed from frontend)
- `BillingContext.tsx:24-29` — `interface UsageCurrentCycle { start; end; request_count; monthly_request_cap; }` matches backend `UsageCurrentCycle` Pydantic model verbatim
- `BillingContext.tsx:54` — `usage?: UsageCurrentCycle | null` (no nesting)
- `UsageMeter.tsx:26` — `const cycle = billing?.usage ?? null;` (reads flat `usage`)
- `UsageMeter.tsx:49-50` — `cycle.request_count` and `cycle.monthly_request_cap` (no `.current_cycle.` deref)
- `UsageCard.tsx:86,88` — `billing?.usage?.request_count` / `billing?.usage?.monthly_request_cap` (consistent flat access)
- Backend `billing.py:766-771` — `UsageCurrentCycle(start=..., end=..., request_count=..., monthly_request_cap=...)` — confirmed flat shape

**Status:** Frontend now matches backend wire shape. Sidebar usage meter will exit loading state once /billing/summary returns. ✓ FIXED

### Anti-Patterns Found

| File                                  | Line   | Pattern                                                              | Severity | Impact                                                                       |
| ------------------------------------- | ------ | -------------------------------------------------------------------- | -------- | ---------------------------------------------------------------------------- |
| `frontend/src/app/settings/page.tsx`  | 65     | `localStorage.setItem("burnlens_api_key", data.api_key)` (legacy regenerate flow) | ⚠️ Warning | WR-01 — pre-existing leak in legacy regenerate flow, NOT introduced by Phase 10. Sits next to new ApiKeysCard which forbids this pattern. |
| `frontend/src/lib/contexts/BillingContext.tsx` | 167 | `setBilling: applyBilling` exposed under misleading name             | ℹ️ Info  | WR-02 — coercion side-effect not visible from type signature                 |
| `frontend/src/app/settings/page.tsx`  | 292-299, 310, 364, 382 | `scheduleRefresh()` cleanup return value discarded     | ⚠️ Warning | WR-03 — timers fire on unmounted parent if user navigates during 3s/10s window |
| `frontend/src/components/NewApiKeyModal.tsx` | 45 | `setTimeout` not cleared on unmount                              | ⚠️ Warning | WR-04 — React state-on-unmounted warning if user dismisses modal mid-copy-feedback |

All warnings are non-blocking quality items. None gate the phase goal. WR-01 (legacy localStorage write) is pre-existing and recommended to track as Phase 11 follow-up. WR-02..WR-04 are quality improvements — see `10-REVIEW.md` for detailed fix recipes.

### Human Verification Required

5 items requiring interactive testing:

1. **Free-tier user lands on /teams** — frosted-glass overlay, dynamic copy, Paddle checkout overlay launch
2. **Cloud-tier user creates first API key** — pre-emptive at-cap on second-key attempt, nextPlanFor-derived "Upgrade to Teams" CTA
3. **Usage meter color transitions** — visual confirmation of green→amber→red threshold transitions, over-quota label
4. **Sidebar meter click navigation** — hash anchor scroll to #usage, daily chart load
5. **API key create/revoke flow** — blocking modal contract (no Esc/backdrop close), plaintext-once lifecycle, typed-name confirm

### Gaps Summary

No gaps. All 5 ROADMAP success criteria are met by the codebase, all 6 requirement IDs are accounted for, and all 18 expected artifacts exist with substantive implementations and proper wiring. The IN-06 contract mismatch flagged in code review has been verified fixed post-commit `a635944`.

The phase status is `human_needed` (not `passed`) because 5 outcomes — visual/interactive frosted-glass behavior, Paddle checkout launch, color threshold transitions, hash-anchor navigation, and modal blocking semantics — cannot be verified programmatically without a running Next.js + Paddle sandbox session. Automated verification (artifact existence, type alignment, key-link wiring, data-flow tracing, anti-pattern scan, requirements coverage) is complete and clean.

---

_Verified: 2026-04-27T22:45:00Z_
_Verifier: Claude (gsd-verifier)_
