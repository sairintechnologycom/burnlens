# BurnLens Troubleshooting

## Error: "Plan limit exceeded"

Your account is over its monthly request, token, spend, or active-key quota. Upgrade your plan from Account → Billing, or wait for the next billing cycle. Open-source local proxy has no limits — quotas apply only to cloud sync.

## Error: "Invalid API key"

The key in `~/.burnlens/config.yaml` was revoked or never existed. Run `burnlens login` to set a new one.

## Error: "Upstream provider returned 401"

Your provider's own API key (OpenAI, Anthropic, etc.) is invalid or expired. BurnLens forwards your provider key unchanged — it does not store or rotate it.

## Streaming responses are buffered or slow

The proxy forwards SSE chunks immediately. If you see buffering, it is almost always your HTTP client. Set `stream=True` in your SDK call and read iteratively.

## Dashboard shows "no data" but I made requests

Check three things: (1) is the proxy actually running? `curl http://127.0.0.1:8420/health`. (2) Did your requests hit `/proxy/<provider>/...` (not the upstream URL directly)? (3) Did the request complete? Failed requests with no response body are recorded but show $0.

## CLI command not found after pip install

Your Python user-site bin is not on PATH. Either install into a virtualenv, or add `python3 -m site --user-base`/bin to your PATH.
