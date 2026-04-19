# Phase 8: Billing Self-Service - Context

**Gathered:** 2026-04-19
**Status:** Ready for planning

<domain>
## Phase Boundary

User can complete the full upgrade / downgrade / cancel / reactivate / invoice-history loop from inside the app — no emailing support, no leaving the product. Settings → Billing is the single surface.

**In scope:** Paddle-overlay checkout wired to the Settings card (Cloud + Teams), mid-cycle plan switching (upgrade prorated immediately, downgrade scheduled at period end), in-app cancel-at-period-end with optional reason capture, in-place reactivate before period end, server-proxied invoice history with Paddle-hosted PDF downloads, optimistic UI + webhook reconciliation.

**Out of scope (Phase 9/10):** quota enforcement, plan-gated feature locks, usage meter, 80/100% quota emails — all orthogonal to self-service billing.

**Non-negotiable overlay (user direction):** no compromise on user experience or security. Every decision below was filtered through this lens.

</domain>

<decisions>
## Implementation Decisions

### Checkout Surface & Plan Switcher
- **D-01:** Primary upgrade CTA lives only in Settings → Billing card. No Topbar CTA button, no dedicated `/plans` route. The Topbar plan badge stays informational (Phase 7 behavior).
- **D-02:** Checkout uses the `@paddle/paddle-js` overlay. Reuse the pattern already validated in `frontend/src/components/UpgradePrompt.tsx` — call `/billing/checkout`, open `Paddle.Checkout.open({ transactionId })`, fall back to `window.location.href = data.url` if Paddle.js failed to initialize.
- **D-03:** Free → Cloud is a single-click primary path. Teams is discoverable but not on the default upgrade trajectory (see D-25).

### Plan-Change Mechanics (upgrade / downgrade between paid plans)
- **D-04:** Cloud → Teams upgrade uses Paddle `PATCH /subscriptions/{id}` with `proration_billing_mode: "prorated_immediately"`. User pays the prorated difference now, plan switches instantly. Matches the "I paid more, I get more now" expectation.
- **D-05:** Teams → Cloud downgrade uses Paddle `PATCH /subscriptions/{id}` with the plan change scheduled at period end (`effective_from: "next_billing_period"`). User keeps their current paid plan through the remainder of the paid period; no proration, no refund. Standard SaaS posture.
- **D-06:** Cloud → Free is a cancel, **not** a plan change. Paddle has no $0 plan object; "downgrade to Free" MUST route through the cancel flow (Area 3 below). UI language must call it "Cancel subscription" not "Downgrade to Free."
- **D-07:** New endpoint `POST /billing/change-plan {target_plan}` in `burnlens_cloud/billing.py`. Server-side price_id lookup via `_plan_to_price_id` — never trust a client-supplied price_id. Endpoint chooses the proration mode per D-04/D-05 based on plan_limits tier ordering (tier_of(target) > tier_of(current) → immediate; tier_of(target) < tier_of(current) → at period end).

### Cancel Flow UX
- **D-08:** Custom in-app confirm modal. Pulls effective-end-date from the existing `workspaces.current_period_ends_at` (populated by Phase 7 webhooks). Body copy: "You'll keep {plan_label} until {formatted_date}. After that, your workspace will switch to the Free plan." Single "Confirm cancel" button + "Keep subscription" secondary.
- **D-09:** No retention offer (discount / pause) in v1.1. Revisit in v1.2 once there is actual churn data to justify the UX + Paddle-config complexity.
- **D-10:** Optional cancel-reason capture. Radio group: "Too expensive / Missing a feature / Switching tools / Not using it enough / Other" + optional free-text. Non-blocking on cancel — the Confirm button is always enabled. Stored in a new Postgres table `cancellation_surveys (id uuid PK, workspace_id uuid FK, reason_code text NULL, reason_text text NULL, created_at timestamptz NOT NULL DEFAULT now())`. Write is best-effort; cancel never blocks on survey-write failure.
- **D-11:** New endpoint `POST /billing/cancel` calls Paddle `POST /subscriptions/{id}/cancel` with `effective_from: "next_billing_period"`. On 2xx Paddle response: write `cancel_at_period_end=true`, `subscription_status='active'` (still active until period end) to our `workspaces` row (D-20 overlay), insert the survey row if present. Webhook `subscription.canceled` (or `subscription.updated` with `scheduled_change`) reconciles.

### Reactivate Flow
- **D-12:** In-place UI flip on the Billing card. When `cancel_at_period_end=true` AND `current_period_ends_at > now()`: the "Cancel" button is replaced with a **green** "Resume subscription" button, and an **amber** inline message renders above the buttons: "Canceled — ends {date}. Resume to keep access." No banner, no separate view.
- **D-13:** New endpoint `POST /billing/reactivate` calls Paddle to clear the scheduled cancel on the subscription (Paddle `PATCH /subscriptions/{id}` removing `scheduled_change` / equivalent). Idempotent: if the subscription is already not-scheduled-for-cancel, return 200 with current summary, no Paddle call.
- **D-14:** Optimistic UX: on 2xx, flip local `cancel_at_period_end → false`, show toast "Subscription resumed", then run the D-21 refresh cadence.
- **D-15:** If the period has already ended (subscription fully canceled at Paddle), Resume is hidden entirely. User must re-checkout via the D-01/D-02 Upgrade flow. Rationale: Paddle does not reactivate an ended subscription; a button labelled "Resume" that secretly does fresh checkout would lie to the user.

### Invoice History
- **D-16:** New "Invoices" card in Settings → Billing, positioned below the plan card. Paid workspaces with no transactions yet see the empty state; Free workspaces without a `paddle_customer_id` still see the card but with the same empty state (no special-casing).
- **D-17:** New endpoint `GET /billing/invoices` server-proxies Paddle `GET /transactions?customer_id={id}&status=completed,paid&order_by=billed_at[DESC]&per_page=24`. Workspace-scoped via `verify_token`; `paddle_customer_id` read from our `workspaces` row, **never** accepted from the client. Response shape: `{ invoices: [{ id, billed_at, amount_cents, currency, status, invoice_pdf_url }] }`.
- **D-18:** Max 24 rows (2 years of monthly invoicing covers nearly all users). Columns: Date · Amount · Status · Download PDF. Empty state: "No invoices yet."
- **D-19:** PDF download links are the Paddle-hosted signed URLs returned by their API, rendered as `<a href={invoice_pdf_url} target="_blank" rel="noopener noreferrer">Download</a>`. Never proxy PDF bytes through Railway. On 404/expired (Paddle signed URLs are short-lived), the user clicks the Invoices card Retry (D-30) to refetch fresh signed URLs.

### Post-Action Refresh & Race Handling
- **D-20:** Every mutation endpoint (`/billing/change-plan`, `/cancel`, `/reactivate`) writes the expected end-state to our `workspaces` row immediately after the Paddle API call returns 2xx — synchronously, before returning to the client. The webhook that follows is a reconciliation no-op thanks to Phase 7 D-10 `ON CONFLICT (event_id) DO NOTHING` dedup. This kills the UI-vs-webhook race at its source.
- **D-21:** Post-mutation refresh cadence: on client-side 2xx response, (a) optimistically apply the returned `BillingSummary` to `BillingContext`, (b) show a success toast, (c) schedule `BillingContext.refresh()` calls at 0s (immediate), 3s, and 10s. The 30s poll from Phase 7 D-18 continues as the reconciliation floor. Worst-case visible lag: ~3s.
- **D-22:** Every mutation endpoint returns the fresh `BillingSummary` in its response body. Frontend passes this straight to `BillingContext.setBilling(...)` — no separate `/summary` round-trip needed for the initial flip.
- **D-23:** Optimistic flip is gated on a 2xx client response. On 4xx/5xx: toast only, zero local state change, zero rollback path needed. Simpler + safer than optimistic-then-rollback.

### Teams Plan Eligibility
- **D-24:** Teams ($99/mo) is self-serve in v1.1 — same Paddle overlay flow, just a different price_id (`PADDLE_TEAMS_PRICE_ID`). The product is live on Paddle per `paddle_product_spec.md`; gating it behind sales would slow growth with no upside.
- **D-25:** Surface strategy. On **Free workspaces**: Billing card shows "Upgrade to Cloud" as the primary button; a small secondary text link "or Teams — $99/mo" opens a lightweight plan-comparison modal. On **Cloud workspaces**: an additional "Upgrade to Teams" button appears in the Billing card's action row. On **Teams workspaces**: no upgrade affordance; only "Change plan" (→ Cloud, downgrade per D-05) and "Cancel" (per D-11).
- **D-26:** Plan-comparison modal renders data pulled from `plan_limits` (price_cents, seat_count, retention_days, api_key_count, gated_features). No hand-maintained marketing copy in the modal body — single source of truth for tier differences. Each row has a "Choose {plan}" button that launches checkout for that price_id.

### Error & Failure Paths
- **D-27:** User closes the Paddle overlay without completing checkout → silent return. We detect via the Paddle.js `closeCheckout`/close callback. No toast ("I changed my mind" is not a failure), no server log, no analytics event beyond whatever Paddle records.
- **D-28:** Paddle API 5xx / network timeout during a mutation → server returns 502 to the client. Client shows toast: "Couldn't {action} — our billing provider didn't respond. Try again in a moment; if it persists, email support@burnlens.app." Server-side log includes workspace_id, operation, Paddle response status + body for debugging. No automatic retry (risk of double-mutation if Paddle processed but timed out on response).
- **D-29:** In-checkout payment decline → Paddle's overlay owns the error UX. We do nothing extra. Recurring-payment failure (post-activation) is covered by the Phase 7 D-21 past_due banner.
- **D-30:** Invoice list fetch failure → inline error in the Invoices card: "Couldn't load invoices" + a Retry button. Plan card above continues rendering normally. Matches the existing "Billing info unavailable" pattern in `BillingCardBody` at `frontend/src/app/settings/page.tsx:277-310`.
- **D-31:** Double-submit protection, defense in depth:
  - Client: button `disabled` + spinner while the request is in flight.
  - Server: mutation endpoints are idempotent — calling `/billing/cancel` when `cancel_at_period_end=true` already, or `/billing/reactivate` when no scheduled cancel exists, or `/billing/change-plan` with the current plan, returns 200 with the current `BillingSummary` and makes no Paddle API call. Handles tab-duplicates + refresh-mid-request.

### Security Posture (explicit)
- **D-32:** All Paddle identifiers (`paddle_customer_id`, `paddle_subscription_id`, `price_id`) are read from the server-side `workspaces` row. The client never sends, and the server never accepts, any of these. The only client input on mutation endpoints is `{target_plan}` on `/change-plan` — validated against the `{"cloud","teams"}` allowlist before any Paddle call.
- **D-33:** Every new endpoint (`/change-plan`, `/cancel`, `/reactivate`, `/invoices`) gates on the existing `verify_token` dependency. Workspace-id is derived from the token, never from request body or query params. Cross-tenant reads/writes are structurally impossible.
- **D-34:** Webhook signature verification (Phase 7 `_verify_signature`) continues to be the only trust boundary for state changes driven by Paddle. Our mutation endpoints are allowed to proactively write our DB (D-20) only because they made the upstream Paddle call themselves — if Paddle rejects, nothing is written.

### Claude's Discretion
- Exact toast copy wording (within the D-28 pattern).
- Modal primitive choice — new `<ConfirmModal>` component vs. inline overlay reusing an existing pattern — pick what's consistent with Shell/Topbar style already in the frontend.
- `cancellation_surveys` table additional columns beyond the minimum (e.g., `plan_at_cancel`, `tenure_days_at_cancel`) — add if planner sees obvious value, skip otherwise. Never add PII beyond what's already known.
- Whether `/billing/invoices` uses Paddle cursor pagination under the hood or a single `per_page=24` fetch — both satisfy the 24-row contract; pick the simpler.
- Exact placement ordering of action buttons within the Billing card when multiple affordances coexist (e.g., Cloud workspace: "Upgrade to Teams" + "Cancel" + "Manage payment method" [portal link]).
- Whether Paddle's `Paddle.Checkout.open` close callback can reliably distinguish successful vs. abandoned close — if yes, optionally add a success toast on completed-close; if unreliable, depend on the webhook-driven refresh cadence from D-21.
- Structure of the `change-plan` handler internally — one handler with a proration-mode switch, or two private helpers keyed to upgrade/downgrade direction.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Roadmap & Requirements
- `.planning/ROADMAP.md` §"Phase 8: Billing Self-Service" — goal, success criteria, BILL-03..BILL-06 mapping.
- `.planning/REQUIREMENTS.md` §"Billing Panel (BILL)" — BILL-03 (checkout to upgrade/downgrade), BILL-04 (invoice history), BILL-05 (self-serve cancel at period end), BILL-06 (reactivate before period expires).

### Phase 7 Foundation (carries forward)
- `.planning/phases/07-paddle-lifecycle-sync/07-CONTEXT.md` — Phase 7 decisions. In particular:
  - D-07 (price_cents/currency cached columns) — render-without-Paddle-round-trip already works.
  - D-12/D-13 (compact summary card layout) — Phase 8 extends, does not replace.
  - D-18 (30s poll while focused) — backstop for our D-21 refresh cadence.
  - D-19 (BillingContext as single state source) — our mutation endpoints feed this.
  - D-20 (`?checkout=success` listener in Settings) — already wired at `frontend/src/app/settings/page.tsx:25-36`.
  - D-21 (past_due amber banner) — continues to handle recurring-payment failure in Phase 8.
  - D-22/D-23 (canceled/paused downgraded to free by webhook) — UI must render these as "Active" on the Free plan (already implemented by `statusDisplay` at `page.tsx:233-250`).

### Live Paddle Configuration
- `~/.claude/projects/-Users-bhushan-Documents-Projects-burnlens/memory/paddle_product_spec.md` — live Paddle product / price / webhook IDs, notification-setting event list, env var names (`PADDLE_API_KEY`, `PADDLE_CLOUD_PRICE_ID`, `PADDLE_TEAMS_PRICE_ID`, `PADDLE_WEBHOOK_SECRET`, `PADDLE_ENVIRONMENT`, `NEXT_PUBLIC_PADDLE_CLIENT_TOKEN`, `NEXT_PUBLIC_PADDLE_ENV`). Downstream agents MUST read this for exact price IDs before wiring `/change-plan`.

### Existing Code to Extend
- `burnlens_cloud/billing.py` — already has `_verify_signature`, `_paddle_headers`, `_paddle_base_url`, `_plan_to_price_id`, `/checkout`, `/portal`, `/summary`, webhook. Phase 8 adds `/change-plan`, `/cancel`, `/reactivate`, `/invoices` as sibling endpoints + response models.
- `burnlens_cloud/database.py` §workspaces — existing columns from Phase 7 (`cancel_at_period_end`, `current_period_ends_at`, `trial_ends_at`, `price_cents`, `currency`, `paddle_customer_id`, `paddle_subscription_id`, `subscription_status`). Phase 8 adds new table `cancellation_surveys` via idempotent `CREATE TABLE IF NOT EXISTS` inside `init_db()`.
- `burnlens_cloud/models.py` — existing `BillingSummary`. Phase 8 adds `CancelBody` (optional reason), `ChangePlanBody` (`{target_plan: "cloud" | "teams"}`), and `InvoicesResponse` / `Invoice` models.
- `burnlens_cloud/main.py` — billing router already mounted; the new endpoints ride on the same `APIRouter(prefix="/billing")`.
- `frontend/src/components/UpgradePrompt.tsx` — **canonical pattern for Paddle.js overlay usage.** Phase 8 extracts the `initializePaddle` + `Paddle.Checkout.open` + hosted-URL fallback into a reusable hook or shared component so Settings can consume it without duplication.
- `frontend/src/lib/contexts/BillingContext.tsx` — `refresh()` method already exposed; Phase 8 may add a `setBilling` escape hatch (or reuse `refresh()` after mutation calls) so mutation responses short-circuit the polling cycle.
- `frontend/src/app/settings/page.tsx` — `BillingCardBody` at lines 252-393 is the component to extend. Disabled CTAs at lines 298-307 and 382-390 (with "Coming soon — Phase 8" tooltips) are the exact spots to wire. The `?checkout=success` listener at lines 25-36 already exists — no changes needed, just navigate with that query param after Paddle overlay reports success.

### Paddle API Docs (external, live)
- Paddle Subscription PATCH: https://developer.paddle.com/api-reference/subscriptions/update-subscription — proration_billing_mode values (`prorated_immediately`, `prorated_next_billing_period`, `do_not_bill`, `full_next_billing_period`), `scheduled_change` shape.
- Paddle Cancel Subscription: https://developer.paddle.com/api-reference/subscriptions/cancel-subscription — `effective_from: "next_billing_period"` for cancel-at-period-end.
- Paddle Transactions list: https://developer.paddle.com/api-reference/transactions/list-transactions — `customer_id` filter, `invoice_pdf_url` in response, signed-URL TTL behavior.
- Paddle.js Checkout.open: https://developer.paddle.com/paddlejs/methods/paddle-checkout-open — `transactionId` parameter, settings object, `eventCallback` / close events.
- Paddle.js events reference: https://developer.paddle.com/paddlejs/events/overview — for determining whether close distinguishes success vs abandon (Claude's discretion item).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `burnlens_cloud/billing.py::_paddle_headers` + `_paddle_base_url` — HTTP client helpers. All new Paddle calls go through these.
- `burnlens_cloud/billing.py::_plan_to_price_id` — plan string → price_id resolver. Reuse in `/change-plan`.
- `burnlens_cloud/billing.py::_verify_signature` — HMAC webhook verification (already Phase 7 spec-compliant).
- `burnlens_cloud/database.py::execute_query` / `execute_insert` — asyncpg wrappers. All DB access.
- `burnlens_cloud/auth.py::verify_token` + `TokenPayload` — dependency for scoping every new endpoint to the caller's workspace.
- `frontend/src/components/UpgradePrompt.tsx` — **the** Paddle.js overlay reference. Extract its `initializePaddle` + `Paddle.Checkout.open({ transactionId })` + `data.url` fallback into a shared hook (`useCheckout`?) or shared wrapper.
- `frontend/src/lib/contexts/BillingContext.tsx` — already provides `billing`, `loading`, `error`, `refresh`. Phase 8 either adds `setBilling` (for D-22 optimistic flip) or calls `refresh()` per D-21 cadence.
- `frontend/src/lib/api.ts::apiFetch` + `AuthError` — authenticated fetch + 401 handling pattern for new mutation endpoints.
- `frontend/src/app/settings/page.tsx` — `BillingCardBody` layout (lines 252-393), existing skeleton / error / empty-state patterns (lines 253-310), the `?checkout=success` post-handoff effect (lines 25-36), and `statusDisplay` pill logic (lines 233-250) — all Phase 7 and directly reusable.

### Established Patterns
- Idempotent migrations via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` / `CREATE TABLE IF NOT EXISTS` in `init_db()`. `cancellation_surveys` follows this exactly.
- FastAPI `APIRouter(prefix="/billing", tags=["billing"])`. New endpoints sit on the same router; no new router.
- Pydantic response models in `burnlens_cloud/models.py`. New `Invoice`, `InvoicesResponse`, `ChangePlanBody`, `CancelBody` live there.
- 502 + `logger.error` for upstream Paddle failures, 200 on webhook handler exceptions (Phase 7 invariant — do not change for mutation endpoints, which return real 502s per D-28).
- `useAuth` session gate + `apiFetch(..., session.token)` for authenticated requests.
- Settings CSS: `.card`, `.section-header`, `.form-input`, `.btn`, `.btn-red`, `.btn-cyan`. New cancel-modal + Invoices card match this vocabulary.

### Integration Points
- Four new REST endpoints on existing `/billing` router: `POST /change-plan`, `POST /cancel`, `POST /reactivate`, `GET /invoices`.
- One new Postgres table `cancellation_surveys` via idempotent ALTER in `database.py::init_db`.
- Settings page `BillingCardBody` gains: real onClick handlers for currently-disabled CTAs, conditional Cancel/Resume button per D-12, a new Cancel confirmation modal, a new Invoices card below the plan card.
- Plan-picker modal: new component, invoked from the "or Teams — $99/mo" link (D-25). Pulls data from `plan_limits` via a new thin endpoint (`GET /billing/plans`? Or extend `/billing/summary` — planner's call).
- `BillingContext`: post-mutation updates via D-22 response payload; no new provider.
- Env: no new environment variables. Existing Paddle config already covers everything.

</code_context>

<specifics>
## Specific Ideas

- **Global overlay, stated by the user:** "go with recommended, ensure we dont compromise on user experience and security." This is the tiebreaker for every Claude's-Discretion item: if a choice trades UX or security for convenience, choose the other way.
- **Cancel confirmation copy is concrete, not placeholder:** "You'll keep {plan_label} until {formatted_date}. After that, your workspace will switch to the Free plan." — use exact words.
- **Reason options are concrete:** "Too expensive / Missing a feature / Switching tools / Not using it enough / Other." These are the radio labels, not examples.
- **Amber canceled-inline message is concrete:** "Canceled — ends {date}. Resume to keep access."
- **Toast copy for the D-28 error path is concrete:** "Couldn't {action} — our billing provider didn't respond. Try again in a moment; if it persists, email support@burnlens.app."
- **Resume button color:** green (not cyan, not the default btn). Cancel button stays `.btn-red` to match the existing `Regenerate` button style on the API key row.
- **The existing disabled CTAs at `page.tsx:298-307` and `page.tsx:382-390` are the exact DOM positions to replace.** Planner should NOT relocate them.
- **24 invoice rows is the ceiling, not a pagination page size.** No "Load more" button; if someone has >24 they see the 24 most recent and we accept the edge case in v1.1.

</specifics>

<deferred>
## Deferred Ideas

- Retention offers at cancel time (discount codes / 1-month pause) — v1.2 if churn data shows churn is actually the problem.
- Required cancel-reason survey — keep optional for v1.1; revisit if optional response rate is too low to be useful.
- Webhook-cached invoices table (subscribing to `transaction.completed` and materializing in Postgres) — premature given Paddle API is fast and the data is low-volume. Reconsider if invoice-list latency becomes a user complaint.
- Proxying PDF bytes through Railway — keeps URLs stable but not worth the bandwidth/infrastructure. Paddle signed URLs with a refresh-on-404 UX is sufficient.
- `/settings/billing/plans` dedicated route + full-page side-by-side comparison — out of scope; the in-Settings card + plan-picker modal meet all BILL-0x requirements.
- "Contact sales" Teams path — Teams is self-serve in v1.1. If a sales-assisted Enterprise tier emerges, it's a new phase.
- In-checkout payment-decline custom UX — Paddle doesn't expose this event reliably via paddle-js; not worth building on top of unreliable signal.
- Topbar upgrade pill CTA (beyond the existing "FREE · UPGRADE" badge) — we already have that; no additional always-visible CTA.
- Dedicated mobile-specific cancel flow — the default responsive layout is enough for v1.1.
- Multi-year / annual-prepay plans — Paddle supports them, but not in our product offer today. Future pricing phase.
- Per-seat pricing on Teams (price scales with seat count) — Teams is flat $99/mo in v1.1. Revisit if seat economics shift.
- Cancellation survey analytics dashboard — the raw data lands in Postgres; building the view is later.

</deferred>

---

*Phase: 08-billing-self-service*
*Context gathered: 2026-04-19*
