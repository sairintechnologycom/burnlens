# CLAUDE.md — BurnLens Standing Orders

## Project Overview

BurnLens is an open-source LLM FinOps tool — a transparent proxy + CLI + dashboard that shows developers where their AI API money goes.

**One-liner:** `pip install burnlens && burnlens start` — zero code changes, see every LLM API call's real cost.

## Architecture — Three Zones

```
┌─────────────────────────────────────────────────────────────────┐
│  USER'S MACHINE (free, always)         pip install burnlens     │
│                                                                 │
│  App → SDK → BurnLens Proxy (localhost:8420) → AI Provider      │
│                  ↓                                              │
│            SQLite: log request, calculate cost, extract tags    │
│                  ↓                              ↓               │
│  Dashboard (localhost:8420/ui)    cloud.sync → POST /v1/ingest  │
│  CLI (burnlens top/report/analyze)    (every 60s, anonymised)   │
└───────────────────────────────────────────┬─────────────────────┘
                                            │ bl_live_xxx API key
                                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  RAILWAY (paid backend)            api.burnlens.app             │
│                                                                 │
│  POST /v1/ingest — receives sync batches, validates API key     │
│  Postgres — multi-tenant cost data keyed by api_key/org_id      │
│  REST API — serves cloud dashboard data                         │
│  Package: burnlens_cloud/ (this repo, never published to PyPI)  │
└───────────────────────────────────────────┬─────────────────────┘
                                            │
                                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  VERCEL (frontend)                 burnlens.app                 │
│                                                                 │
│  Next.js app — landing page, login, cloud dashboard UI          │
│  Auth (Auth.js or Clerk) — handles burnlens login flow          │
│  Stripe billing — plan management                               │
│  Writes bl_live_xxx API key to user's account on login          │
└─────────────────────────────────────────────────────────────────┘
```

### Zone 1: User's Machine (open-source proxy)
- **Proxy:** FastAPI reverse proxy. Intercepts via SDK BASE_URL env vars. Forwards requests unmodified, logs on response.
- **Storage:** SQLite with WAL mode. Zero external dependencies.
- **Dashboard:** Static HTML + Chart.js served by FastAPI. No React, no build step.
- **CLI:** Typer-based. Commands: start, stop, top, report, analyze, ui.
- **Cost Engine:** JSON pricing files per provider. Calculates cost from token usage in response.
- **Cloud Sync:** `burnlens/cloud/sync.py` batches anonymised records (hashes + token counts, never prompt content) and POSTs to Railway every 60s.
- **PyPI package:** `burnlens` (the only thing users install)

### Zone 2: Railway (SaaS backend)
- **Package:** `burnlens_cloud/` in this repo. Never published to PyPI — deployed as a private service.
- **Stack:** FastAPI + asyncpg + PostgreSQL
- **Deploys via:** `git push → Railway auto-builds → api.burnlens.app`
- **Why Railway over Lambda:** persistent Postgres connection pooling + always-on ingest endpoint, not ephemeral functions.
- **Core schema:** `org_id, ts, provider, model, tokens_in, tokens_out, cost_usd, tag_*`

### Zone 3: Vercel (frontend)
- **Stack:** Next.js at `burnlens.app`
- **Handles:** login (Auth.js or Clerk), cloud dashboard UI (org-wide spend), Stripe billing, `burnlens login` API key flow.
- **Talks to:** Railway REST API for all data.

### Money Flow
1. User runs `burnlens login` → browser opens Vercel login page
2. Vercel writes `bl_live_xxx` API key to their account
3. CLI stores key locally in `~/.burnlens/config.yaml`
4. Every sync batch includes the key → Railway validates → routes to org in Postgres

## Tech Stack

- Python 3.10+
- FastAPI + Uvicorn (proxy + dashboard server)
- httpx (async HTTP client for upstream forwarding)
- Typer + Rich (CLI)
- aiosqlite (async SQLite)
- PyYAML (config)
- Chart.js (dashboard charts, loaded from CDN)

## Key Design Principles

1. **Zero code changes for the user.** BurnLens works by setting BASE_URL env vars. The user's existing SDK code works unchanged.
2. **Local-first.** Everything runs on localhost. No cloud account needed. No data leaves the machine.
3. **Minimal latency.** Proxy must add < 20ms overhead. Log asynchronously after forwarding response. Never buffer streaming responses.
4. **Streaming passthrough.** SSE chunks must be forwarded immediately. Token counting happens from the final chunk or usage header, not by parsing every chunk.
5. **Fail open.** If BurnLens can't log or calculate cost, still forward the request. Never break the user's app.
6. **7 dependencies only.** Keep it lightweight. No heavy frameworks.

## Project Structure

```
burnlens/
├── pyproject.toml
├── README.md
├── LICENSE
├── CLAUDE.md                   ← You are here
├── burnlens.yaml.example
│
├── burnlens/
│   ├── __init__.py             # Version string
│   ├── __main__.py             # python -m burnlens entry point
│   ├── cli.py                  # Typer CLI commands
│   ├── config.py               # YAML config loader + defaults
│   │
│   ├── proxy/
│   │   ├── __init__.py
│   │   ├── server.py           # FastAPI app: proxy routes + dashboard serving
│   │   ├── interceptor.py      # Request/response interception + logging
│   │   ├── providers.py        # Provider URL mapping + routing config
│   │   └── streaming.py        # SSE streaming passthrough handler
│   │
│   ├── cost/
│   │   ├── __init__.py
│   │   ├── calculator.py       # Token usage → USD cost
│   │   ├── pricing.py          # Load/lookup pricing data
│   │   └── pricing_data/
│   │       ├── openai.json
│   │       ├── anthropic.json
│   │       └── google.json
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── database.py         # SQLite connection, migrations, WAL mode
│   │   ├── models.py           # Dataclasses for request records
│   │   └── queries.py          # Aggregation queries (by model, tag, time)
│   │
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── waste.py            # Waste detectors (bloat, duplicates, overkill, prompt waste)
│   │   ├── budget.py           # Budget tracking + forecasting
│   │   └── reports.py          # Report generation for CLI
│   │
│   ├── alerts/
│   │   ├── __init__.py
│   │   ├── engine.py           # Alert evaluation
│   │   ├── slack.py            # Slack webhook
│   │   └── terminal.py         # Terminal notification
│   │
│   └── dashboard/
│       ├── __init__.py
│       ├── routes.py           # JSON API endpoints for dashboard
│       └── static/
│           ├── index.html      # Single-page dashboard
│           ├── style.css
│           └── app.js          # Chart.js rendering
│
└── tests/
    ├── conftest.py             # Shared fixtures
    ├── test_proxy.py
    ├── test_cost.py
    ├── test_storage.py
    ├── test_analysis.py
    └── test_cli.py
```

## Provider Routing

Providers are a plugin architecture. Each provider is a single file in
`burnlens/providers/` that subclasses `Provider`. Adding a new provider
requires one new file there and one new `pricing_data/{key}.json` — no
core changes. See `docs/PROVIDERS.md` for the full guide.

Built-in providers:

| Provider | Upstream URL | Env Var | Proxy Path |
|----------|-------------|---------|------------|
| OpenAI | https://api.openai.com | OPENAI_BASE_URL | /proxy/openai |
| Anthropic | https://api.anthropic.com | ANTHROPIC_BASE_URL | /proxy/anthropic |
| Google | https://generativelanguage.googleapis.com | *(use burnlens.patch)* | /proxy/google |

**Adding a provider = one new file in `burnlens/providers/` + one new pricing JSON. No core changes required.**

## Request Flow (Critical Path)

1. SDK sends request to `localhost:8420/proxy/openai/v1/chat/completions`
2. Extract `X-BurnLens-Tag-*` headers → tags dict
3. Extract `model` from request body
4. Hash system prompt (for duplicate detection)
5. Record start time
6. Forward to `api.openai.com/v1/chat/completions` (strip BurnLens headers, keep auth)
7. **If streaming:** passthrough chunks immediately, accumulate usage from final chunk
8. **If non-streaming:** read full response
9. Extract usage from response (input_tokens, output_tokens, reasoning_tokens, cache tokens)
10. Calculate cost using pricing DB
11. Store to SQLite (async, non-blocking)
12. Check budget alerts (async, non-blocking)
13. Return original response to caller UNMODIFIED

## Coding Standards

- Type hints on all function signatures
- Docstrings on all public functions
- async/await for all I/O operations
- Use `httpx.AsyncClient` for upstream requests
- Use `aiosqlite` for database operations
- Error handling: log and continue, never crash the proxy
- Tests: pytest + pytest-asyncio

## Current Status

- **Open-source proxy (`burnlens`):** v1.0.0 on PyPI. Fully functional.
- **Cloud backend (`burnlens_cloud`):** v1.0.1. Deployed as private service on Railway. NOT on PyPI.
- **Frontend (`burnlens.app`):** Next.js on Vercel. Landing page live.

## Important Notes

- The proxy MUST NOT modify request or response bodies. It is transparent.
- The proxy MUST NOT buffer streaming responses. Forward each chunk immediately.
- Cost calculation happens from the `usage` field in the API response, NOT by counting tokens ourselves.
- If a model is not in the pricing DB, log the request with cost=0 and a warning, don't fail.
- SQLite database lives at `~/.burnlens/burnlens.db` by default.
- Config file is optional. Everything works with sensible defaults.

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke office-hours
- Bugs, errors, "why is this broken", 500 errors → invoke investigate
- Ship, deploy, push, create PR → invoke ship
- QA, test the site, find bugs → invoke qa
- Code review, check my diff → invoke review
- Update docs after shipping → invoke document-release
- Weekly retro → invoke retro
- Design system, brand → invoke design-consultation
- Visual audit, design polish → invoke design-review
- Architecture review → invoke plan-eng-review
- Save progress, checkpoint, resume → invoke checkpoint
- Code quality, health check → invoke health
