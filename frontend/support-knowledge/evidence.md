# Cost evidence in BurnLens

## What is Cost Confidence?

Cost Confidence answers a question a spend total cannot: how much of that number BurnLens can actually stand behind. It appears on the dashboard under the spend figures.

Every request is placed in one of four classes:

- **Provider verified** — BurnLens compared its own figure against that provider's billing API for the most recent day and the two agreed inside the drift threshold.
- **Pricing calculated** — priced from the pricing table. Correct as far as the table goes, but never checked against a bill.
- **Estimated** — rebuilt from a coding agent's local logs by `burnlens scan`. The token counts are real, but the agent reported them about itself; nothing measured them on the wire.
- **Unpriced** — tokens were used and BurnLens has no price for the model, so the request contributes $0.

The headline percentage is the share of **requests** in any class except unpriced.

## Why is Cost Confidence counted by requests instead of dollars?

Because unpriced requests contribute $0 to the total. A dollar-weighted figure would report 100% confidence on a workspace whose single most expensive model has no price at all — it would be blind to exactly the failure it exists to expose.

The panel also shows a second figure, "% of known spend provider-verified", which *is* dollar-weighted. The two answer different questions:

- **By request** — is the workload being priced comprehensively?
- **By dollar** — of the money we do have a figure for, how much has been verified against a bill?

One unpriced call can be worth more than ninety-nine thousand priced ones, so neither number replaces the other.

## Is Cost Confidence a score?

No, and deliberately so. It is a plain ratio with no per-class weighting. A weighted index — reconciled counting 1.0, estimated counting 0.75 — would not be auditable by anyone outside BurnLens. The four class figures are published separately so you can weigh a calculated dollar against a verified one yourself.

## What are coverage gaps?

Underneath the confidence bar, BurnLens lists every specific reason some spend is less than fully trustworthy: each model it has no price for, and each provider with spend but no billing key stored, a stale comparison, or drift outside the threshold. A gap names the provider and model and the number of affected requests, so it is actionable rather than a warning.

## How do I connect a provider billing key?

Go to **Settings → Cost reconciliation** and paste a read-only billing key for the provider. Owner role required.

- **Anthropic** — an Admin API key (`sk-ant-admin…`) or an OAuth token, with cost report access. The Admin API is only available to Organization accounts; individual accounts cannot use it.
- **OpenAI** — an organization key with `api.usage.read`.

BurnLens proves the key works against the provider before storing it, so a key that is expired or lacks scope is rejected immediately with the provider's own reason rather than being saved and failing silently later. Keys are encrypted at rest and are never returned by any endpoint. Remove one at any time from the same screen.

Once a key is stored, BurnLens compares its own daily figure against that provider's bill once a day and reports the drift.

## What does drift mean, and is it a failure?

Drift is the signed percentage BurnLens differs from the provider's own bill. Negative means BurnLens counted less than the invoice, which is the normal direction.

Drift is a diagnosis, not a fault. The usual causes are calls that never went through the proxy, a provider pricing change BurnLens has not picked up yet, an unpriced model, and rounding. Drift above 2% flips the badge and raises an alert.

## What is Outcome Coverage?

Cost per outcome is only as good as the share of spend it can see. Outcome Coverage reports that share, by dollar, and splits what is missing into two groups because they have different fixes:

- **Tagged, no outcome** — the request carried a `workflow_id` but no outcome was ever posted for it inside the allocation window. Post the outcome and this spend moves.
- **No workflow tag** — the request carried no `workflow_id` at all, so it can never be attributed to anything. Tag the caller.

The second group matters most: cost-per-outcome is computed only from tagged requests, so a workspace tagging 5% of its traffic gets a confident-looking unit cost built on 5% of its money. Outcome Coverage is what makes that visible.

## Why is Outcome Coverage weighted by dollars when Cost Confidence is weighted by requests?

They ask different things. Cost Confidence asks whether the workload is being priced comprehensively, and unpriced requests are invisible in dollars. Outcome Coverage asks what share of the *money* bought something nameable, and a cheap request that produced an outcome is not worth the same as an expensive one that did not.

## What are Verified Savings?

A projected saving is a claim. A verified saving is one that showed up in traffic.

When you resolve a waste finding, BurnLens snapshots a baseline — cost and request count over the preceding window — and then measures the same subject over the following week. Verdicts are:

- **Verified** — cost per request fell.
- **Missed** — the fix landed and cost per request did not fall. The projection did not materialise.
- **Inconclusive** — too few requests after the fix to judge it either way.
- **Still verifying** — the measurement window has not elapsed yet.

The `/savings` page rolls these up: what is projected but not yet acted on, what was predicted for fixes that were made, what was verified, and what was missed.

## Why does BurnLens compare cost per request instead of total spend?

Because total spend is trivially gamed by traffic volume. A workload that halves its traffic at the same unit cost shows a 50% drop in totals while the fix did nothing at all. Worse, a workload that stops entirely reads as a 100% saving.

BurnLens compares cost per request, never totals, and reports a subject with no traffic after the fix as `no_traffic` rather than a win.

## Why does the realised percentage show a dash instead of 0%?

Because nothing has been judged yet. A ratio over an empty denominator is undefined, and printing 0% would read as "every fix failed" — the opposite of "no fix has reached a verdict".

Once at least one fix reaches a verified or missed verdict, the figure appears. Missed fixes count toward the denominator and contribute nothing to the numerator, which is what makes the ratio worth reading rather than a restatement of the original projection.
