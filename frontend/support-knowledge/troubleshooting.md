# BurnLens Troubleshooting

## Error: "Plan limit exceeded" / "free_tier_limit"

Your cloud account is over its monthly request, token, spend, or active-key quota. Upgrade your plan from Account → Billing on burnlens.app, or wait for the next billing cycle. The open-source local proxy has no quota — limits apply only to cloud sync ingest.

## Error: "Invalid API key" on cloud sync

The key in `~/.burnlens/config.yaml` was revoked or never existed. Run `burnlens login` to set a new one.

## Error: "Upstream provider returned 401"

Your provider's own API key (OpenAI, Anthropic, etc.) is invalid or expired. BurnLens forwards your provider key unchanged — it never stores or rotates it. Fix the key in your environment or SDK config, not in BurnLens.

## Streaming responses are buffered or slow

The proxy forwards SSE chunks immediately and never buffers. If you see buffering, it is almost always your HTTP client doing it. Make sure `stream=True` is set in your SDK call and that you are reading the response iteratively.

## Dashboard shows "no data" but I made requests

Three checks:

1. Is the proxy actually running? `curl http://127.0.0.1:8420/health`.
2. Did your requests go through the BurnLens proxy URL (`/proxy/<provider>/...`), not directly to the upstream?
3. Did each request actually complete? Failed requests with no response body are recorded with `cost_usd=0` and may look like "nothing happened."

## CLI command not found after pip install

Your Python user-site `bin` directory is not on PATH. Two fixes:

- Install into a virtualenv (`python3 -m venv .venv && source .venv/bin/activate && pip install burnlens`), or
- Add the user-site bin to PATH: `export PATH="$(python3 -m site --user-base)/bin:$PATH"`.

## Model downgrade is replacing my requested model

That is a team or customer tag-level budget trigger. When a tag's spend crosses the configured threshold, BurnLens routes the request to a cheaper model instead of failing it. Disable downgrade in `burnlens.yaml` (`routing.disabled: true`) or raise the threshold if this is unwanted.
