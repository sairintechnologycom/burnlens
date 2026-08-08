# Budget enforcement semantics

What BurnLens guarantees when a budget is hit, and what it does not. Written
against the code, not the marketing copy: every claim below cites the function
that implements it.

Read this before putting BurnLens in front of production traffic.

- `burnlens/proxy/interceptor.py` — the pipeline; where each check runs
- `burnlens/key_budget.py` — per-API-key daily caps
- `burnlens/budget_engine.py` — budget policies (reserve/reconcile)
- `burnlens/proxy/router.py` — budget-aware model downgrade

---

## Order of checks

Every proxied request runs these in order. The first one that rejects wins;
nothing after it executes.

| # | Check | On breach | Source |
|---|---|---|---|
| 1 | Virtual-key allowed-models | `403 model_not_allowed` | `interceptor.py:470` |
| 2 | Virtual-key monthly team budget | `429 team_budget_exceeded` | `interceptor.py:477` |
| 3 | **Per-API-key daily cap** | `429 daily_budget_exceeded` | `interceptor.py:524` |
| 4 | Customer budget | `429 budget_exceeded` | `interceptor.py:543` |
| 5 | Semantic cache lookup | returns cached response, **skips 6 and 7** | `interceptor.py:589` |
| 6 | Budget-aware model downgrade | swaps model, never blocks | `interceptor.py:652` |
| 7 | **Budget policies** (reserve) | `429 budget_policy_exceeded` | `interceptor.py:690` |
| 8 | Forward upstream | — | `interceptor.py:719` |

All rejections happen **before** the upstream request is sent. A 429 from
BurnLens means no provider call was made and nothing was billed.

---

## Two different mechanisms

BurnLens has two budget systems with materially different correctness
properties. Knowing which one you configured matters.

### A. Per-API-key daily caps — eventually consistent

Configured with `burnlens key register` plus an entry in
`alerts.api_key_budgets`. Implemented by `enforce_daily_cap`
(`key_budget.py:150`).

**No reservation.** The check is `spent >= daily_cap`, where `spent` is the sum
of *already-recorded* request costs. The in-flight request's own cost is not
estimated or reserved. Consequence: the request that crosses the cap is
forwarded and billed; the *next* one is blocked.

**30-second read cache.** `SpendCache` (`key_budget.py:101`) caches spend per
label for 30s. The entry is invalidated whenever a request is logged
(`interceptor.py:334`), so in steady traffic the cached value is fresh. A cap
raised or lowered out of band can take up to 30s to take effect.

**Concurrent requests overshoot.** There is no lock spanning check → forward →
log. N requests issued together all read the same `spent` and all pass. Worst
case overshoot is roughly `concurrency × cost_of_largest_in_flight_request`.
If you need a strict ceiling, set the cap below your true limit by that margin.

**Opt-in only.** Unregistered keys (`label is None`) are never blocked. They
still record cost — they just pass through. This is deliberate
(`key_budget.py:16`), and it means enabling BurnLens does not silently start
rejecting traffic.

### B. Budget policies — reserved, serialized, reconciled

Configured as `budget_policies` in `burnlens.yaml`. Implemented by
`BudgetEngine.check_and_reserve` (`budget_engine.py:185`).

**Real reservation.** The request's cost is estimated, checked as
`current_spend + estimated > limit_usd`, and — if allowed — added to
`budget_counters` inside an `asyncio.Lock` and a DB transaction before the
request is forwarded. After the response, `reconcile` (`budget_engine.py:258`)
applies `actual - estimated` so the counter converges on truth.

**Reservations are refunded on failure.** All three response paths reconcile:
non-streaming success and error (`interceptor.py:864`, `:1062`) and streaming
(`interceptor.py:1205`). Responses with status >= 400 reconcile to `0.0`, so a
failed request does not consume budget.

**The lock is per-process.** `asyncio.Lock` on a `BudgetEngine` instance
serializes within one proxy process only. Two proxy processes against the same
SQLite file can both pass the check concurrently.

**Estimation is coarse.** `estimate_request_tokens` (`budget_engine.py:18`)
counts input as `characters / 4` and takes output from `max_tokens` /
`max_completion_tokens`, defaulting to 1000 when absent and 100/1000 when the
body will not parse. Under-estimating output means a policy can be crossed by
the reconciled amount; the overshoot is corrected on the next request.

---

## Specific questions

### What happens at 50%, 80%, 100%?

Enforcement is binary at 100% — there is no throttling below the limit. The
sub-limit thresholds are alerting and status only:

- 50% and 80% fire Slack/email alerts.
- `compute_keys_today` (`key_budget.py:182`) reports `OK` (<80%),
  `WARNING` (80–99%), `CRITICAL` (>=100%), `NO_CAP` (no cap configured).

Model downgrade (below) is the one graduated response, and it is configured
separately from the cap.

### Concurrent requests

Neither mechanism is strictly race-free. Daily caps have no reservation at all;
budget policies reserve under a lock that covers a single process. Size caps
with headroom rather than treating them as a hard ceiling under high
concurrency.

### Streaming responses that cross the limit mid-stream

Not interrupted. The cap is evaluated before the request is sent; once a stream
is open it runs to completion and the full cost is recorded at stream end. A
single long stream can therefore exceed the cap by its own cost.

### Estimated vs finalized cost

Daily caps use finalized cost only (no estimate). Budget policies use an
estimate to reserve, then reconcile to the finalized cost. Between forward and
reconcile, a policy counter is wrong by `estimated - actual`.

### Unknown models

`calculate_cost` returns `0.0` and logs a warning when the model is absent from
the pricing data (`cost/calculator.py:52`). Two consequences:

- Spend for that model contributes nothing to any cap. A cap will not trip on
  traffic BurnLens cannot price.
- In `check_and_reserve`, `estimated_cost <= 0.0` returns *allowed* immediately
  (`budget_engine.py:204`) without consulting any policy — an unpriced model
  bypasses budget policies entirely.

Check `burnlens pricing` covers every model you route before relying on a cap.
Unpriced traffic is unenforced traffic.

### Provider retries

`RetryConfig` retries only statuses that mean the request was never processed —
`retry.retry_on_status` (default `{429, 503}`, `config.py:167`) plus
connection-level errors. Read timeouts are deliberately *not* retried, because
the request may have reached the provider (`interceptor.py:246`). Retries
cannot double-bill and do not re-consume budget.

Retries run inside the upstream call (`interceptor.py:790`), which is after
every budget check. A retried request is not re-checked against the cap.

### Cache hits

A semantic or exact cache hit returns at `interceptor.py:646` / `:648`, which
is **before** model downgrade and the budget-policy reservation. A cache hit
therefore consumes no budget-policy allowance. It is still subject to checks
1–4, which run earlier. Cache hits record `cost_usd = 0.0` plus
`cache_saved_usd` (`interceptor.py:1523`), so they do not advance daily-cap
spend either.

### Budget reset timezone

Daily caps reset at local midnight in `api_key_budgets.reset_timezone`
(`key_budget.py:66`). An unresolvable timezone name falls back to UTC with a
logged warning rather than failing the request (`key_budget.py:49`).

Budget policies use a different clock: `_get_period_start`
(`budget_engine.py:92`) computes daily/weekly/monthly boundaries in **UTC
only**, ignoring `reset_timezone`. Weekly periods start Monday.

### Fail-open vs fail-closed

Budget checks fail **open**. If the cap lookup, customer-budget query, or
policy check raises, the error is logged at debug level and the request is
forwarded (`interceptor.py:529`, `:481`, `:716`). A corrupt or locked database
degrades to no enforcement, not to an outage.

The one fail-**closed** path is a virtual key whose `upstream_key_env` is
missing: that returns `503 gateway_misconfigured` rather than forwarding
without credentials (`interceptor.py:495`).

### Cloud disconnection

Enforcement is entirely local. Caps read the local SQLite database and never
consult BurnLens Cloud, so a cloud outage or an unconfigured workspace has no
effect on whether requests are blocked. Cloud sync only ships already-recorded
metadata.

### Budget-aware model downgrade

Distinct from capping. When a tag's spend crosses a configured routing
threshold, `decide_route` (`interceptor.py:652`) rewrites the request to a
cheaper model instead of rejecting it. The request still goes upstream and
still costs money. The response records `routed_model`, `downgrade_reason`,
and remaining budget. Disable with `routing.disabled: true` in
`burnlens.yaml`.

---

## Known ceilings

Documented rather than fixed, in rough order of how likely they are to bite:

1. **Unpriced models are unenforced** — and silently bypass budget policies.
   The most likely way to think you are capped and not be.
2. **Concurrent overshoot** — no reservation on daily caps; policy lock is
   per-process.
3. **Streams are not interrupted mid-flight.**
4. **Budget policies ignore `reset_timezone`** and always use UTC period
   boundaries, unlike daily caps.
5. **Multi-process deployments** weaken the budget-policy lock to per-process.
