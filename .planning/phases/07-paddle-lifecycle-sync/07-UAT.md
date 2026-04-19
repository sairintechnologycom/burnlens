---
status: complete
phase: 07-paddle-lifecycle-sync
source:
  - 07-01-SUMMARY.md
  - 07-02-SUMMARY.md
  - 07-03-SUMMARY.md
  - 07-04-SUMMARY.md
started: 2026-04-19T06:32:51Z
updated: 2026-04-19T06:42:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Cold Start Smoke Test
expected: Backend boots from scratch, init_db() runs idempotent DDL, new schema is present, and GET /billing/summary returns 200 for an authed workspace.
result: pass

### 2. Webhook Rejects Invalid Signature (HTTP 401)
expected: POST /paddle/webhook without a Paddle-Signature header returns 401 "Missing signature". Malformed, stale, or wrong-HMAC headers also return 401 (never 400). Only malformed-envelope errors (bad JSON, missing event_id after signature passes) return 400.
result: pass

### 3. GET /billing/summary Shape + Auth
expected: GET /billing/summary with a valid JWT returns 200 and a JSON body containing plan, price_cents, currency, status, trial_ends_at, current_period_ends_at, cancel_at_period_end. Without Authorization header returns 401. Scope is caller's workspace only — another workspace's data never leaks.
result: pass

### 4. Topbar Plan Pill Reflects Current Plan
expected: On any authed route the Topbar plan pill reads the workspace's current plan. For Free workspaces it reads "Free · Upgrade"; for paid plans it reads the plan name ("Cloud" / "Teams"). The pill links to /settings#billing. First render falls back to session.plan so the pill never flashes blank.
result: pass

### 5. Settings Billing Card — Ready State
expected: /settings shows a "Billing" card at the top. Row 1: "<Plan> · <Price>" (e.g. "Cloud · $29/mo" or "Free · $0") on the left plus a status pill on the right (● Active / Trialing / Past due). Row 2 (paid only): "Next billing: <Month D, YYYY>" in muted text, or "Trial ends: <Month D, YYYY>" in amber when trialing; Free hides Row 2.
result: pass

### 6. Disabled Billing CTAs With Phase-8 Tooltips
expected: Billing card's bottom row renders a disabled CTA — "Manage billing →" for paid workspaces, "Upgrade to Cloud" for Free. Both are keyboard-inert (disabled + aria-disabled="true") with tooltips reading "Coming soon — self-serve billing ships in Phase 8" (paid) or "Coming soon — checkout ships in Phase 8" (free).
result: pass

### 7. past_due Amber Banner Appears Globally
expected: When a workspace has subscription_status='past_due', an amber 40px banner appears below the Topbar on every authed route (/dashboard, /models, /teams, /customers, /alerts, /settings) reading "Payment failed — update billing" with "update billing" as a link to /settings#billing. Banner disappears when status leaves past_due. role="status" + aria-live="polite" are set.
result: pass

### 8. ?checkout=success Refresh Handoff
expected: Visit /settings?checkout=success. The Billing card refetches /billing/summary immediately on mount, and the "checkout=success" query param is stripped from the URL (becomes /settings) without a full page reload.
result: pass

### 9. Loading / Error Variants Render Cleanly
expected: On first mount before /billing/summary resolves, the Billing card shows skeleton placeholders (plan-price shimmer + status-pill shimmer + one muted line + disabled CTA). If the fetch fails, the card shows "Billing info unavailable" in muted text plus a cyan "Retry" text-button that calls refresh().
result: pass

## Summary

total: 9
passed: 9
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none yet]
