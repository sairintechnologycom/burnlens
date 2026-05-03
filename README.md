# BurnLens — See exactly what your LLM API calls cost

`pip install burnlens` — open-source LLM FinOps proxy for OpenAI, Anthropic (Claude), and Google Gemini. Track real token costs, attribute spend to features, teams, and customers, and detect waste. Zero code changes. Everything runs locally.

[![PyPI](https://img.shields.io/pypi/v/burnlens?label=pypi&color=00e5c8)](https://pypi.org/project/burnlens)
[![Downloads](https://img.shields.io/pypi/dm/burnlens?label=downloads&color=00e5c8)](https://pypi.org/project/burnlens)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue)](https://python.org)
[![GitHub stars](https://img.shields.io/github/stars/sairintechnologycom/burnlens?style=social)](https://github.com/sairintechnologycom/burnlens)

> Zero code changes. Every dollar tracked. Works with the official OpenAI, Anthropic, and Google AI SDKs out of the box.

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

# Anthropic (Claude)
export ANTHROPIC_BASE_URL=http://127.0.0.1:8420/proxy/anthropic

# Google Gemini — one-line patch
import burnlens.patch; burnlens.patch.patch_google()
```

Your existing SDK code works unchanged. BurnLens intercepts, logs, and forwards — nothing else.

## Tag any request for attribution

```
X-BurnLens-Tag-Feature:  chat
X-BurnLens-Tag-Team:     backend
X-BurnLens-Tag-Customer: acme-corp
```

Tags are stripped before reaching the AI provider. They never leave your machine.

---

## Why BurnLens

- **OpenAI and Anthropic bill by model, not by feature.** You find out at month end which feature cost the most.
- **Reasoning tokens on o1 / o3 / Claude thinking models cost 10× more than expected.** One prompt change can balloon your bill.
- **One bad deploy can burn $47K before anyone notices.** Budget alerts catch it in minutes.

BurnLens fixes this at the proxy layer — no instrumentation, no SDK wrapping, no vendor lock-in.

---

## What you get

![BurnLens dashboard — LLM cost tracking by model, feature, team, and customer](https://burnlens.app/opengraph-image)

- **Cost timeline** — daily spend trend across all providers
- **Attribution** — cost by model, feature, team, customer
- **Waste detection** — context bloat, duplicate requests, model overkill
- **Per-request detail** — tokens, cost, and latency for every call
- **Budget alerts** — Slack + terminal notifications when you hit spend limits

---

## Supported providers

| Provider | Models |
|----------|--------|
| **OpenAI** | gpt-4o, gpt-4o-mini, o1, o3, o1-mini, gpt-4-turbo |
| **Anthropic (Claude)** | claude-opus-4, claude-sonnet-4, claude-3-5-sonnet, claude-3-haiku |
| **Google Gemini** | gemini-2.0-flash, gemini-1.5-pro, gemini-1.5-flash |

Reasoning tokens, cached tokens, and vision tokens are all tracked separately.

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

## Per-API-key daily kill-switch

Stop a leaked or runaway API key before it burns the month's budget.

```bash
# Register your provider key with a label and a $25/day hard cap
burnlens key register prod-openai --provider openai --cap 25.00

# Use the key normally — the proxy resolves it to its label, tracks
# today's spend, fires 50/80/100% alerts, and returns HTTP 429 at 100%
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=http://127.0.0.1:8420/proxy/openai/v1

# Inspect today's per-key roll-up
burnlens keys
```

- Keys are stored as SHA-256 hashes — never in plaintext.
- TZ-aware daily reset (UTC midnight by default, configurable).
- 100% breach returns `429 {"error": "burnlens_daily_cap_exceeded"}` until reset.
- Dashboard panel "API keys today" shows live status at `:8420/ui`.

---

## Offline scan — coding agent sessions

Already spent money in Claude Code, Cursor, Codex, or Gemini CLI? Import those session logs into the same dashboard without replaying any traffic:

```bash
burnlens scan claude    # ~/.claude/projects/ — JSONL session files
burnlens scan cursor    # ~/.cursor/ — SQLite bubble DB
burnlens scan codex     # ~/.codex/sessions/ — JSONL session files
burnlens scan gemini    # ~/.gemini/tmp/<project>/chats/ — JSON/JSONL
```

All four commands are idempotent — re-running them won't create duplicate rows. Imported records appear alongside live-proxy traffic in `burnlens top`, the dashboard, and exports.

---

## Configuration

Zero config required — sensible defaults out of the box. Optional `burnlens.yaml`:

```yaml
budget_limit_usd: 500.00
budgets:
  teams:
    backend: 200.00
    research: 100.00
alerts:
  slack_webhook: https://hooks.slack.com/...
```

---

## How it works

```
App → SDK → BurnLens proxy (localhost:8420) → AI provider
                 ↓
           SQLite: logs request, calculates cost, extracts tags
                 ↓
        Dashboard (localhost:8420/ui) + CLI (burnlens top/report)
```

- **Local-first.** Everything runs on localhost. No cloud account needed.
- **Privacy-preserving.** Prompts and completions never leave your machine. API keys pass through, never stored remotely.
- **Streaming passthrough.** SSE chunks forwarded immediately. < 20 ms proxy overhead.
- **Fail-open.** If BurnLens can't log, it still forwards the request. Never breaks your app.

---

## Cloud (optional)

Need team-wide dashboards and multi-workspace cost tracking? [BurnLens Cloud](https://burnlens.app) offers:

- **Free** — local proxy only (this repo)
- **Cloud — $29/mo** — personal cloud dashboard, 7-day trial
- **Teams — $99/mo** — multi-user workspaces, shared budgets

The CLI is free forever. Cloud is opt-in and only syncs anonymised cost records (tokens + cost — never prompts, completions, or API keys).

---

## Contributing

Issues and PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache License 2.0](LICENSE)
