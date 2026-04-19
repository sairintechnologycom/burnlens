# Phase 8: Billing Self-Service - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-19
**Phase:** 08-billing-self-service
**Areas discussed:** Checkout surface & plan switcher · Downgrade mechanics · Cancel flow UX · Reactivate flow · Invoice history · Post-action refresh & race handling · Teams plan eligibility · Error & failure paths

**User global overlay:** "will follow your recommendation, ensure we dont compromise on user experience and security" — applied to every Claude's-Discretion tiebreaker.

---

## Area 1 — Checkout surface & plan switcher

### Q1a — Upgrade entry point
| Option | Description | Selected |
|--------|-------------|----------|
| Settings Billing card only | Intentional navigation; minimal clutter | ✓ |
| Settings + Topbar plan badge CTA | Always visible; nudges conversion | |
| Settings + dedicated /plans route | Full tier comparison page | |

**User's choice:** Recommended (a).

### Q1b — Checkout widget
| Option | Description | Selected |
|--------|-------------|----------|
| Paddle.js overlay + hosted-URL fallback | Reuses UpgradePrompt.tsx; validated pattern | ✓ |
| Always redirect to Paddle hosted page | No Paddle.js dep; worse UX (leaves app) | |
| Paddle inline-checkout embed | Most control; most to build | |

**User's choice:** Recommended (a).

### Q1c — Plan picker
| Option | Description | Selected |
|--------|-------------|----------|
| Single-step to Cloud | Teams as separate CTA; 80% path | ✓ |
| Two-tier picker (Cloud / Teams) modal | Small modal before checkout | |
| Full side-by-side comparison modal | Marketing-style with feature bullets | |

**User's choice:** Recommended (a).

---

## Area 2 — Downgrade mechanics

### Q2a — Cloud → Teams upgrade proration
| Option | Description | Selected |
|--------|-------------|----------|
| prorated_immediately | Pays prorated diff now, plan switches instantly | ✓ |
| do_not_bill | Switches instantly, no charge until renewal | |
| prorated_next_billing_period | Switch queued to renewal | |

**User's choice:** Recommended (a).

### Q2b — Teams → Cloud downgrade proration
| Option | Description | Selected |
|--------|-------------|----------|
| Scheduled at period end | Keep Teams through paid period; no refund | ✓ |
| Prorate immediately with credit | Paddle issues credit balance | |
| Cash refund for unused days | Most generous, most ops overhead | |

**User's choice:** Recommended (a).

### Q2c — Cloud → Free treatment
| Option | Description | Selected |
|--------|-------------|----------|
| Reuses Cancel flow | Paddle has no $0 plan object | ✓ |
| Separate "Switch to Free" path | Complicates the model | |

**User's choice:** Recommended (a).

### Q2d — Endpoint shape
| Option | Description | Selected |
|--------|-------------|----------|
| New POST /billing/change-plan | Server-side price_id lookup, auditable | ✓ |
| Route via Paddle customer portal | Zero code, less UX control | |

**User's choice:** Recommended (a).

---

## Area 3 — Cancel flow UX

### Q3a — Cancel confirmation surface
| Option | Description | Selected |
|--------|-------------|----------|
| Custom in-app modal with effective-end-date | We control copy; one less redirect | ✓ |
| Punt to Paddle portal cancel page | Zero code; user leaves app | |

**User's choice:** Recommended (a).

### Q3b — Retention offer
| Option | Description | Selected |
|--------|-------------|----------|
| None in v1.1 | Straight confirmation; add later from data | ✓ |
| 20% off for 3 months | Requires Paddle discount code setup | |
| Pause subscription (1-month hold) | Contradicts Phase 7 D-23 paused=canceled | |

**User's choice:** Recommended (a).

### Q3c — Cancel-reason capture
| Option | Description | Selected |
|--------|-------------|----------|
| Optional radio + optional free-text | Cheap feedback, non-blocking, skippable | ✓ |
| No reason capture | Just confirm | |
| Required reason selector | Friction, may feel coercive | |

**User's choice:** Recommended (a).

### Q3d — Endpoint shape
| Option | Description | Selected |
|--------|-------------|----------|
| New POST /billing/cancel (effective_from=next_billing_period) | Mirrors change-plan pattern | ✓ |
| Route via Paddle customer portal | Zero code, loses in-app UX | |

**User's choice:** Recommended (a).

---

## Area 4 — Reactivate flow

### Q4a — Reactivate UI placement
| Option | Description | Selected |
|--------|-------------|----------|
| In-place Resume button + amber inline message | Single card state flip | ✓ |
| Separate Canceled state view | Own panel, more surface | |
| Top-of-app banner | Noisy | |

**User's choice:** Recommended (a).

### Q4b — Reactivate endpoint
| Option | Description | Selected |
|--------|-------------|----------|
| New POST /billing/reactivate | Idempotent, auditable | ✓ |
| Route via Paddle customer portal | Leaves app | |

**User's choice:** Recommended (a).

### Q4c — Success UX
| Option | Description | Selected |
|--------|-------------|----------|
| Optimistic + toast + background poll | Instant feedback, webhook reconciles | ✓ |
| Wait for webhook before UI change | Correct but laggy (up to 30s) | |
| Full page reload | Heavy, breaks flow | |

**User's choice:** Recommended (a).

### Q4d — Already-ended period handling
| Option | Description | Selected |
|--------|-------------|----------|
| Hide Resume — force re-checkout | Paddle can't reactivate ended sub | ✓ |
| Secretly trigger new checkout | Button label would lie | |

**User's choice:** Recommended (a).

---

## Area 5 — Invoice history

### Q5a — Where invoices render
| Option | Description | Selected |
|--------|-------------|----------|
| New Invoices card in Settings → Billing | In-product, consistent | ✓ |
| Link to Paddle portal | Zero code, leaves app | |
| Dedicated /settings/billing/invoices route | Own page | |

**User's choice:** Recommended (a).

### Q5b — Backend shape
| Option | Description | Selected |
|--------|-------------|----------|
| GET /billing/invoices proxies Paddle | Server-side auth boundary | ✓ |
| Webhook-cached in Postgres | Faster; needs new event subscription | |
| Client-direct to Paddle | Crosses trust boundary | |

**User's choice:** Recommended (a).

### Q5c — Row count & columns
| Option | Description | Selected |
|--------|-------------|----------|
| Last 24, Date/Amount/Status/PDF | 2 years of monthly billing | ✓ |
| Infinite scroll | Overkill for v1.1 | |
| Last 12 only | Too short for annual look-back | |

**User's choice:** Recommended (a).

### Q5d — PDF download
| Option | Description | Selected |
|--------|-------------|----------|
| Paddle signed URLs opened in new tab | No proxying, Paddle hosts PDFs | ✓ |
| Proxy PDF bytes through Railway | Stable URL, bandwidth + risk | |

**User's choice:** Recommended (a).

---

## Area 6 — Post-action refresh & race handling

### Q6a — Post-mutation UI strategy
| Option | Description | Selected |
|--------|-------------|----------|
| Optimistic + toast + refresh at 0s/3s/10s | Instant feel, <10s consistency | ✓ |
| Block with spinner until /summary confirms | Correct but up to 30s wait | |
| Fire-and-forget, wait for next poll | Feels broken | |

**User's choice:** Recommended (a).

### Q6b — Webhook-vs-UI race safeguard
| Option | Description | Selected |
|--------|-------------|----------|
| Mutation endpoint writes expected state immediately after Paddle 2xx | Kills race at source | ✓ |
| Webhook-as-only-writer | Simpler, laggier | |

**User's choice:** Recommended (a).

### Q6c — Mutation response payload
| Option | Description | Selected |
|--------|-------------|----------|
| Return fresh BillingSummary | One round-trip | ✓ |
| Return 200, client re-fetches | Extra round-trip | |

**User's choice:** Recommended (a).

### Q6d — Error rollback
| Option | Description | Selected |
|--------|-------------|----------|
| Gate optimistic flip on 2xx — no rollback path | No inconsistent state | ✓ |
| Flip optimistically, roll back on error | More surface area for bugs | |

**User's choice:** Recommended (a).

---

## Area 7 — Teams plan eligibility

### Q7a — Teams upgrade path
| Option | Description | Selected |
|--------|-------------|----------|
| Self-serve checkout | Product is priced and live | ✓ |
| "Contact sales" CTA | Adds manual ops, slows growth | |
| Invite-only | Contradicts ROADMAP scope | |

**User's choice:** Recommended (a).

### Q7b — Surface strategy
| Option | Description | Selected |
|--------|-------------|----------|
| Cloud primary; "or Teams $99" link → modal; separate button on Cloud | Cloud stays 80%; Teams one-click | ✓ |
| Side-by-side on Free | Choice paralysis | |
| Only reachable via /pricing | Harder to find | |

**User's choice:** Recommended (a).

### Q7c — Plan-picker modal content
| Option | Description | Selected |
|--------|-------------|----------|
| Minimal table pulled from plan_limits | Single source of truth | ✓ |
| Marketing-style comparison | Drift risk | |

**User's choice:** Recommended (a).

---

## Area 8 — Error & failure paths

### Q8a — Overlay closed without completing
| Option | Description | Selected |
|--------|-------------|----------|
| Silent return | Not an error | ✓ |
| Toast "Checkout canceled" | Mildly accusatory | |
| Survey "we'd love to know why" | Hostile | |

**User's choice:** Recommended (a).

### Q8b — Paddle 5xx / timeout on mutation
| Option | Description | Selected |
|--------|-------------|----------|
| 502 + toast + server log | Honest, actionable, traceable | ✓ |
| Silent retry 3x server-side | Risks double-mutation | |
| Generic "Something went wrong" | Unhelpful | |

**User's choice:** Recommended (a).

### Q8c — In-checkout payment decline
| Option | Description | Selected |
|--------|-------------|----------|
| Paddle owns the error UX | We don't have a reliable signal | ✓ |
| Our own decline modal | Paddle doesn't emit this reliably | |

**User's choice:** Recommended (a).

### Q8d — Invoice list fetch failure
| Option | Description | Selected |
|--------|-------------|----------|
| Inline error + Retry in Invoices card | Isolated failure domain | ✓ |
| Hide the entire card | User wonders where it went | |

**User's choice:** Recommended (a).

### Q8e — Double-submit protection
| Option | Description | Selected |
|--------|-------------|----------|
| Client disable + server idempotency | Defense in depth | ✓ |
| Client-side disable only | Breaks on refresh mid-request | |
| API gateway rate-limit | Overkill | |

**User's choice:** Recommended (a).

---

## Claude's Discretion

- Exact toast copy wording (within confirmed patterns).
- Modal primitive choice (new ConfirmModal vs. inline overlay).
- `cancellation_surveys` additional columns beyond minimum (no PII).
- Paddle cursor pagination vs single `per_page=24` fetch for invoices.
- Button ordering within Billing card when multiple affordances coexist.
- Whether Paddle.Checkout close callback reliably distinguishes success vs abandon.
- Structure of `/change-plan` handler (single vs helper-split).

## Deferred Ideas

- Retention offers (discount codes / pause) — v1.2 if churn data warrants.
- Required cancel-reason — keep optional; revisit if response rate too low.
- Webhook-cached invoice table — premature; Paddle API fast enough.
- PDF byte proxying through Railway — unnecessary overhead.
- `/settings/billing/plans` dedicated route — single card is enough.
- Side-by-side full plan comparison page — modal is enough.
- "Contact sales" Teams path — Teams is self-serve in v1.1.
- In-checkout decline capture — Paddle signal unreliable.
- Extra Topbar upgrade CTA — existing badge is enough.
- Dedicated mobile cancel flow — responsive default suffices.
- Multi-year / annual prepay — future pricing phase.
- Per-seat Teams pricing — flat $99/mo in v1.1.
- Cancellation survey analytics dashboard — later.
