# Current State Specification — BurnLens

## 1. CLI Commands (Typer-based)

Run via `burnlens <command>`:

- `start` — Run the FastAPI proxy and dashboard server on `localhost:8420`.
- `stop` — Stop the running proxy daemon.
- `top` — Display a real-time terminal monitor of model costs and request volume.
- `report` — Output a summary report of AI spend for the specified period.
- `analyze` — Run waste analysis (e.g., prompt bloat, duplicate detection) on the local database.
- `scan` — Scan retroactive CLI history or log files to ingest past calls.
- `keys` — Manage registered API keys and daily budgets.
- `login` — Link the local proxy to a `burnlens.app` SaaS account using an API key.
- `export` — Export cost data to CSV or JSON format.
- `doctor` — Run diagnostic checks on proxy ports, database files, and config.

---

## 2. Dashboard Pages (Next.js & local HTML)

Served at `http://localhost:3000` (Next.js dev) or `/ui/` on the proxy:

- **Dashboard / Overview** — Spending overview, daily cost trends, recent requests, and KPI summary.
- **Timeline** — Detailed time-series trend of spend and request counts.
- **Requests** — List of all intercepted requests with latency, tokens, cost, and tags.
- **Waste Detection** — Actionable alerts highlighting duplicate calls, prompt bloat, and overkill models.
- **Recommendations** — Model optimization suggestions based on usage patterns.
- **Budgets** — Global, team, and customer budget status with warning/limit indicators.
- **Models** — Spend and request count breakdowns grouped by AI model.
- **Features** — Spend attributed to custom feature tags (`X-BurnLens-Tag-Feature`).
- **Teams** — Spend attributed to custom team tags (`X-BurnLens-Tag-Team`).
- **Customers** — Spend attributed to custom customer tags (`X-BurnLens-Tag-Customer`).
- **Settings** — Local configuration, Slack webhooks, and cloud synchronization options.

---

## 3. Local API Endpoints (localhost:8420)

### Proxy Paths
- `ANY /proxy/openai/{path:path}` — Forward to `api.openai.com`.
- `ANY /proxy/anthropic/{path:path}` — Forward to `api.anthropic.com`.
- `ANY /proxy/google/{path:path}` — Forward to `generativelanguage.googleapis.com`.

### Analytics APIs
- `GET /api/requests` — Query intercepted requests.
- `GET /api/stats` — Total cost, total requests, average latency.
- `GET /api/cost-by-model` — Cost by model.
- `GET /api/cost-by-feature` — Cost by feature tag.
- `GET /api/cost-by-team` — Cost by team tag.
- `GET /api/cost-timeline` — Spend grouped by day.
- `GET /api/waste-alerts` — High/Medium/Low waste findings.
- `GET /api/budgets` — Budgets vs actual spend.
- `GET /api/customers` — Customers vs budget.
- `GET /api/recommendations` — Alternative model savings.

### Shadow AI Discovery APIs
- `GET /api/v1/assets` — List discovered AI endpoints/models.
- `GET /api/v1/assets/summary` — Discovered assets overview.
- `GET /api/v1/assets/{id}` — Retrieve asset detail and discovery logs.
- `PATCH /api/v1/assets/{id}` — Update owner team, status, or risk tier.
- `POST /api/v1/assets/{id}/approve` — Mark a shadow asset as approved.
- `GET /api/v1/discovery/events` — Retrieve append-only discovery log.
- `GET /api/v1/providers/signatures` — Retrieve provider signature rules.
- `POST /api/v1/providers/signatures` — Register custom provider signature.
