# BurnLens — The open-source FinOps proxy for AI spend

Track every dollar by feature, team, and customer across OpenAI, Anthropic, Google, Azure, AWS Bedrock, and Groq. Hard-cap budgets before the API call — not after the bill arrives.

[![PyPI](https://img.shields.io/pypi/v/burnlens?label=pypi&color=00e5c8)](https://pypi.org/project/burnlens)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue)](https://python.org)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/sairintechnologycom/burnlens?style=social)](https://github.com/sairintechnologycom/burnlens)

```bash
pip install burnlens
burnlens start
# Dashboard at http://127.0.0.1:8420/ui
```

---

## The Problem

**Bills tell you the model, not the why.** Your invoice says `gpt-4o: $4,287`. It doesn't say which feature, which team, or which customer burned it. By the time you trace the spike, it's already on next month's card.

**Alerts arrive after the damage.** A bad deploy, a runaway agent, or one abusive customer can trigger thousands of API calls before any dashboard turns red. You find out when you open the bill — or when your CEO does.

**Every provider is a different silo.** OpenAI's usage page. Anthropic's console. Azure Cost Management. Bedrock CloudWatch. No unified view, no way to ask "which feature is our biggest AI spend across all providers."

---

## How It Works

1. **Drop-in proxy.** Point your SDK's `BASE_URL` at `localhost:8420`. Existing code works unchanged. Less than 20ms overhead. Full streaming passthrough. No changes to your application logic.

2. **Tag what matters.** Three request headers (`X-BurnLens-Tag-Feature`, `X-BurnLens-Tag-Team`, `X-BurnLens-Tag-Customer`) attribute any call to any dimension. Tags are stripped before reaching the AI provider — they never leave your machine.

3. **Cap before you call.** Register an API key with a daily dollar limit. At 100%, BurnLens returns `429` *before* the upstream request is made — not after the bill arrives. 50% and 80% thresholds fire Slack or email alerts.

4. **One dashboard, every provider.** OpenAI, Anthropic, Google, Azure OpenAI, AWS Bedrock, and Groq spend in one unified view. Model breakdowns, waste detection, and budget tracking — reconciled to the provider bill.

---

## Code Example

```python
import os, openai

os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:8420/proxy/openai"

client = openai.OpenAI(default_headers={
    "X-BurnLens-Tag-Feature": "chat",
    "X-BurnLens-Tag-Team": "backend",
    "X-BurnLens-Tag-Customer": "acme-corp",
})
```

Tags are stripped before the request reaches OpenAI. They never appear in any API payload.

---

## Use Cases

**Coding agents.** Cursor, Claude Code, Cline, Windsurf — attribute cost per PR, repo, or developer. Set a hard daily cap per API key so one runaway agent can't blow the team's monthly budget overnight.

**Customer-facing AI.** Tag each request with a customer ID. See which customers drive the most cost. Enforce per-customer monthly spend limits with automatic 429 enforcement before the call is forwarded.

**RAG and agents.** Tag retrieval calls, tool calls, and generation separately. See whether your vector search or synthesis step is the cost driver — and whether it justifies the output quality.

**Internal tools.** Set per-team monthly budgets, get Slack alerts at 80% and 100%, and export monthly reports that reconcile line-by-line to the actual provider bill.

---

## Supported Providers

| Provider | Status | Notes |
|----------|--------|-------|
| OpenAI | Stable | All models, streaming, reasoning tokens |
| Anthropic | Stable | All models, streaming, prompt caching tokens |
| Google | Stable | Gemini 1.5/2.0, requires `patch_google()` |
| Azure OpenAI | Roadmap v0.3 | |
| AWS Bedrock | Roadmap v0.3 | |
| Groq | Roadmap v0.2 | |
| Together | Roadmap v0.2 | |
| Mistral | Roadmap v0.2 | |

---

## Why BurnLens

| | BurnLens | Helicone / Langfuse | Vantage / CloudZero |
|---|---|---|---|
| Open source | ✓ | Partial | ✗ |
| Local-first (prompts stay local) | ✓ | ✗ | ✗ |
| Hard caps before API call | ✓ | ✗ | ✗ |
| Per-customer attribution | ✓ | ✓ | ✗ |
| Multi-cloud (Azure / AWS / GCP) | ✓ | Partial | ✓ |

---

## Dashboard

![BurnLens dashboard — LLM cost tracking by model, feature, team, and customer](https://burnlens.app/opengraph-image)

---

## Configuration

Zero config required — sensible defaults out of the box. Optional `burnlens.yaml`:

```yaml
budget_limit_usd: 500.00
budgets:
  teams:
    backend: 200.00
    research: 100.00
  customers:
    acme-corp: 50.00
alerts:
  slack_webhook: https://hooks.slack.com/...
```

---

## CLI

```bash
burnlens start                  # proxy + dashboard on :8420
burnlens top                    # live cost by model (htop-style)
burnlens report                 # weekly cost summary
burnlens analyze                # waste detection report
burnlens export                 # CSV of last 7 days
burnlens run -- python app.py   # auto-tag a process with repo / dev / pr / branch
burnlens key register <name>    # label an API key + set a daily cap
burnlens key list               # list registered keys with caps
burnlens keys                   # today's spend per registered key
burnlens scan claude            # import Claude Code session costs from disk
burnlens scan cursor            # import Cursor IDE session costs from disk
burnlens scan codex             # import OpenAI Codex session costs from disk
burnlens scan gemini            # import Gemini CLI session costs from disk
```

---

## Contributing

Issues and PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
git clone https://github.com/sairintechnologycom/burnlens
cd burnlens
pip install -e ".[dev]"
pytest
```

## License

[Apache License 2.0](LICENSE)
