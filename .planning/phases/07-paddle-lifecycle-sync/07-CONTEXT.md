# Phase 7: Paddle Lifecycle Sync - Context

**Gathered:** 2026-04-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Paddle webhook events are the authoritative source of each workspace's plan and subscription state, and the user can read that state back from a read-only Settings → Billing summary. The Topbar plan badge stays truthful within 60 seconds of any Paddle lifecycle event.

**In scope:** webhook handlers (activated/updated/canceled/paused + payment_failed), schema extensions to carry period/trial/cancel dates, `GET /billing/summary` endpoint, read-only Settings → Billing card, Topbar + Settings refresh pathway, past_due banner, event dedup/audit log.

**Out of scope (Phase 8):** checkout mutations, self-serve cancel, reactivate, invoice history listing, manage-billing wiring. Phase 7 leaves one disabled "Manage billing" stub in place for Phase 8 to replace.

**Out of scope (Phase 9/10):** quota enforcement, plan-gated feature locks, usage meter — all orthogonal to lifecycle sync.
</domain>

<decisions>
## Implementation Decisions

### Webhook Event Mapping
- **D-01:** Handle exactly the events the live Paddle notification setting (`ntfset_01kpe4f7r19k7xdqdw588qs9zm`) is subscribed to: `subscription.activated`, `subscription.updated`, `subscription.canceled`, `subscription.paused`, `transaction.payment_failed`. Do not subscribe to `subscription.created` or `transaction.completed` — `subscription.activated` is the paid-and-live signal, and renewals arrive via `subscription.updated`.
- **D-02:** The success criteria in ROADMAP.md should be interpreted as: "created" → `subscription.activated`; `transaction.completed` → covered implicitly by `subscription.updated` restoring `status='active'`. This is a wording reconciliation, not a Paddle config change.
- **D-03:** `past_due` ↔ `active` transitions are driven as follows: `transaction.payment_failed` flips `subscription_status` to `past_due` (plan unchanged). Any subsequent `subscription.updated` with `status='active'` flips back to `active`.

### State Schema (workspaces table)
- **D-04:** Add `trial_ends_at timestamptz NULL` — populated from Paddle subscription payload when `status='trialing'`; surfaced in Settings → Billing if non-null.
- **D-05:** Add `current_period_ends_at timestamptz NULL` — populated from Paddle subscription payload; used for the "Next billing" line in Settings.
- **D-06:** Add `cancel_at_period_end boolean NOT NULL DEFAULT false` — populated from Paddle so the webhook doesn't need a Phase-8 round-trip when reactivate lands.
- **D-07:** Add `price_cents integer NULL` and `currency text NULL` — cached from the Paddle price payload so the Settings card renders `$29/mo` without a Paddle API round-trip. Falls back to `null` for free-tier workspaces.
- **D-08:** All new columns added via idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements inside the existing `init_db()` flow. Migrations must remain re-runnable per Phase 6's pattern.

### Event Dedup & Audit
- **D-09:** New `paddle_events` table: `(event_id text PRIMARY KEY, event_type text NOT NULL, received_at timestamptz NOT NULL DEFAULT now(), payload jsonb NOT NULL, processed_at timestamptz NULL, error text NULL)`. `event_id` is Paddle's event-envelope id — we insert-or-skip on it to get dedup for free.
- **D-10:** Webhook flow: verify signature → parse → `INSERT ... ON CONFLICT (event_id) DO NOTHING RETURNING event_id`. If nothing returned, the event was already processed; return 200 without re-running handlers. Otherwise process, then `UPDATE paddle_events SET processed_at = now()` (or `error = ...` on failure).
- **D-11:** Continue returning 200 on handler exceptions (current behavior) so Paddle doesn't retry-storm on code bugs — but `error` column lets us find stuck events in production.

### Settings → Billing Read View
- **D-12:** Layout is the compact summary card — single card with plan+price+status on row 1, next-billing/trial-expiry on row 2, one disabled "Manage billing → (coming soon)" button at the bottom. No multi-row label/value layout, no plan-limits preview (Phase 10 owns that surface).
- **D-13:** Free users see the same card: `Free · $0`, no dates, status pill reads `Active`, CTA reads "Upgrade to Cloud" (disabled stub — Phase 8 wires checkout). Never hide the panel entirely — the upgrade surface stays discoverable.
- **D-14:** Paid users in `past_due` see the card unchanged plus an amber banner above the dashboard content (see D-20). Paid users in `canceled`/`paused` are already downgraded to free (see D-21/D-22) and see the free state.

### Phase 8 Scaffolding
- **D-15:** Ship exactly one disabled "Manage billing" button with tooltip "Coming soon". Do not wire it to the existing `/billing/portal` endpoint in Phase 7 — self-serve is Phase 8's promise, not Phase 7's. No other mutation affordances.

### Backend Surface
- **D-16:** New `GET /billing/summary` endpoint in `burnlens_cloud/billing.py` returns: `{ plan, price_cents, currency, status, trial_ends_at, current_period_ends_at, cancel_at_period_end }`. Single indexed workspace-by-id lookup. No Paddle API calls — everything reads from our Postgres cache.
- **D-17:** `GET /billing/summary` is workspace-scoped via the existing `verify_token` dependency (same pattern as `/checkout` and `/portal`).

### UI Freshness (< 60s guarantee)
- **D-18:** Client polls `GET /billing/summary` on a 30–45s interval while the app is focused, plus on window-focus events. This comfortably clears the 60s requirement with no new infrastructure.
- **D-19:** Plan state lives in a single React context/query fed by `/billing/summary`. Topbar reads from this context, not from `localStorage.plan`. `localStorage.plan` degrades to a stale-on-boot hint only — the context replaces it as soon as the first poll returns.
- **D-20:** Post-checkout refresh hook: when the Settings page loads with `?checkout=success` in the URL (Phase 8 will navigate with this param), the billing query invalidates and fetches immediately rather than waiting for the next poll tick. Phase 7 wires this listener so Phase 8 just has to navigate.

### past_due / Trial / Paused Behavior
- **D-21:** `past_due` keeps full access. `plan` unchanged, `subscription_status='past_due'`, a persistent amber banner renders across dashboard pages reading "Payment failed — update billing" with a link to Settings → Billing. Matches v1.1's soft-enforcement posture. Paddle retries payment automatically; a successful retry fires `subscription.updated` with `status='active'` and clears the banner.
- **D-22:** Trial-expiry without payment method arrives as `subscription.canceled` from Paddle. Handler downgrades `plan='free'`, `subscription_status='canceled'`. Topbar badge flips to Free with upgrade pill (existing behavior). Re-upgrade path is Phase 8.
- **D-23:** `subscription.paused` is treated the same as `subscription.canceled`: downgrade to free, status='paused'. Current handler already groups these together — keep that behavior.

### Claude's Discretion
- Banner component location (new `BillingStatusBanner.tsx` vs. extending an existing layout slot) — pick what's consistent with Topbar/Shell.
- Exact poll interval within the 30–45s range.
- `paddle_events.payload` jsonb indexing — add GIN index only if plan finds a query that needs it; otherwise skip.
- Error-surface strategy for dedup races (two workers processing the same event) — pick the simplest option that preserves correctness.
- Where to mount the `?checkout=success` listener (Settings page mount effect vs. global auth boundary) — whichever keeps concerns local.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Paddle Integration (authoritative)
- `.planning/ROADMAP.md` §"Phase 7: Paddle Lifecycle Sync" — goal, success criteria, canonical refs list.
- `.planning/REQUIREMENTS.md` §"Paddle Integration (PDL)" — PDL-01..PDL-04 wording.
- `.planning/REQUIREMENTS.md` §"Billing Panel (BILL)" — BILL-01 (plan/price/status view), BILL-02 (next billing + trial expiry).
- `~/.claude/projects/-Users-bhushan-Documents-Projects-burnlens/memory/paddle_product_spec.md` — live Paddle product/price/webhook IDs, notification setting event list, env var names. Downstream agents MUST read this for the exact `ntfset_*` id and webhook secret variable name.

### Phase 6 Foundation (already shipped)
- `.planning/phases/06-plan-limits-foundation/06-CONTEXT.md` (if present) and `06-PLAN.md` artefacts — Phase 6 seeded `plan_limits` with `paddle_price_id` column. Phase 7 webhook maps Paddle price_id → internal plan by reading that column, not hardcoded env vars. Keep env-based fallback for safety but prefer the DB lookup.
- `burnlens_cloud/database.py` §plan_limits seed (lines ~249–305) — shows the existing `idx_plan_limits_paddle_price` partial index Phase 7 should hit.
- `burnlens_cloud/plans.py` — resolver wrapper (not needed by webhook but referenced for consistency).

### Existing Code to Extend
- `burnlens_cloud/billing.py` — already has webhook signature verification (`_verify_signature`), handlers for activated/updated/canceled/paused, and `/checkout` + `/portal` endpoints. Phase 7 refactors the handlers to populate new columns and adds `GET /billing/summary`.
- `burnlens_cloud/database.py` §workspaces (lines ~20–76) — the existing workspaces table + paddle_customer_id / paddle_subscription_id / subscription_status columns. New columns (D-04..D-08) go alongside via idempotent ALTERs.
- `burnlens_cloud/models.py` — Pydantic models. New `BillingSummary` response model lives here.
- `burnlens_cloud/main.py` — route mount point for the billing router (already mounted; just make sure the new summary endpoint is included).
- `frontend/src/components/Topbar.tsx` lines 44–77 — existing plan badge reading `session.plan`. Phase 7 switches it to read from the new billing context (D-19).
- `frontend/src/app/settings/page.tsx` lines ~81–93 — existing hardcoded "Free" tier display. Phase 7 replaces it with the compact summary card (D-12).

### Paddle API Docs (external, live)
- Paddle Events reference: https://developer.paddle.com/webhooks/overview — event envelope shape, event_id, signing.
- Paddle Subscription object: https://developer.paddle.com/api-reference/subscriptions/overview — fields for `current_billing_period`, `trial_dates`, `scheduled_change`, `status` values.
- Paddle Signature verification: https://developer.paddle.com/webhooks/signature-verification — current implementation in `_verify_signature` already matches.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `burnlens_cloud/billing.py::_verify_signature` — Paddle HMAC verification, tolerance 300s. Reuse as-is.
- `burnlens_cloud/billing.py::_plan_from_price_id` — maps price_id → plan via env vars. Extend (or replace) with a DB lookup against `plan_limits.paddle_price_id` per Phase 6, with env fallback.
- `burnlens_cloud/database.py::execute_insert` / `execute_query` — existing asyncpg wrappers. All new DB access uses these.
- `burnlens_cloud/auth.py::verify_token` + `TokenPayload` — dependency for scoping `/billing/summary` to the caller's workspace.
- `frontend/src/lib/api.ts::apiFetch` — existing authenticated fetch; Settings page already uses it.
- `frontend/src/lib/hooks/useAuth.ts` — existing session hook; the new billing context will likely sit alongside or inside it.
- `frontend/src/components/Shell.tsx` — page shell; banner for `past_due` mounts here or in Topbar depending on layout decisions.

### Established Patterns
- Idempotent migrations inside `init_db()` — new columns use `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (pattern already in `database.py` for paddle_customer_id etc.).
- Router pattern — `APIRouter(prefix="/billing", tags=["billing"])` in `billing.py`, mounted from `main.py`.
- Silent-success webhook — current code catches handler exceptions, logs, and returns 200. Keep this for Paddle retry hygiene.
- Plan state currently hydrated from `localStorage` on client boot via `useAuth` — Phase 7 layers the billing context on top; localStorage stays as a fast-boot hint only.

### Integration Points
- Webhook → Postgres: `/billing/webhook` handler writes to `workspaces` (plan/status/dates) and `paddle_events` (audit/dedup).
- Backend → Frontend: new `GET /billing/summary` is the single client-facing contract for plan state.
- Frontend polling: new React context queries `/billing/summary` on interval + focus + `?checkout=success`.
- Topbar badge and Settings Billing card both subscribe to that context — no duplicate fetches.
</code_context>

<specifics>
## Specific Ideas

- Settings → Billing card matches the ASCII mock the user selected: `Cloud · $29/mo [● Active]` on line 1, `Next billing: <date>` on line 2, disabled `[Manage billing →]` button on line 3. Use existing `.card` + `.section-header` CSS classes from the Settings page.
- past_due banner copy: "Payment failed — update billing" with a link to Settings → Billing. Amber styling (use existing warning token if one exists; otherwise match the alert pattern already used elsewhere in the dashboard).
- Plan display name capitalization: "Free", "Cloud", "Teams" (Title Case) — matches Topbar `PLAN_LABELS`.
- Poll interval: default 30s while focused, pause when tab hidden, resume+fetch on focus.
</specifics>

<deferred>
## Deferred Ideas

- Subscribing to `subscription.created` and `transaction.completed` — would enable finer-grained state tracking but redundant given activated+updated cover the same transitions. Revisit if Paddle changes event semantics.
- Paused-as-temporary-hold behavior (keep access with banner) — deferred; current treatment collapses paused into canceled for simplicity. Revisit in v1.2 if product wants pause-to-vacation flows.
- Paddle `subscription.trialing` event explicit handler — if Paddle fires this as its own event (vs. just a status field on activated/updated), wire a dedicated handler. For now, read `status` off activated/updated payloads.
- Edge-cache or CDN cache for `/billing/summary` — tempting but wrong: response is per-user and must reflect webhook writes immediately. Keep it uncached.
- SSE/WebSocket push for state changes — reconsider once we have another product reason to add a push channel. Billing alone doesn't justify the infra.
- Revenue/billing metrics dashboard (events received, failed, dedup rate) — the `paddle_events` table gives us the raw material, but building the view is a later concern.
- Invoice history, cancel, reactivate, checkout-from-Settings — all Phase 8 scope.
- Usage meter, gated-feature lock UI — Phase 10 scope.
</deferred>

---

*Phase: 07-paddle-lifecycle-sync*
*Context gathered: 2026-04-19*
