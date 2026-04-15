# BurnLens v1.0 — Architecture & Onboarding Specification

**Version:** 1.0  
**Status:** Draft  
**Replaces:** burnlens_mvp_technical_spec.md (v0.1.1)

---

## 1. Product Overview

BurnLens is an open-source LLM FinOps tool: a transparent proxy, CLI, and dashboard that shows developers exactly where their AI API money goes — per feature, team, and customer — without changing a line of application code.

**Core value:** Set one environment variable. See every LLM API call's real cost within seconds.

**v1.0 extends this with Shadow AI Discovery:** automatically detect, catalog, and alert on all AI API usage across an organisation — including unapproved models, personal API keys, and unknown providers — within 24 hours.

### What ships in v1.0

| Capability | Where it runs |
|---|---|
| Transparent proxy (OpenAI, Anthropic, Google) | Local |
| Cost tracking per request, model, feature, team, customer | Local |
| Shadow AI detection (billing API parsers + proxy traffic) | Local |
| AI asset inventory with risk classification | Local |
| Budget alerts, waste detection, model recommendations | Local |
| Discovery dashboard | Local (`localhost:8420/ui/discovery`) |
| Cloud cost analytics dashboard | burnlens.app/dashboard |
| Google + GitHub OAuth | burnlens.app |
| 60-second metadata sync (OSS → cloud) | Bridge |
| Stripe billing (Free / Cloud $29/mo) | burnlens.app |

### What is explicitly out of scope in v1.0

- Policy enforcement / request blocking (v2)
- Compliance reporting (v2)
- Discovery data in the cloud dashboard (v2)
- Multi-tenant SaaS hosting of the proxy itself (v2)
- Mobile (web dashboard is sufficient)

---

## 2. Two Surfaces — One Product

BurnLens v1.0 has two distinct surfaces that share a brand but operate independently until the user explicitly connects them with `burnlens login`.

```
LOCAL (OSS)                              CLOUD (SaaS)
─────────────────────────────────        ──────────────────────────────────
localhost:8420                           burnlens.app
                                         
Proxy — intercepts all LLM calls         Landing page + pricing
Cost tracking — per request              Google / GitHub OAuth
Shadow AI discovery                      API key generation + workspace
ai_assets inventory                      Cost analytics dashboard
discovery.html (local browser only)      /api/v1/ingest (receives sync)
burnlens CLI                             Stripe billing
                                         
         ← burnlens login enables →
         60s metadata sync (no prompts, no payloads)
```

**The key distinction for documentation and support:**

- Everything in the left column works with zero internet access and zero account.
- Everything in the right column requires a burnlens.app account.
- Shadow AI discovery **always runs locally** — discovery data never syncs to the cloud in v1.0.
- The cloud dashboard shows **cost analytics only** (spend charts, model breakdown, request table).

This split is intentional: the local proxy is the trust layer. Prompt content never leaves the machine.

---

## 3. User Journeys

### 3a. OSS Path (local-only, no account required)

```
1. pip install burnlens
2. burnlens start
   → Proxy running at localhost:8420
   → Dashboard at localhost:8420/ui  (empty state + Getting Started tab)
   → Discovery at localhost:8420/ui/discovery  (empty, detection armed)

3. User sets one env var per provider:
   export OPENAI_BASE_URL=http://127.0.0.1:8420/proxy/openai
   export ANTHROPIC_BASE_URL=http://127.0.0.1:8420/proxy/anthropic
   # Google: import burnlens.patch; burnlens.patch.patch_google()

4. User runs their existing application — no code changes.

5. First SDK call flows through the proxy:
   → Cost row appears in main dashboard immediately
   → Asset upserted in discovery dashboard immediately
   → APScheduler billing API parse runs 1 hour after start
     (catches usage that occurred outside the proxy)

6. Optional: burnlens login
   → Links to cloud account, enables 60s metadata sync
   → Local behaviour unchanged after login
```

**Empty states a first-time user will see:**
- Main dashboard: "No requests yet. Route API calls through the proxy to see them here." Charts render at zero.
- Discovery dashboard: "No assets found", "No shadow AI detected", "No discovery events yet". KPI cards at zero.
- Both dashboards populate in real-time on first proxied call — no page refresh needed.

**Google provider note:** The Google AI SDK does not support a `BASE_URL` env var. Users must call `burnlens.patch.patch_google()` in their application code. This is the only case that requires a code change, and it is one line.

---

### 3b. SaaS Path (cloud onboarding)

```
1. User visits burnlens.app
   → Landing page: "See where your AI API money goes"

2. Clicks "Get Started Free"
   → /signup page with:
      [Sign in with Google]  [Sign in with GitHub]
      — or —  email + workspace name form

3. Completes OAuth (Google or GitHub) or email signup
   → Workspace created
   → bl_live_{key} API key generated and displayed once
   → 3-step onboarding shown:
        Step 1: pip install burnlens
        Step 2: burnlens login  (paste API key when prompted)
        Step 3: Route your SDK through the proxy

4. Clicks "Go to dashboard"
   → /dashboard: cost analytics view
      - Daily spend bar chart
      - Cost by model doughnut
      - Cost by feature / team bars
      - Recent requests table
      (All empty until burnlens login completes and sync begins)

5. User runs burnlens login on their machine
   → Validates API key against burnlens.app/auth/login
   → Writes cloud config to burnlens.yaml
   → Sync loop starts: 60s batches of metadata → /api/v1/ingest

6. First sync batch arrives → cloud dashboard populates
```

**Plan limits at signup (Free tier):**
- 10,000 requests/month
- 7-day cost history
- Upgrade prompt at 80% usage threshold → Stripe checkout ($29/mo Cloud plan)

---

## 4. Authentication & API Keys

BurnLens v1.0 has two separate authentication paths that serve different clients. They share the same JWT format but are issued differently and used differently.

### 4a. Browser Authentication (OAuth — Google / GitHub)

Used by: the burnlens.app web dashboard.

```
User clicks [Sign in with Google]
  → GET /auth/google
    Redirects to Google OAuth consent (scopes: openid email profile)
    redirect_uri: burnlens.app/auth/google/callback

  → GET /auth/google/callback
    Exchanges code for token via httpx (no OAuth library)
    Fetches profile from googleapis.com/oauth2/v3/userinfo
    Upserts user (google_id / email match)
    Checks workspace membership:
      - Member found → issue JWT
      - Pending invite for this email → auto-accept → issue JWT
      - No workspace → redirect to /signup?email=...&sso=google

  → Redirect to /auth/callback.html#token={jwt}
    callback.html extracts token from URL fragment
    Stores in localStorage as "bl_token"
    Redirects to /dashboard
```

GitHub OAuth follows the same pattern (`/auth/github`, `/auth/github/callback`) using `github.com/login/oauth/authorize` and `api.github.com/user`.

**JWT payload:**
```json
{
  "workspace_id": "ws_abc123",
  "plan": "free",
  "user_id": "usr_xyz",
  "role": "owner",
  "iat": 1713000000,
  "exp": 1713086400
}
```

- `plan` is one of: `"free"`, `"cloud"`, `"teams"`, `"enterprise"`
- `exp` is always `iat + 86400` (24-hour expiry)
- Token is stored in `localStorage` only — never in a cookie, never sent to the local proxy

---

### 4b. CLI Authentication (API Key)

Used by: `burnlens login` and the 60-second sync loop.

```
burnlens login
  → Prompts: "Enter your BurnLens API key (bl_live_...):"
  → POST burnlens.app/auth/login
    Body:    {"api_key": "bl_live_..."}
    Returns: {"token": "eyJ...", "workspace_name": "My Team",
              "plan": "free", "expires_in": 86400}
  → CLI displays: "Connected to workspace 'My Team' (free plan)"
  → Writes to burnlens.yaml:
      cloud:
        enabled: true
        api_key: bl_live_...
        endpoint: https://burnlens.app/api/v1/ingest
        sync_interval_seconds: 60
```

**Critical distinction:** The CLI stores the **API key** in `burnlens.yaml`, not the JWT. The JWT returned by `/auth/login` is used only to display the success message (workspace name, plan). The sync loop authenticates every batch with the raw API key via the `X-API-Key` header — it never re-issues or stores a JWT locally.

The `user_id` in the JWT payload is `None` for API-key login (no SSO user context). The `role` defaults to `"owner"`.

---

### 4c. API Key Security

- Generated at signup as `bl_live_{uuid4().hex}`
- Shown once at signup — user is responsible for storing it
- Hashed via SHA-256 before storage in Postgres — raw key is never persisted
- Used as the bearer credential for all sync batches: `X-API-Key: bl_live_...`

---

## 5. Cloud Sync (OSS → burnlens.app)

Cloud sync is the bridge between the local proxy and the cloud dashboard. It is opt-in, metadata-only, and designed so that its failure never affects proxy performance.

### How it works

```
burnlens start (with cloud.enabled: true in burnlens.yaml)
  → asyncio.create_task(cloud_sync.start_sync_loop(db_path))
  → Every 60 seconds:
      1. Query requests WHERE synced_at IS NULL (up to 500 rows)
      2. POST burnlens.app/api/v1/ingest
         Header: X-API-Key: bl_live_...
         Body:   batch of metadata records (see schema below)
      3. On HTTP 200: UPDATE requests SET synced_at = now()
      4. On any error: log warning, continue — never raise
```

### What is synced (metadata only)

```json
{
  "api_key": "bl_live_...",
  "records": [
    {
      "ts": "2026-04-15T10:30:00Z",
      "provider": "openai",
      "model": "gpt-4o-mini",
      "input_tokens": 142,
      "output_tokens": 38,
      "cost_usd": 0.0000512,
      "latency_ms": 320,
      "tag_feature": "chat",
      "tag_team": "backend",
      "tag_customer": "acme-corp",
      "system_prompt_hash": "sha256:abc123..."
    }
  ]
}
```

**What is never synced:**
- Prompt content (user messages, system prompts)
- Response content
- Raw API keys or credentials
- Any PII from request/response bodies

`system_prompt_hash` is a SHA-256 one-way hash used only for duplicate detection — the original prompt is not recoverable from it.

### Sync state tracking

The `requests` table has a `synced_at TIMESTAMP NULL` column. `NULL` means unsynced. The sync loop queries `WHERE synced_at IS NULL` and marks rows after a successful push. If the process restarts, unsynced rows are picked up on the next loop iteration — no data is lost.

### Failure behaviour

Every operation in the sync loop is wrapped in `try/except`. A network timeout, a 5xx from the ingest endpoint, or a database error will log a warning and skip to the next interval. The proxy continues forwarding requests and logging locally regardless of sync status.

---

## 6. Shadow AI Discovery (Local Only)

Shadow AI Discovery is the v1.0 flagship feature. It automatically detects, catalogs, and alerts on all AI API usage across an organisation — including usage that bypasses the proxy entirely.

**Discovery data is local-only in v1.0.** The `ai_assets`, `provider_signatures`, and `discovery_events` tables are not synced to the cloud. The discovery dashboard runs at `localhost:8420/ui/discovery` only.

### Detection approach

Two complementary mechanisms run in parallel:

**1. Proxy-based (real-time)**
Every request through the proxy upserts an asset record immediately in `ai_assets`. A user making their first call with a new model or API key creates a discovery event on the spot. No delay.

**2. Billing API parsing (hourly)**
APScheduler runs billing API parsers for OpenAI, Anthropic, and Google every hour (first run deferred 1 hour from startup to allow traffic accumulation). This catches AI usage that happened outside the proxy — direct API calls, CI pipelines, team members using personal keys.

| Provider | Billing source | Status |
|---|---|---|
| OpenAI | Billing API | Live |
| Anthropic | Billing API | Live |
| Google | Proxy traffic only | Billing API stub (v2) |

### Shadow classification

An asset is classified as shadow when any of these are true:
- API key is not registered in the known-keys list
- Model is not in the approved model list
- Provider URL does not match any `provider_signatures` pattern
- Usage detected via billing API that never appeared in proxy traffic (implies direct call)

Risk tiers: `critical`, `high`, `medium`, `low`, `none` — set manually via PATCH or automatically by the classifier.

### Provider signatures

Seven providers pre-seeded with URL and header patterns using fnmatch glob matching:
- `*.openai.azure.com/*` — Azure OpenAI
- `api.openai.com/*` — OpenAI direct
- `api.anthropic.com/*` — Anthropic
- `generativelanguage.googleapis.com/*` — Google AI
- `bedrock-runtime.*.amazonaws.com/*` — AWS Bedrock
- `api.cohere.com/*` — Cohere
- `api.mistral.ai/*` — Mistral

Custom signatures can be added via `POST /api/v1/providers/signatures` for self-hosted or private models.

### Alert schedule

| Alert | Trigger | Channel |
|---|---|---|
| New shadow endpoint | Within 1 hour of detection | Slack + email |
| New provider first seen | Within 1 hour | Slack + email |
| Spend spike | >200% of 30-day average | Slack + email |
| Model version change digest | Daily at 08:00 UTC | Email |
| Inactive asset digest | Weekly at 08:00 UTC (Mon) | Email |

### Discovery dashboard (localhost:8420/ui/discovery)

Five panels, all populated in real-time:
1. **KPI cards** — total assets, active, shadow count, unassigned, monthly spend
2. **Provider donut chart** — asset breakdown by provider
3. **Asset table** — sortable, filterable, paginated; inline approve/assign actions
4. **Shadow alert panel** — unreviewed shadow assets, one-click approve
5. **Discovery timeline** — event log (new assets, model changes, status updates)

Global search across model, provider, team, endpoint, and tag. Filter views saved to `localStorage` — persist across page reloads, no backend needed.

---

## 7. Architecture Reference

### 7a. OSS Architecture (v1.0, local)

```
App code (with env var set)
  |
SDK  ->  localhost:8420/proxy/{provider}/...  (FastAPI + Uvicorn)
              |
         interceptor.py
         |-- Extract X-BurnLens-Tag-* headers
         |-- Hash system prompt (SHA-256)
         |-- Record start_ms
         |-- Forward to upstream provider (httpx AsyncClient)
         |-- Stream chunks immediately (SSE passthrough)
         |-- asyncio.create_task -> log cost to SQLite
         +-- asyncio.create_task -> upsert ai_assets (discovery)
              |
         SQLite (~/.burnlens/burnlens.db)
         |-- requests table    (cost tracking)
         |-- ai_assets         (shadow AI inventory)
         |-- provider_signatures (URL pattern library)
         +-- discovery_events  (append-only audit log)

APScheduler (hourly, deferred 1h on startup)
  +-- Billing API parsers -> OpenAI, Anthropic -> upsert ai_assets

burnlens.app cloud sync (if cloud.enabled: true)
  +-- Every 60s: batch POST metadata -> burnlens.app/api/v1/ingest
```

**Key proxy constraints:**
- Request/response bodies are never modified
- Streaming SSE chunks are forwarded immediately — never buffered
- Cost calculation uses the `usage` field in the API response — tokens are never counted independently
- If BurnLens cannot log a request, it still forwards it (fail open)
- Proxy overhead target: < 20ms

---

### 7b. Cloud Architecture (burnlens.app)

```
burnlens.app  (single domain, Vercel)
|-- /                    Static HTML (Vercel static serving)
|-- /signup              Static HTML
|-- /dashboard           Static HTML
|-- /auth/callback.html  Static HTML (extracts JWT from URL fragment)
|
|-- /api/*               api/main.py  (@vercel/python serverless function)
|-- /auth/*              FastAPI app, cold-started per request
|-- /billing/*           Connects to Postgres via asyncpg connection pool
|-- /team/*              (min 2 / max 20 connections, DATABASE_URL env var)
|-- /invite/*
+-- /status/*

Postgres (external, e.g. Neon or Railway Postgres)
|-- users              (id, email, name, google_id, github_id,
|                       created_at, last_login)
|-- workspaces         (id, name, plan, api_key_hash, ...)
|-- workspace_members  (workspace_id, user_id, role, ...)
|                       ^ join table — workspace_id is here, not on users
|                       one user can belong to multiple workspaces
+-- requests           (synced cost metadata from OSS sync batches)
```

**User-workspace relationship:** `workspace_id` is not a column on `users`. The relationship is many-to-many via `workspace_members`. A user created via Google/GitHub OAuth may belong to one or more workspaces; membership and role are stored on `workspace_members`, not on `users`.

**Serverless function note:** `api/main.py` is a standard FastAPI app mounted as a Vercel serverless function via `@vercel/python`. It cold-starts on the first request to any `/api/*`, `/auth/*`, or `/billing/*` route. The asyncpg connection pool is re-created on each cold start — this is expected behaviour for serverless Postgres.

---

## 8. SQLite Schema (v1.0, local OSS)

The local database lives at `~/.burnlens/burnlens.db` (configurable via `db_path` in `burnlens.yaml`). All tables use WAL mode. New tables added in v1.0 are created via migration on `burnlens start` — safe to run against existing v0.x databases.

### requests (v0.x, unchanged)

```sql
CREATE TABLE requests (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id          TEXT,
    provider            TEXT NOT NULL,
    model               TEXT NOT NULL,
    request_path        TEXT,
    timestamp           TEXT NOT NULL,        -- ISO 8601 UTC
    input_tokens        INTEGER DEFAULT 0,
    output_tokens       INTEGER DEFAULT 0,
    reasoning_tokens    INTEGER DEFAULT 0,
    cache_read_tokens   INTEGER DEFAULT 0,
    cache_write_tokens  INTEGER DEFAULT 0,
    cost_usd            REAL DEFAULT 0.0,
    duration_ms         INTEGER DEFAULT 0,
    status_code         INTEGER,
    tag_feature         TEXT,
    tag_team            TEXT,
    tag_customer        TEXT,
    system_prompt_hash  TEXT,
    synced_at           TIMESTAMP NULL        -- NULL = not yet synced to cloud
);
```

### ai_assets (v1.0 new)

```sql
CREATE TABLE IF NOT EXISTS ai_assets (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    provider            TEXT    NOT NULL,
    model_name          TEXT    NOT NULL,
    endpoint_url        TEXT    NOT NULL,
    api_key_hash        TEXT,                 -- SHA-256, never raw key
    owner_team          TEXT,
    project             TEXT,
    status              TEXT    NOT NULL DEFAULT 'shadow'
                            CHECK(status IN ('active','inactive','shadow','approved','deprecated')),
    risk_tier           TEXT    NOT NULL DEFAULT 'unclassified'
                            CHECK(risk_tier IN ('unclassified','low','medium','high')),
    first_seen_at       TEXT    NOT NULL,
    last_active_at      TEXT    NOT NULL,
    monthly_spend_usd   REAL    NOT NULL DEFAULT 0.0,
    monthly_requests    INTEGER NOT NULL DEFAULT 0,
    tags                TEXT    NOT NULL DEFAULT '{}',  -- JSON string
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);
```

**Status values:**
- `shadow` — detected but not reviewed (default for new assets)
- `approved` — explicitly approved by an admin
- `active` — in use, approved
- `inactive` — no traffic in >30 days
- `deprecated` — flagged for removal

### provider_signatures (v1.0 new)

```sql
CREATE TABLE IF NOT EXISTS provider_signatures (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    provider          TEXT NOT NULL UNIQUE,
    endpoint_pattern  TEXT NOT NULL,             -- fnmatch glob, e.g. "api.openai.com/*"
    header_signature  TEXT NOT NULL DEFAULT '{}',-- JSON object: {header_name: value_pattern}
    model_field_path  TEXT NOT NULL DEFAULT 'body.model'  -- dotted path to model name in request
);
```

Key design points:
- `provider` is UNIQUE — one canonical signature per provider name
- `header_signature` is a JSON object rather than two flat columns — supports multi-header matching
- `model_field_path` locates the model name in the request body (e.g. `body.model` for OpenAI, `body.modelId` for Bedrock). Used by the classifier to extract which model is being called.
- No `created_at` column — seed data is static; custom additions are tracked by `id` ordering.

Pre-seeded for 7 providers on first migration. Custom signatures added via `POST /api/v1/providers/signatures`.

### discovery_events (v1.0 new)

```sql
CREATE TABLE IF NOT EXISTS discovery_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type  TEXT NOT NULL
                    CHECK(event_type IN (
                        'new_asset_detected',
                        'model_changed',
                        'provider_changed',
                        'key_rotated',
                        'asset_inactive'
                    )),
    asset_id    INTEGER REFERENCES ai_assets(id),  -- nullable (system-level events)
    details     TEXT NOT NULL DEFAULT '{}',         -- JSON string
    detected_at TEXT NOT NULL
);
-- Append-only enforced via SQLite trigger:
-- DELETE and UPDATE on this table are blocked at DB level
```

Notes:
- `asset_id` is nullable — allows system-level discovery events not tied to a specific asset
- Column order is `event_type` before `asset_id` (matches database.py implementation)
- Detail column is `details` (plural), timestamp column is `detected_at`
- Event type enum has 5 values: `new_asset_detected`, `model_changed`, `provider_changed`, `key_rotated`, `asset_inactive`

---

## 9. API Reference

### 9a. Local API (localhost:8420)

All endpoints served by the FastAPI proxy. No authentication required — local only.

**Proxy routes**
| Method | Path | Purpose |
|---|---|---|
| ANY | `/proxy/openai/{path}` | Forward to api.openai.com |
| ANY | `/proxy/anthropic/{path}` | Forward to api.anthropic.com |
| ANY | `/proxy/google/{path}` | Forward to generativelanguage.googleapis.com |

**Cost analytics**
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/requests` | Recent requests, filterable by `days` |
| GET | `/api/stats` | Total spend, request count, avg cost |
| GET | `/api/cost-by-model` | Aggregated cost per model |
| GET | `/api/cost-by-feature` | Aggregated cost per feature tag |
| GET | `/api/cost-by-team` | Aggregated cost per team tag |
| GET | `/api/cost-timeline` | Daily spend for last N days |
| GET | `/api/waste-alerts` | Waste detector findings |
| GET | `/api/budgets` | Team budget status |
| GET | `/api/customers` | Customer spend vs budget |
| GET | `/api/recommendations` | Model recommendation findings |

**Shadow AI discovery (v1.0)**
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/assets` | List assets — paginated, filterable by status/provider/risk |
| GET | `/api/v1/assets/summary` | Dashboard aggregation (counts, spend) |
| GET | `/api/v1/assets/{id}` | Asset detail with discovery event history |
| PATCH | `/api/v1/assets/{id}` | Update team, risk_tier, tags, status |
| POST | `/api/v1/assets/{id}/approve` | Approve a shadow asset |
| GET | `/api/v1/discovery/events` | Query events by type, asset_id, date range |
| GET | `/api/v1/providers/signatures` | List all provider signatures |
| POST | `/api/v1/providers/signatures` | Add custom provider signature |

**Static**
| Method | Path | Purpose |
|---|---|---|
| GET | `/ui` | Main cost dashboard |
| GET | `/ui/discovery` | Shadow AI discovery dashboard |
| GET | `/health` | Health check (`{"status": "ok", "version": "1.0.0"}`) |

---

### 9b. Cloud API (burnlens.app/api/*)

All endpoints require `X-API-Key: bl_live_...` header (or JWT `Authorization: Bearer` for browser clients).

**Auth**
| Method | Path | Purpose |
|---|---|---|
| GET | `/auth/google` | Initiate Google OAuth |
| GET | `/auth/google/callback` | Google OAuth callback |
| GET | `/auth/github` | Initiate GitHub OAuth |
| GET | `/auth/github/callback` | GitHub OAuth callback |
| POST | `/auth/login` | API key -> JWT (used by `burnlens login`) |

**Sync ingest**
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/ingest` | Receive metadata batch from OSS sync loop |

**Cloud dashboard data** — mirrors OSS local API paths (no `/v1/` namespace)
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/stats` | Total spend, request count, avg cost |
| GET | `/api/cost-by-model` | Aggregated cost per model |
| GET | `/api/cost-by-feature` | Aggregated cost per feature tag |
| GET | `/api/cost-by-team` | Aggregated cost per team tag |
| GET | `/api/cost-by-customer` | Aggregated cost per customer tag |
| GET | `/api/cost-timeline` | Daily spend for last N days |
| GET | `/api/requests` | Recent requests, filterable by `days` |

**Billing**
| Method | Path | Purpose |
|---|---|---|
| GET | `/billing/plans` | Available plans and limits |
| POST | `/billing/checkout` | Create Stripe checkout session |
| POST | `/billing/webhook` | Stripe webhook (plan upgrades/cancellations) |

**Team management**
| Method | Path | Purpose |
|---|---|---|
| POST | `/team/invite` | Send workspace invitation |
| GET | `/invite/{token}/accept` | Accept invitation |

---

## 10. Configuration Reference

### burnlens.yaml (local OSS)

```yaml
# Proxy
proxy_port: 8420          # default
db_path: ~/.burnlens/burnlens.db

# Global budget alert
budget_limit_usd: 500.00

# Per-team budgets
budgets:
  global: 500.00
  teams:
    backend: 200.00
    research: 100.00
    infra: 50.00

# Per-customer hard caps (429 enforcement before forwarding)
customer_budgets:
  acme-corp: 50.00
  beta-user: 10.00
  default: 5.00           # applied to unrecognised customers

# Cloud sync (written by burnlens login — do not edit manually)
cloud:
  enabled: false
  api_key: bl_live_xxxxxxxxxxxx
  endpoint: https://burnlens.app/api/v1/ingest
  sync_interval_seconds: 60
  anonymise_prompts: true  # prompt content never synced

# Alert channels
alerts:
  slack_webhook_url: https://hooks.slack.com/...
  email:
    smtp_host: smtp.gmail.com
    smtp_port: 587
    smtp_user: you@gmail.com
    smtp_password: your-app-password
    from: BurnLens <you@gmail.com>
    to:
      - oncall@yourcompany.com

# OpenTelemetry (opt-in: pip install burnlens[otel])
telemetry:
  enabled: false
  otel_endpoint: http://localhost:4317
  service_name: burnlens
```

### Environment variables (Railway / self-hosted OSS)

| Variable | Purpose | Example |
|---|---|---|
| `PORT` | Proxy listen port (overrides `proxy_port`) | `8420` |
| `BURNLENS_DB_PATH` | SQLite path (overrides `db_path`) | `/data/burnlens.db` |
| `OPENAI_API_KEY` | Forwarded to OpenAI (user's own key) | `sk-...` |
| `ANTHROPIC_API_KEY` | Forwarded to Anthropic | `sk-ant-...` |
| `GOOGLE_API_KEY` | Forwarded to Google AI | `AIza...` |

### Environment variables (Vercel cloud backend)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string (asyncpg format) |
| `JWT_SECRET` | HMAC secret for JWT signing |
| `GOOGLE_CLIENT_ID` | Google OAuth app client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth app client secret |
| `GITHUB_CLIENT_ID` | GitHub OAuth app client ID |
| `GITHUB_CLIENT_SECRET` | GitHub OAuth app client secret |
| `STRIPE_SECRET_KEY` | Stripe secret key |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret |
| `BASE_URL` | Public base URL (`https://burnlens.app`) |

---

## 11. Deployment

### 11a. Vercel (cloud backend — burnlens.app)

The cloud backend is a FastAPI app deployed as a Vercel serverless function via `@vercel/python`. Static HTML (landing page, dashboard, signup) is served by Vercel's static layer.

**`vercel.json` routing:**
```json
{
  "builds": [
    {"src": "api/main.py", "use": "@vercel/python"},
    {"src": "frontend/**", "use": "@vercel/static"}
  ],
  "routes": [
    {"src": "/api/(.*)",     "dest": "api/main.py"},
    {"src": "/auth/(.*)",    "dest": "api/main.py"},
    {"src": "/billing/(.*)", "dest": "api/main.py"},
    {"src": "/team/(.*)",    "dest": "api/main.py"},
    {"src": "/invite/(.*)",  "dest": "api/main.py"},
    {"src": "/status/(.*)",  "dest": "api/main.py"},
    {"src": "/auth/callback.html", "dest": "frontend/auth/callback.html"}
  ]
}
```

**Required environment variables in Vercel dashboard:**
`DATABASE_URL`, `JWT_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `BASE_URL`

**Deploy:**
```bash
vercel --prod
```

---

### 11b. Railway (self-hosted OSS proxy — optional)

For teams that want to run the BurnLens proxy on a shared server rather than each developer's machine.

**`railway.toml`:**
```toml
[build]
builder = "nixpacks"
buildCommand = "pip install -e ."

[deploy]
startCommand = "burnlens start --host 0.0.0.0 --port $PORT"
healthcheckPath = "/health"
healthcheckTimeout = 10
restartPolicyType = "on-failure"

[[volumes]]
mountPath = "/data"
```

**Required environment variables in Railway:**
`PORT`, `BURNLENS_DB_PATH=/data/burnlens.db`

Set provider API keys as Railway secrets: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`

**Custom domain:** point `proxy.yourcompany.com` to the Railway service. Teams then set:
```bash
export OPENAI_BASE_URL=https://proxy.yourcompany.com/proxy/openai
export ANTHROPIC_BASE_URL=https://proxy.yourcompany.com/proxy/anthropic
```

---

## 12. Known Limitations & v2 Roadmap

### Tech debt in v1.0

| Item | Impact | Notes |
|---|---|---|
| Google billing API is a stub | Detection relies on proxy traffic only for Google | Full API integration in v2 |
| `discovery_events` grows unbounded | Disk usage over time | 90-day archival deferred |
| Client-side sort on asset table | Inaccurate with large datasets | API lacks `sort_by` param |
| `_fired_events` deduplication is in-memory | Alert re-fires after process restart | Needs DB-backed persistence |
| Monthly spend KPI uses visible page only | Inaccurate with pagination | Avoids secondary fetch cost |
| Serverless cold starts on Vercel | First request to cloud API ~1-2s | Acceptable at current scale |

### Deferred to v2

**Policy enforcement (PLCY)**
- PLCY-01: Admin-defined allowed/blocked model lists
- PLCY-02: Block requests to unapproved models before forwarding
- PLCY-03: Per-team spending limits with hard 429 enforcement (cloud-side)

**Compliance reporting (CMPL)**
- CMPL-01: Reports mapped to regulatory frameworks (SOC 2, GDPR, ISO 27001)
- CMPL-02: Data residency tracking per provider and model

**Discovery in the cloud dashboard**
- v1.0: discovery is local-only
- v2: sync ai_assets and discovery_events to cloud for team-wide visibility

**Other v2 items**
- Multi-tenant hosted proxy (users point SDK to burnlens.app instead of localhost)
- Mobile (web dashboard sufficient for v1.0)
- Agent-based deep payload inspection (v1.0 is metadata-only by design)
