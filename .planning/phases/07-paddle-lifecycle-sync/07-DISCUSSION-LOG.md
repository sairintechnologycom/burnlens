# Phase 7: Paddle Lifecycle Sync - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-19
**Phase:** 07-paddle-lifecycle-sync
**Areas discussed:** Events + state schema, Settings → Billing read view, UI freshness, past_due / trial edge cases

---

## Gray Area Selection

| Option | Description | Selected |
|--------|-------------|----------|
| Events + state schema | Paddle event mapping, new workspaces columns, idempotency/audit log | ✓ |
| Settings → Billing read view | Layout, free-user UX, Phase 8 scaffolding | ✓ |
| UI freshness (<60s) | Polling vs focus vs push; client state location; post-checkout refresh | ✓ |
| past_due / trial edge cases | past_due access, trial-expiry transition, paused behavior | ✓ |

**User's choice:** All four selected.

---

## Events + State Schema

### Q1: Paddle event reconciliation

| Option | Description | Selected |
|--------|-------------|----------|
| Match live config | Keep activated/updated/canceled/paused + payment_failed. Update success-criteria wording. | ✓ |
| Extend Paddle subscription | Add subscription.created + transaction.completed to Paddle notification setting. | |
| Activated + transaction.completed only | Keep activated but add transaction.completed for past_due → active. | |

**User's choice:** Match live config (Recommended).

### Q2: New workspaces columns (multi-select)

| Option | Description | Selected |
|--------|-------------|----------|
| trial_ends_at timestamptz | For BILL-02 trial expiry display | ✓ (Claude discretion) |
| current_period_ends_at timestamptz | For BILL-02 next billing display | ✓ (Claude discretion) |
| cancel_at_period_end boolean | For Phase 8 reactivate flow | ✓ (Claude discretion) |
| price_cents + currency | Cache for Settings display without Paddle round-trip | ✓ (Claude discretion) |

**User's choice:** "You decide as required if required all these."
**Notes:** Interpreted as Claude's discretion to include all four — each maps to a stated success criterion or a cheap-now/useful-later cost.

### Q3: Webhook idempotency / audit

| Option | Description | Selected |
|--------|-------------|----------|
| Event log + dedup by event_id | paddle_events(event_id PK, type, payload jsonb, processed_at, error) | ✓ |
| Dedup only, no payload | paddle_event_ids(event_id PK, received_at) | |
| No dedup | Trust at-least-once + UPDATE-where handlers | |

**User's choice:** Event log + dedup by event_id (Recommended).

---

## Settings → Billing Read View

### Q1: Paid-user layout

| Option | Description | Selected |
|--------|-------------|----------|
| Compact summary card | Plan+price+status, next billing, disabled Manage button | ✓ |
| Multi-row detail layout | Label/value rows for each field | |
| Summary + limits preview | Compact + bulleted plan limits | |

**User's choice:** Compact summary card (Recommended).

### Q2: Free-user experience

| Option | Description | Selected |
|--------|-------------|----------|
| Same panel, 'Free' + upgrade CTA | Free · $0 with Upgrade to Cloud CTA | ✓ |
| Minimal 'You are on Free' blurb | Short sentence + button | |
| Hide panel entirely | No Billing panel for free users | |

**User's choice:** Same panel, 'Free' + upgrade CTA (Recommended).

### Q3: Phase 8 scaffolding

| Option | Description | Selected |
|--------|-------------|----------|
| Read-only + single disabled button | One 'Manage billing' stub, tooltip 'Coming soon' | ✓ |
| No buttons at all | Pure read-only | |
| Wire to /billing/portal now | Early self-service via existing /portal endpoint | |

**User's choice:** Read-only + single disabled button (Recommended).

---

## UI Freshness (<60s rule)

### Q1: Refresh mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Light polling of /billing/summary | 30–45s interval + on focus | ✓ |
| Focus + manual refresh only | No interval — fails 60s if tab stays focused | |
| SSE or WebSocket push | Real-time but adds infra surface | |

**User's choice:** Light polling of /billing/summary (Recommended).

### Q2: Client state source

| Option | Description | Selected |
|--------|-------------|----------|
| Fetch /billing/summary, cache in React | React context/query as single source; localStorage is boot hint only | ✓ |
| Keep localStorage, overlay /billing/summary on Settings | Two code paths, two stale risks | |
| Patch session object on poll | Write plan back to localStorage each poll | |

**User's choice:** Fetch /billing/summary, cache in React (Recommended).

### Q3: Post-checkout refresh (Phase 8 prep)

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — invalidate on ?checkout=success | Phase 7 ships the trigger; Phase 8 just navigates with the param | ✓ |
| No — rely on polling only | Up to 30–45s stale after checkout | |

**User's choice:** Yes — invalidate on ?checkout=success (Recommended).

---

## past_due / Trial Edge Cases

### Q1: past_due access policy

| Option | Description | Selected |
|--------|-------------|----------|
| Keep full access, show banner | Plan unchanged, status='past_due', amber banner | ✓ |
| Downgrade to free immediately | Hard flip mid-session | |
| Keep access silently, no banner | Flip internal status, no UI signal | |

**User's choice:** Keep full access, show banner (Recommended).

### Q2: Trial expiry without payment method

| Option | Description | Selected |
|--------|-------------|----------|
| Downgrade to Free, show re-upgrade CTA | subscription.canceled → plan='free', upgrade pill | ✓ |
| Keep at Cloud with status=canceled | Defer to future quota enforcement | |

**User's choice:** Downgrade to Free, show re-upgrade CTA (Recommended).

### Q3: subscription.paused behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Same as canceled | Downgrade to free, status='paused' | ✓ |
| Keep plan, status='paused', banner | Treat as temporary hold | |

**User's choice:** Same as canceled (Recommended).

---

## Claude's Discretion

- Specific choice of all four new workspaces columns (trial_ends_at, current_period_ends_at, cancel_at_period_end, price_cents+currency) — user said "you decide as required".
- Banner component location, exact poll interval (30–45s), jsonb index necessity, dedup-race error surfacing, `?checkout=success` listener mount location.

## Deferred Ideas

- Subscribing to subscription.created / transaction.completed events.
- Paused-as-temporary-hold (keep access with banner).
- Dedicated subscription.trialing handler.
- Edge cache for /billing/summary.
- SSE/WebSocket push channel.
- Revenue/billing metrics dashboard over paddle_events.
- Checkout / cancel / reactivate / invoice history UI (Phase 8).
- Usage meter / feature gating UI (Phase 10).
