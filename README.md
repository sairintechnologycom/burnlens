# BurnLens

> See exactly what your LLM API calls cost — per feature, team, and customer.  
> Zero code changes. Everything local.

[![PyPI](https://img.shields.io/pypi/v/burnlens)](https://pypi.org/project/burnlens)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue)](https://python.org)

---

## Install

```bash
pip install burnlens
burnlens start
# Dashboard → http://127.0.0.1:8420/ui
```

## Point your SDK at the proxy

```bash
# OpenAI
export OPENAI_BASE_URL=http://127.0.0.1:8420/proxy/openai

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

![Dashboard screenshot](docs/dashboard.png)

- **Cost timeline** — daily spend trend across all providers
- **Attribution** — cost by model, feature, team, customer
- **Waste alerts** — context bloat, duplicate requests, model overkill
- **Per-request detail** — tokens, cost, and latency for every call

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
