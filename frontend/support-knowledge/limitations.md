# Known limitations

## Why does BurnLens publish its own limitations?

Because a cost tool is only worth what its worst number is worth. Every figure BurnLens shows has a boundary where it stops being authoritative, and a reader who does not know where that boundary is cannot use the number safely.

This page is that boundary, stated plainly. It is maintained alongside the code, not written once. Cost Confidence and Outcome Coverage report the same limits per workspace, with real figures.

## Unpriced models are valued at $0

If BurnLens has no price for a model, a request using it contributes nothing to your spend total. It is not estimated, guessed, or excluded — it is counted as zero dollars.

This is deliberate: inventing a price would put a fabricated number into a total that people make decisions from. But it means a spend figure can be understated by an unknown amount, and the amount is unknowable by definition.

**How to see it:** Cost Confidence reports unpriced requests as their own class and names each affected model as a coverage gap. Its headline percentage is counted by requests rather than dollars precisely so unpriced traffic cannot hide inside a dollar figure. Where an unpriced bucket appears, BurnLens shows "$ unknown" rather than "$0.00".

**Resolution:** report the model and it gets a price. The proxy can also be configured to refuse unpriced models outright rather than record them at $0.

## Scanned agent runs carry no prompt-segment breakdown

`burnlens scan` reconstructs cost history from coding-agent logs written to disk. Those logs record token totals but not how the prompt was composed, so the per-segment counts — system, tools, retrieved context, history — are all zero on scanned rows.

This is correct behaviour, not missing data. Scaling a partial request body up to the recorded token total was measured to inflate apparent history by 159% and fabricate thousands of dollars of waste that did not exist. Zero means "not observable from this source".

**Consequence:** the detectors that depend on prompt shape — oversized tool schemas, low retrieval efficiency, history bloat — are inert on scanned rows. They work on proxied traffic, where the request body is actually visible.

## Scanned token counts are self-reported

A scanned row's tokens come from what the agent wrote in its own log, not from a provider response observed on the wire. BurnLens classifies this spend as **estimated** rather than calculated for that reason, and says so in Cost Confidence.

In practice these counts are accurate. But they are the agent's account of itself, and BurnLens does not present them as measurement.

## Cost per outcome only sees tagged requests

Unit economics are computed from requests carrying a `workflow_id` tag. Untagged spend is not merely excluded from the numerator — it is invisible to the calculation entirely.

A workspace tagging a small fraction of its traffic will therefore see a confident-looking cost per outcome built on a small fraction of its money.

**How to see it:** Outcome Coverage reports untagged spend as its own figure and distinguishes it from spend that is tagged but has no outcome recorded, because the two have different fixes.

## Spend is only reconciled where a billing key is stored

Without a read-only billing key for a provider, BurnLens has never compared its figure for that provider against the actual bill. Such spend is reported as **calculated**, not verified, and the provider appears as a coverage gap.

The Anthropic Admin API is available only to Organization accounts. Individual accounts cannot obtain a cost-report key at all, so Anthropic spend on an individual account cannot be reconciled by any means.

## Reconciliation compares one day, once a day

The daily comparison covers the previous complete UTC day, not the current one, because provider billing lags and a same-day comparison reports drift that is only reporting delay. A drift figure therefore describes yesterday, not this moment.

## Savings verification measures a window, not a permanent state

A verdict compares cost per request over the week after a fix against a baseline snapshotted at the moment of the fix. It is evidence that the fix worked over that window. It is not a guarantee the saving persists, and a finding that reappears later is reported as reopened.

A subject with too little traffic in the measurement window is reported as **inconclusive** rather than assigned to either the win or the loss column.

## Waste categories overlap and must never be summed

A single request can be both context bloat and model overkill. The waste categories describe overlapping views of the same spend, so adding them together double-counts and produces a total larger than the waste that exists.

BurnLens never sums them, and neither should any report built on its output. For the same reason, spend does not partition into "useful plus waste plus errors" — those are overlapping lenses, not slices.

## Cached prompts are counted differently by different providers

OpenAI and Google fold cached prompt tokens *into* the reported input token count. Anthropic reports them as a separate, disjoint figure. A tool that applies one convention to both providers either double-counts or silently drops most of the prompt.

BurnLens handles both, but the consequence is worth knowing: for a coding agent, the uncached input tokens are a tiny fraction of the real prompt. An input-token figure shown alone in a cost context is misleading, so BurnLens does not show one.

## Hosted spend reflects what has been synced

The hosted dashboard shows what the local proxy has actually delivered. Plan limits cap how many requests sync per month, so a workspace over its cap will see a hosted total lower than its local one until the backlog clears or the cap is raised. The local database is always the complete record.
