# BurnLens Support FAQ

## How do I install BurnLens?

Run `pip install burnlens` (requires Python 3.10+). Start the proxy with `burnlens start`. The dashboard is at http://127.0.0.1:8420/ui.

## How do I point my SDK at BurnLens?

Set the provider's BASE_URL env var to the matching BurnLens proxy path:

- OpenAI: `OPENAI_BASE_URL=http://127.0.0.1:8420/proxy/openai`
- Anthropic: `ANTHROPIC_BASE_URL=http://127.0.0.1:8420/proxy/anthropic`
- Google: call `burnlens.patch()` in your code (Google SDK does not honor an env var)

Existing SDK code works unchanged.

## Why does the dashboard show $0 for my requests?

Either (a) the model is not in the pricing JSON for that provider (a warning is logged — open an issue with the model name), or (b) the request is streaming and the upstream response did not include a final usage block.

## My proxy will not start — port 8420 is in use.

Run `burnlens stop` to kill any running instance, or pass `--port 9000` to `burnlens start` and update your BASE_URL accordingly.

## Cloud sync is not pushing data to burnlens.app.

Three checks: (1) is your API key valid? Run `burnlens whoami`. (2) Is sync enabled in `~/.burnlens/config.yaml`? (3) Are you over plan quota? Free tier has limits — see the Plans page.

## How do I rotate my API key?

See the Key Rotation Runbook in the docs. TL;DR: create a new key in the dashboard, copy it into `~/.burnlens/config.yaml`, restart the proxy, then revoke the old key.

## My budget cap is not blocking requests.

Budget enforcement is per-API-key, not per-tag. Check the key's cap in the dashboard. Tag-level budgets only trigger alerts — they do not 429.

## Does BurnLens send my prompts to the cloud?

No. The local proxy logs prompts only to your local SQLite at `~/.burnlens/burnlens.db`. Cloud sync sends token counts, costs, tags, and SHA hashes only — never prompt or response content.

## How do I cancel my plan?

Account → Billing → Cancel. Cancellation takes effect at the end of the current billing period.

## What providers are supported?

Stable: OpenAI, Anthropic, Google Gemini. Roadmap (v0.2–v0.3): Azure OpenAI, AWS Bedrock, Groq, Together, Mistral.

## I am getting 429 errors from BurnLens but not from the upstream provider.

That is your hard cap firing. Either raise the cap on the API key in the dashboard, or wait for the daily window to reset (UTC midnight).
