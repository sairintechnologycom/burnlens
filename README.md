# BurnLens — The open-source FinOps proxy for AI spend

Track every dollar by feature, team, and customer across OpenAI, Anthropic, Google, Groq, Mistral, Together, xAI, DeepSeek, Azure OpenAI, and AWS Bedrock. Hard-cap budgets before the API call — not after the bill arrives.

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

1. **Drop-in proxy.** Point your SDK's `BASE_URL` at `localhost:8420`. Existing code works unchanged. The proxy is designed for low overhead and supports streaming passthrough.

2. **Tag what matters.** Request headers (`X-BurnLens-Tag-Feature`, `X-BurnLens-Tag-Team`, `X-BurnLens-Tag-Customer`, plus `X-BurnLens-Tag-Agent-Id` and `X-BurnLens-Tag-Workflow-Id` for agent workloads) attribute any call to any dimension. Tags are stripped before the request reaches the AI provider. If you enable cloud sync, tag values are uploaded to your workspace alongside cost metadata — never prompt or response bodies.

3. **Cap before you call.** Register an API key with a daily dollar limit. At 100%, BurnLens returns `429` *before* the upstream request is made — not after the bill arrives. 50% and 80% thresholds fire Slack or email alerts. Exact behaviour under concurrency, streaming, retries, and unpriced models is specified in [Budget enforcement semantics](docs/BUDGET_ENFORCEMENT.md).

4. **One dashboard for supported providers.** OpenAI, Anthropic, Google, Groq, Mistral, Together, xAI, DeepSeek, Azure OpenAI, and AWS Bedrock spend in one unified view. Model breakdowns, waste detection, and budget tracking use versioned provider pricing.

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

Tags are stripped before the request reaches OpenAI. They never appear in the provider API payload.

**Agent workloads.** Tag with `X-BurnLens-Tag-Agent-Id` and `X-BurnLens-Tag-Workflow-Id` to get cost per agent and cost per workflow instead of only cost per model:

```python
client = openai.OpenAI(default_headers={
    "X-BurnLens-Tag-Agent-Id": "refund-agent",
    "X-BurnLens-Tag-Workflow-Id": "refund_review",
})
```

Break spend down with `GET /api/costs/by-tag?tag=agent_id` locally, or `GET /api/v1/usage/by-tag?tag_type=agent_id` on BurnLens Cloud. Tool and function calls are counted per request, so a looping agent shows up as tool-call volume rather than just a larger bill.

Multi-word tag headers accept either spelling — `X-BurnLens-Tag-Agent-Id` or `X-BurnLens-Tag-Agent_Id`. Prefer the hyphenated form: nginx drops headers containing underscores unless `underscores_in_headers` is on.

---

## Cost per accepted outcome

Spend alone doesn't tell you whether it was worth it. Report what a workflow *produced* and BurnLens divides one by the other:

```bash
burnlens outcome record --workflow refund_review --status accepted --id ticket-8412
burnlens outcome show
```

```text
 Workflow        Accepted  Rejected/Failed  Total cost  Rework   Unattributed  Per accepted
 refund_review   780       140              $18.40      $3.20    $1.10         $0.0236
```

From an application, post outcomes to BurnLens Cloud instead:

```bash
curl -X POST https://api.burnlens.app/v1/outcomes \
  -H "X-API-Key: $BURNLENS_API_KEY" \
  -d '{"outcomes":[{"outcome_id":"ticket-8412","workflow_id":"refund_review",
                    "status":"accepted","event_time":"2026-08-09T12:00:00Z"}]}'
```

Three things worth knowing about the number:

- **`outcome_id` is yours and it is the idempotency key.** Re-posting the same one is ignored, so at-least-once delivery and importer re-runs can't inflate the count that the cost is divided by.
- **Per accepted = total workflow spend / accepted outcomes.** Failed and rejected attempts are charged to the successes, because that is what one working result actually costs. The `Rework` column shows how much of it was spent on attempts that didn't land.
- **Unattributed spend is shown, not hidden.** A request is charged to the first outcome of its workflow that follows it within a window (24h by default, `--window` to change). Spend with no outcome after it stays visible in its own column rather than quietly disappearing from the denominator.

A workflow with spend and no accepted outcomes reports no unit cost at all rather than `$0` — the absence is the signal.

### Coding agents: no instrumentation required

For agent work you don't have to report anything. A merged pull request already *is* an accepted outcome, and a closed-unmerged one is a rejected outcome — so BurnLens reads them out of GitHub and joins them to the agent spend it scanned off disk:

```bash
burnlens scan --provider claude     # agent session cost, from local logs
burnlens outcome derive             # merged PRs -> outcomes, via the gh CLI
burnlens outcome show               # cost per merged PR
```

Measured on this repository while building it: **81 merged PRs, $407 of Claude Code spend, about $5.03 per merged PR.** (A floor, not a ceiling — any model missing from the pricing tables contributes $0, so check `burnlens pricing` if a number looks low.)

Both commands are idempotent and safe on a schedule: outcome ids are derived deterministically from the repo and PR number, so re-running only ever adds newly-closed PRs.

Cost is attributed per repository rather than per PR, because agent session logs record which repo a session ran in, not which branch. With several PRs in flight that is the honest reading of what one merged PR costs.

---

## Use Cases

**Coding agents.** Cursor, Claude Code, Cline, Windsurf — attribute cost per PR, repo, or developer. Set a hard daily cap per API key so one runaway agent can't blow the team's monthly budget overnight.

**Customer-facing AI.** Tag each request with a customer ID. See which customers drive the most cost, alert on thresholds, and optionally route to cheaper models.

**RAG and agents.** Tag retrieval calls, tool calls, and generation separately. See whether your vector search or synthesis step is the cost driver — and whether it justifies the output quality.

**Internal tools.** Set per-team monthly budgets, get Slack alerts at 80% and 100%, and export monthly records for comparison with provider invoices.

---

## Supported Providers

| Provider | Status | Notes |
|----------|--------|-------|
| OpenAI | Stable | All models, streaming, reasoning tokens |
| Anthropic | Stable | All models, streaming, prompt caching tokens |
| Google | Stable | Gemini 1.5–2.5 (+ 3.x previews), requires `patch_google()`; Gemini 2.5 / 3.1 Pro switch to their higher long-context rate above 200K input tokens |
| Groq | Beta | OpenAI-compatible: point `GROQ_BASE_URL` at `/proxy/groq` |
| Together | Beta | OpenAI-compatible: set client `base_url` to `/proxy/together` |
| Mistral | Beta | OpenAI-compatible: set client `base_url` to `/proxy/mistral` |
| xAI | Beta | OpenAI-compatible: point `XAI_BASE_URL` at `/proxy/xai` |
| DeepSeek | Beta | OpenAI-compatible: point `DEEPSEEK_BASE_URL` at `/proxy/deepseek` |
| Azure OpenAI | Beta | Point client `azure_endpoint` at `/proxy/azure`; set `BURNLENS_AZURE_ENDPOINT` to your resource URL |
| AWS Bedrock | Beta | Claude models; Bedrock API key (`Authorization: Bearer`, no SigV4); set `BURNLENS_BEDROCK_REGION`; Global cross-region pricing |

Pricing covers current text/chat models for the supported providers, plus
audio-modality tokens (OpenAI `*-audio-preview` / `*-realtime-preview`, billed at
their own per-million rate) and arbitrary flat per-unit fees via each model's
optional `unit_prices` (e.g. per web-search call). Image and video generation are
still out of scope. Gemini Pro's higher rate above 200K input tokens is applied
automatically (tiered pricing, since v1.12.0). Audio rates should be re-checked
against the provider pricing page — they change less often than text but do move.

---

## Why BurnLens

| | BurnLens | Helicone / Langfuse | Vantage / CloudZero |
|---|---|---|---|
| Open source | ✓ | Partial | ✗ |
| Local-first (prompt bodies never pass through the vendor) | ✓ | ✗ | ✗ |
| Hard caps before API call | ✓ | ✗ | ✗ |
| Per-customer attribution | ✓ | ✓ | ✗ |
| Multi-cloud (Azure / AWS / GCP) | Partial | Partial | ✓ |

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
