# BurnLens Support FAQ

## How do I install BurnLens?

Run `pip install burnlens` (requires Python 3.10+). Start the proxy with `burnlens start`. The dashboard is at http://127.0.0.1:8420/ui.

## How do I point my SDK at BurnLens?

Set the provider's BASE_URL env var to the matching BurnLens proxy path:

- OpenAI: `OPENAI_BASE_URL=http://127.0.0.1:8420/proxy/openai`
- Anthropic: `ANTHROPIC_BASE_URL=http://127.0.0.1:8420/proxy/anthropic`
- Google: import and call `patch_google()` in your code (the Google SDK does not honor an env var):

  ```python
  from burnlens.patch import patch_google
  patch_google()
  ```

Existing SDK code works unchanged after this.

## Why does the dashboard show $0 for my requests?

Either (a) the model is not in the pricing JSON for that provider (a warning is logged — open an issue with the model name), or (b) the request was streaming and the upstream response did not include a final usage block.

## How do I stop the proxy?

Press Ctrl+C in the terminal running `burnlens start`. If you launched it in the background, find the process with `ps aux | grep burnlens` and stop it with `kill <pid>`.

## My proxy will not start — port 8420 is in use.

Stop whatever is bound to that port, or pass a different port to `burnlens start` (see `burnlens start --help`) and update your BASE_URL accordingly.

## Cloud sync is not pushing data to burnlens.app.

Three things to check:

1. Is your API key set? Look in `~/.burnlens/config.yaml`. If missing, run `burnlens login`.
2. Is sync enabled in `~/.burnlens/config.yaml`?
3. Are you over your plan quota? Free tier is capped at 10,000 records per month — see the Plans page on burnlens.app.

## How do I rotate my API key?

See the Key Rotation Runbook in the docs. The short version: create a new key in the cloud dashboard, copy it into `~/.burnlens/config.yaml`, restart the proxy, then revoke the old key from the dashboard.

## How do budget caps actually work?

Two different mechanisms:

- **Per-API-key daily caps** (in the local proxy): when a key hits 100% of its daily dollar limit, BurnLens returns `429` *before* forwarding the request to the upstream provider. The daily window resets at local midnight in your configured timezone.
- **Per-team / per-customer budgets** (tag-level): when usage crosses configured thresholds, BurnLens automatically downgrades the requested model to a cheaper one (configurable). They do not 429.

## Does BurnLens send my prompts to the cloud?

No. The normal local request log stores cost metadata and prompt fingerprints, not prompt bodies. Cloud sync sends token counts, costs, model names, opted-in tags, and a workspace-keyed HMAC-SHA256 prompt fingerprint — never prompt or response content. See `burnlens/cloud/sync.py` for the exact payload schema.

## How do I cancel my plan?

Open the cloud dashboard → Account → Billing → Cancel. Cancellation takes effect at the end of the current billing period.

## What providers are supported?

Eight providers today: OpenAI, Anthropic, Google Gemini (via `patch_google()`), Groq, Together, Mistral, Azure OpenAI, and AWS Bedrock (Claude models, Bedrock API key). OpenAI, Anthropic, and Google are stable; the rest are beta.

## I am getting 429 errors from BurnLens but not from the upstream provider.

That is your per-key daily cap firing. Either raise the cap on the API key in the dashboard, or wait for the daily window to reset (local midnight in your configured timezone).
