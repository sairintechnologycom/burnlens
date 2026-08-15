# Handoff — the 2026-08-22 trial conversion

Written 2026-08-15. Every fact in §0 was read from the live Paddle API or the
production database at that time, not recalled. **This event fires by itself on
2026-08-22 06:55:25 UTC whether or not anyone is ready.** Re-verify before acting.

---

## 0. Verified state

**Paddle** — one subscription exists, `sub_01m0238dam04x47aqc7bcwq5qr`.

| field | value |
|---|---|
| status | `trialing` |
| trial | 2026-08-15 06:55:25Z → **2026-08-22 06:55:25Z** |
| `next_billed_at` | 2026-08-22T06:55:25.519Z |
| price | `pri_01kpe2gkbz9w85btadnw8ckkyn` (Cloud) |
| `collection_mode` | `automatic` — Paddle charges the saved card, no user action |
| `scheduled_change` | `null` |
| `custom_data.workspace_id` | `318aef07-49c4-424a-9b77-e710f4c46f89` |

**Transactions so far: exactly one** — `txn_01m0234cq8xv81dbyxka8jw39j`, status
`completed`, total **`"0"` INR**. That is the trial authorisation. **No money has
moved yet.** 2026-08-22 is the first real charge.

**Production DB** (`workspaces` row with a non-null `paddle_subscription_id_hash`):

```
plan   | subscription_status | cancel_at_period_end | current_period_ends_at    | trial_ends_at | price_cents | currency
cloud  | trialing            | f                    | 2026-08-22 06:55:25.519+00| (NULL)        | 2900        | USD
```

`workspace_usage_cycles` correctly seeded the paid period:
`2026-08-15 06:55:25 → 2026-08-22 06:55:25`, `request_count = 0`. The old free
calendar-month row (`2026-08-01 → 2026-09-01`, 9,192) is inert now.

**Webhook destination** `ntfset_01kzge0wmdq1mx7ebjh25d51vm` →
`https://api.burnlens.app/billing/webhook`, active, subscribed to all 10 events the
code handles. `SMTP_PASSWORD` is set on the Railway `burnlens-proxy` service, so
`is_email_enabled()` is true and receipts will actually send.

---

## 1. What fires on 2026-08-22

Paddle's own definition: *"`subscription.activated` — occurs when a subscription
becomes active… **this means any trial period has elapsed and Paddle has successfully
billed the customer**."* So the conversion event is one we already subscribe to and
already handle.

Expected sequence:

1. `transaction.completed` → `_handle_transaction_completed` → payment-receipt email
   to the workspace owner. Resolves the workspace via `custom_data.workspace_id`
   (present) with a subscription-lookup fallback.
2. `subscription.activated` → `_handle_subscription_activated` → `plan='cloud'`
   (unchanged), `subscription_status='active'`, refreshed period columns, and a new
   `workspace_usage_cycles` row seeded for 08-22 → 09-22.

Nothing needs to be deployed for this to work. The question is whether it *does*.

---

## 2. The one real risk — the charge itself

The money path was blocked for weeks by **an INR card refusing recurring mandates**.
That blocker was declared closed on 2026-08-15 when checkout succeeded — but what
succeeded was a **₹0 trial authorisation**, not a recurring charge. A card that
authorises ₹0 can still decline a ₹2,900-equivalent recurring debit; Indian
e-mandate rules (RBI AFA / e-NACH) are enforced at debit time, not at auth time.

**So treat 2026-08-22 as the first genuine test of the recurring mandate.** It is the
last unproven leg of billing, and it is unproven precisely because nothing has been
charged yet.

If the debit fails, `transaction.payment_failed` fires →
`_handle_payment_failed` (`billing.py:616`) sets `subscription_status='past_due'`,
**leaving `plan` unchanged** (D-21), so access is not cut off. The UI already covers
this: `statusDisplay` renders an amber "Past due" chip (`settings/page.tsx:271`) and
`BillingStatusBanner.tsx:28` shows a banner. Paddle retries automatically; a
successful retry emits `subscription.updated` with `status='active'`, which
`_handle_subscription_updated` applies and which clears the past-due state.

Note `subscription.past_due` is neither subscribed nor handled — that is consistent,
not a gap, because `transaction.payment_failed` carries the same signal and *is*
subscribed.

---

## 3. Bug found while verifying this — `trial_ends_at` is never populated

**Confirmed against the live API, not inferred.**

`_extract_trial_end` (`burnlens_cloud/billing.py`) reads:

```python
return _parse_iso((data.get("trial_dates") or {}).get("ends_at"))
```

Paddle puts trial dates on the **line item**, not the subscription. Verified on the
live entity:

- `sub.trial_dates` → **absent (undefined)**; no top-level key contains "trial"
- `sub.items[0].trial_dates` → `{starts_at: 2026-08-15…, ends_at: 2026-08-22…}`

So the extractor reads a key that never exists, returns `None`, and writes NULL —
which is exactly what production shows.

**User-visible effect:** `settings/page.tsx:445` gates on
`isTrialing = billing.status === "trialing" && !!billing.trial_ends_at`. With the
field NULL that is false, so the **"Trial ends: …" line never renders**. A trialing
customer gets no in-app warning of the date they will be charged — which is the worst
possible week for that line to be missing.

**Fix** — read item-level first, keep the old path as a fallback:

```python
def _extract_trial_end(data: dict) -> Optional[datetime]:
    try:
        items = data.get("items") or []
        for item in items:
            ends = ((item or {}).get("trial_dates") or {}).get("ends_at")
            if ends:
                return _parse_iso(ends)
        return _parse_iso((data.get("trial_dates") or {}).get("ends_at"))
    except Exception:
        return None
```

**Backfilling the current row is separate from the fix.** Even after deploying, the
column stays NULL until a webhook re-writes it — and the next one that does is the
08-22 activation, by which point the trial is over and the banner is moot. To see it
work before then, either set `trial_ends_at` directly on the workspaces row from
`sub.items[0].trial_dates.ends_at`, or ignore it and let the fix serve the *next*
trialing customer. **Decide which; do not assume deploying is sufficient.**

Add a test — `_extract_trial_end` against a real item-shaped payload. This is the same
class as every other silent-null in this project: a plausible value read from a key
that does not exist, with nothing asserting otherwise.

---

## 4. What to verify after 2026-08-22 06:55 UTC

Run these, do not assume:

```bash
# 1. Paddle side — did the charge actually succeed?
#    Expect status=active, and a SECOND transaction with a non-zero total.
#    (via the Paddle MCP: client.subscriptions.get + client.transactions.list)

# 2. Our side — did the webhook land?
DB=$(railway variables --service Postgres --kv | grep '^DATABASE_PUBLIC_URL=' | cut -d= -f2-)
psql "$DB" -c "SELECT plan, subscription_status, current_period_ends_at, trial_ends_at
               FROM workspaces WHERE paddle_subscription_id_hash IS NOT NULL;"
# Expect: plan=cloud, subscription_status=active, period ends 2026-09-22.

# 3. New billing cycle seeded?
psql "$DB" -c "SELECT cycle_start, cycle_end, request_count
               FROM workspace_usage_cycles ORDER BY cycle_start DESC LIMIT 2;"
# Expect a new row 2026-08-22 → 2026-09-22.

# 4. Receipt email actually sent — check Railway logs for
#    "_handle_transaction_completed: receipt queued for workspace=".
```

Failure signature to watch for: `subscription_status='past_due'` plus a
`transaction.payment_failed` entry in `paddle_events`. That means the mandate was
refused — a payment-instrument problem, **not** a code problem. Do not start rewriting
billing code in response. The fix is a different card or an enabled wallet.

---

## 5. Traps

- **The trial ends before the roadmap does.** If the card is going to be swapped, do it
  *before* 08-22 via `management_urls.update_payment_method` — after a failed debit the
  subscription is already past_due and dunning has started.
- `railway` must run from the linked repo directory or it silently targets nothing. The
  service is `burnlens-proxy`; `railway variables` with no `--service` returns nothing.
- Never print `DATABASE_PUBLIC_URL` — pipe it into a shell variable. It carries
  credentials into the transcript otherwise.
- A green Railway deploy workflow does **not** mean the code is serving. Poll
  `https://api.burnlens.app/openapi.json` for something the new build introduces.
- `export GH_TOKEN=$(gh auth token --user sairintechnologycom)` before any push or
  merge; `github` is canonical, `origin` is a stale Azure DevOps mirror.
- Paddle API key expires **2026-11-06**. Not a risk for this event, but an expired key
  403s everything while looking exactly like a scope bug.

---

## 6. Out of scope for this handoff

The cancel leg is audited and sound but still unclicked — see
`project_paddle_plans_verified_2026_07_18` in memory. **If cancel is exercised before
08-22, the conversion will not happen at all** (the subscription would end at period
end instead), so do not run both tests in the same week without deciding which one
matters more.
