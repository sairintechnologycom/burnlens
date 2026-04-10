# BurnLens

> See exactly what your LLM API calls cost — per feature, team, and customer.  
> Zero code changes. Everything local.

**Works with streaming. Sub-20ms overhead. Nothing leaves your machine.**

[![PyPI](https://img.shields.io/pypi/v/burnlens)](https://pypi.org/project/burnlens)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue)](https://python.org)

<p align="center">
  <img src="docs/burnlens.gif" alt="BurnLens dashboard demo" width="800">
</p>

---

## Install

```bash
pip install burnlens
burnlens start
# Dashboard → http://127.0.0.1:8420/ui
```

## Point your SDK at the proxy

```bash
# OpenAI — note the /v1 suffix
export OPENAI_BASE_URL=http://127.0.0.1:8420/proxy/openai/v1

# Anthropic
export ANTHROPIC_BASE_URL=http://127.0.0.1:8420/proxy/anthropic

# Google (one import instead of env var)
import burnlens.patch; burnlens.patch.patch_google()
```

Your existing SDK code works unchanged. BurnLens intercepts, logs, and forwards — nothing else.

## Tag any request for attribution

```
X-BurnLens-Tag-Feature: chat
X-BurnLens-Tag-Team:    backend
X-BurnLens-Tag-Customer: acme-corp
```

Tags are stripped before reaching the AI provider. They never leave your machine.

---

## The problem

- OpenAI bills by model, not by feature. You find out at month end.
- Reasoning tokens on o1/o3 can cost 10× more than expected.
- One bad deploy can cost $47K before anyone notices.

BurnLens fixes this at the proxy layer — no instrumentation, no SDK wrapping, no vendor lock-in.

---

## What you get

- **Cost timeline** — daily spend trend across all providers
- **Attribution** — cost by model, feature, team, customer
- **Waste alerts** — context bloat, duplicate requests, model overkill
- **Per-request detail** — tokens, cost, and latency for every call
- **Streaming support** — SSE passthrough with zero buffering, token counting from final chunk

---

## Providers

| Provider | Models |
|----------|--------|
| OpenAI | gpt-4o, gpt-4o-mini, o1, o3, o1-mini, and more |
| Anthropic | claude-3-5-sonnet, claude-3-haiku, claude-opus-4-6, and more |
| Google | gemini-1.5-pro, gemini-1.5-flash, gemini-2.0-flash, and more |

---

## CLI

```bash
burnlens start         # proxy + dashboard
burnlens export        # CSV of last 7 days
burnlens report        # weekly cost summary
burnlens recommend     # cheaper model suggestions
burnlens budgets       # team spend vs limits
```

---

## How BurnLens compares

| | BurnLens | Helicone | LangSmith | Portkey |
|---|---|---|---|---|
| **Setup** | `pip install`, set env var | Cloud signup + API key | Cloud signup + SDK wrapper | Cloud signup + gateway |
| **Data privacy** | 100% local, SQLite on your machine | Cloud-hosted | Cloud-hosted | Cloud-hosted |
| **Cost** | Free, open source | Free tier, then paid | Free tier, then paid | Free tier, then paid |
| **Streaming** | Full SSE passthrough, zero buffering | Yes | Yes | Yes |
| **Code changes** | None — proxy via `BASE_URL` | SDK integration | SDK wrapper required | Gateway config |

---

## FAQ

**Does it support streaming?**
Yes. SSE chunks are forwarded immediately with zero buffering. Token counting happens from the final chunk or usage header.

**What's the performance overhead?**
Sub-20ms. Logging and cost calculation happen asynchronously after the response is forwarded.

**Where's my data?**
SQLite on your machine (`~/.burnlens/burnlens.db`). Nothing leaves localhost. No cloud account needed.

**What providers are supported?**
OpenAI, Anthropic, and Google. Set `BASE_URL` env vars and your existing SDK code works unchanged.

**Can I run it in Docker?**
Not yet — coming soon. For now it runs directly via `pip install burnlens`.

---

## Configuration

```yaml
# burnlens.yaml (optional — sensible defaults without it)
budget_limit_usd: 500.00
budgets:
  teams:
    backend: 200.00
    research: 100.00
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and PRs welcome.

## License

MIT
