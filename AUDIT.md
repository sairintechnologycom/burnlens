# BurnLens x TokenLens — Codebase Audit

**Date:** 2026-04-11
**Auditor:** Claude (automated)
**Scope:** Full source audit of both codebases for unification planning

---

## 1. Inventory

### BurnLens (Local Proxy + CLI)

| Module | Path | Description |
|--------|------|-------------|
| `cli.py` | `burnlens/cli.py` | Typer CLI with 12 commands (start, top, report, analyze, export, budgets, customers, recommend, doctor, login, sync, ui) |
| `config.py` | `burnlens/config.py` | YAML config loader with dataclass-based sections (alerts, budgets, cloud, email, telemetry) |
| `server.py` | `burnlens/server.py` | Test-oriented app factory (`create_app()`) |
| `proxy/server.py` | `burnlens/proxy/server.py` | Production FastAPI app with lifespan, APScheduler, catch-all proxy route |
| `proxy/interceptor.py` | `burnlens/proxy/interceptor.py` | Request/response interception, tag extraction, token counting, cost calculation |
| `proxy/providers.py` | `burnlens/proxy/providers.py` | Provider routing config (OpenAI, Anthropic, Google) + env var builder |
| `proxy/streaming.py` | `burnlens/proxy/streaming.py` | SSE streaming passthrough with per-provider usage extraction |
| `cost/calculator.py` | `burnlens/cost/calculator.py` | Token usage to USD cost conversion with cache/reasoning token support |
| `cost/pricing.py` | `burnlens/cost/pricing.py` | JSON pricing file loader with exact + prefix model matching |
| `cost/pricing_data/*.json` | `burnlens/cost/pricing_data/` | Bundled pricing for OpenAI, Anthropic, Google |
| `storage/database.py` | `burnlens/storage/database.py` | SQLite setup (WAL), migrations, insert operations, append-only event triggers |
| `storage/models.py` | `burnlens/storage/models.py` | Dataclasses: RequestRecord, AggregatedUsage, AiAsset, ProviderSignature, DiscoveryEvent |
| `storage/queries.py` | `burnlens/storage/queries.py` | Aggregation queries (by model, tag, time, team, customer) — 750+ lines |
| `analysis/waste.py` | `burnlens/analysis/waste.py` | Waste detectors: context bloat, duplicate requests, model overkill, prompt waste |
| `analysis/budget.py` | `burnlens/analysis/budget.py` | Budget tracking with daily/weekly/monthly periods, 80/90/100% thresholds, forecasting |
| `analysis/recommender.py` | `burnlens/analysis/recommender.py` | Model downgrade/caching recommendations with projected savings |
| `analysis/reports.py` | `burnlens/analysis/reports.py` | Stub (Sprint 2) |
| `detection/wrapper.py` | `burnlens/detection/wrapper.py` | SDK-level interception via httpx transport replacement |
| `detection/classifier.py` | `burnlens/detection/classifier.py` | Provider signature matching + shadow asset classification |
| `detection/billing.py` | `burnlens/detection/billing.py` | Billing API parsers for OpenAI, Anthropic, Google admin APIs |
| `detection/scheduler.py` | `burnlens/detection/scheduler.py` | APScheduler wiring for hourly detection + alert jobs |
| `alerts/engine.py` | `burnlens/alerts/engine.py` | Per-request budget threshold evaluation with deduplication |
| `alerts/types.py` | `burnlens/alerts/types.py` | Alert payload dataclasses (DiscoveryAlert, SpendSpikeAlert, DigestPayload) |
| `alerts/slack.py` | `burnlens/alerts/slack.py` | Slack webhook delivery with blocks-format payloads |
| `alerts/terminal.py` | `burnlens/alerts/terminal.py` | Rich terminal notifications |
| `alerts/email.py` | `burnlens/alerts/email.py` | Async SMTP email delivery (STARTTLS) |
| `alerts/discovery.py` | `burnlens/alerts/discovery.py` | Discovery event alert engine (shadow assets, new providers, spend spikes) |
| `cloud/sync.py` | `burnlens/cloud/sync.py` | Background sync of anonymised cost data to burnlens.app (privacy-preserving) |
| `telemetry/otel.py` | `burnlens/telemetry/otel.py` | OpenTelemetry span export (OTLP/gRPC) |
| `dashboard/routes.py` | `burnlens/dashboard/routes.py` | JSON API endpoints for web dashboard (summary, costs, waste, budget, recommendations) |
| `dashboard/static/` | `burnlens/dashboard/static/` | Single-page HTML + Chart.js dashboard (no build step) |
| `api/schemas.py` | `burnlens/api/schemas.py` | Pydantic v2 schemas for asset/discovery/signature endpoints |
| `api/assets.py` | `burnlens/api/assets.py` | Asset CRUD endpoints (list, detail, patch, approve, events) |
| `api/discovery.py` | `burnlens/api/discovery.py` | Discovery event list endpoint |
| `api/providers.py` | `burnlens/api/providers.py` | Provider signature CRUD endpoints |
| `doctor.py` | `burnlens/doctor.py` | System health checks (proxy, DB, env vars, activity) |
| `patch.py` | `burnlens/patch.py` | Monkey-patch SDK clients for proxy routing |
| `export.py` | `burnlens/export.py` | CSV export of request records |
| `reports/weekly.py` | `burnlens/reports/weekly.py` | Weekly report generation with prior-period comparison |

### TokenLens (Cloud SaaS)

| Module | Path | Description |
|--------|------|-------------|
| `main.py` | `src/api/main.py` | Central FastAPI app with all REST endpoints, APScheduler, API key auth |
| `billing.py` | `src/api/billing.py` | Lemon Squeezy integration (checkout, license validation, webhooks) |
| `settings.py` | `src/config/settings.py` | Pydantic BaseSettings — all config via `TOKENLENS_*` env vars |
| `pricing.py` | `src/config/pricing.py` | Centralized model pricing table (hardcoded dict) |
| `database.py` | `src/lib/database.py` | SQLAlchemy async engine + session factory (asyncpg for PostgreSQL) |
| `encryption.py` | `src/lib/encryption.py` | Fernet encryption for API keys at rest |
| `license.py` | `src/lib/license.py` | License key validation against Lemon Squeezy API with tier enforcement |
| `email.py` | `src/lib/email.py` | Transactional emails via Resend API (welcome, cancellation) |
| `seeds.py` | `src/lib/seeds.py` | Demo data generator (30 days of mock usage) |
| `schemas.py` | `src/models/schemas.py` | SQLAlchemy ORM models + Pydantic DTOs (Organization, ProviderConnection, UsageRecord, OptimizationResult, AlertRule, WebhookEvent) |
| `rate_limit.py` | `src/middleware/rate_limit.py` | Redis-based sliding window rate limiting (tier-based) |
| `optimizer.py` | `src/services/optimizer.py` | Rule-based optimization engine (6 rules: legacy, downgrade, caching, batch, compression, arbitrage) |
| `base.py` | `src/services/providers/base.py` | Abstract provider interface (`UsageProvider` ABC) |
| `anthropic_provider.py` | `src/services/providers/anthropic_provider.py` | Anthropic billing API integration |
| `openai_provider.py` | `src/services/providers/openai_provider.py` | OpenAI billing API integration |
| `google_provider.py` | `src/services/providers/google_provider.py` | Google AI Studio billing API integration |
| `sync_worker.py` | `src/workers/sync_worker.py` | Background sync, optimization runner, data purge |
| `001_initial.py` | `src/migrations/001_initial.py` | Core schema migration |
| `002_billing_schema.py` | `src/migrations/002_billing_schema.py` | Billing columns + webhook_events table |
| Frontend `page.tsx` | `frontend/src/app/page.tsx` | Marketing landing page with pricing |
| Frontend `dashboard/` | `frontend/src/app/dashboard/page.tsx` | Main analytics dashboard (Recharts) |
| Frontend `optimizations/` | `frontend/src/app/optimizations/page.tsx` | Optimization recommendations UI |
| Frontend `connections/` | `frontend/src/app/connections/page.tsx` | Provider connection management |
| Frontend `alerts/` | `frontend/src/app/alerts/page.tsx` | Alert rule CRUD |
| Frontend `settings/` | `frontend/src/app/settings/page.tsx` | Organization settings |
| Frontend `setup/` | `frontend/src/app/setup/page.tsx` | First-run setup wizard |
| Frontend `api.ts` | `frontend/src/lib/api.ts` | HTTP client with API key auth |
| Frontend `useAuth.ts` | `frontend/src/lib/hooks/useAuth.ts` | Auth state hook (localStorage) |
| Frontend E2E | `frontend/tests/e2e/` | Playwright tests for auth, CRUD, dashboard |

---

## 2. Overlap Analysis

### 2.1 Cost Calculation / Pricing

| Aspect | BurnLens | TokenLens | Recommendation |
|--------|----------|-----------|----------------|
| **Pricing data format** | JSON files per provider (`pricing_data/*.json`), lazy-loaded | Hardcoded Python dict in `pricing.py` | **Keep BurnLens.** JSON files are easier to update without code changes, support community contributions, and enable user overrides. |
| **Pricing lookup** | Exact match then longest-prefix match | Exact match only | **Keep BurnLens.** Prefix matching handles dated model variants (e.g., `gpt-4o-2024-11-20`) automatically. |
| **Cost formula** | Full breakdown: input + output + reasoning + cache_read + cache_write | Simple: input + output only | **Keep BurnLens.** Its formula correctly handles reasoning tokens (o1/o3) and cache tokens. TokenLens stores cache tokens but doesn't price them. |
| **Token extraction** | Per-provider parsers from HTTP response bodies | From billing API aggregates | **Merge.** Different data sources, both needed. BurnLens does real-time; TokenLens does daily aggregates. |

### 2.2 Provider Billing API Integration

| Aspect | BurnLens | TokenLens | Recommendation |
|--------|----------|-----------|----------------|
| **Architecture** | Functions in `detection/billing.py` | ABC-based `UsageProvider` classes | **Keep TokenLens.** The ABC pattern is cleaner and more extensible. BurnLens's flat functions mix parsing with DB writes. |
| **OpenAI API** | `/v1/organization/usage/completions` | `/v1/organization/usage` | **Merge.** Similar endpoints, minor path differences. |
| **Anthropic API** | Custom billing API call | `/v1/organizations/usage` | **Merge.** Both implementations are comparable. |
| **Google API** | Cloud billing API | AI Studio `/v1beta/usage` | **Merge.** Different target APIs; may need both for different customer profiles. |
| **Credential storage** | Admin keys from config/env (plaintext in config) | Fernet-encrypted at rest | **Keep TokenLens.** Encryption at rest is required for cloud. |
| **Cursor/pagination** | `has_more` / `next_page` pattern | `sync_cursor` stored per connection | **Keep TokenLens.** Persistent cursor enables incremental sync. |

### 2.3 Optimization / Recommendations

| Aspect | BurnLens | TokenLens | Recommendation |
|--------|----------|-----------|----------------|
| **Engine** | `analysis/recommender.py` — model downgrade + caching suggestions | `services/optimizer.py` — 6 rules (legacy, downgrade, caching, batch, compression, arbitrage) | **Keep TokenLens.** More comprehensive rule set, severity classification, and confidence scoring. |
| **Waste detection** | `analysis/waste.py` — context bloat, duplicate detection, prompt waste | None | **Keep BurnLens.** Unique capability — real-time waste detection from actual request data (not just billing aggregates). |
| **Model tiering** | Simple map (expensive → cheap) | Three-tier system (reasoning/balanced/fast) | **Keep TokenLens.** More nuanced. |
| **Output** | CLI-formatted findings | DB-stored `OptimizationResult` with apply/dismiss workflow | **Keep TokenLens.** Persistent results with user action tracking. |

### 2.4 Alert System

| Aspect | BurnLens | TokenLens | Recommendation |
|--------|----------|-----------|----------------|
| **Architecture** | Multi-channel engine: Slack + terminal + email + discovery alerts | Simple alert rules with webhook delivery | **Merge.** BurnLens has richer channels; TokenLens has cleaner rule abstraction. |
| **Budget tracking** | Daily/weekly/monthly periods with 80/90/100% thresholds + forecasting | Threshold-only alert rules (daily_spend, model_spend, etc.) | **Keep BurnLens.** Forecasting ("on track to exceed by X") is significantly more useful than simple threshold crossing. |
| **Discovery alerts** | Shadow asset detection, new provider alerts, spend spikes | None | **Keep BurnLens.** Unique capability. |
| **Dispatch** | Slack blocks, Rich terminal, SMTP email | Webhook URL per alert rule | **Merge.** Keep BurnLens channels + add TokenLens webhook flexibility. |

### 2.5 Dashboard / Frontend

| Aspect | BurnLens | TokenLens | Recommendation |
|--------|----------|-----------|----------------|
| **Stack** | Static HTML + Chart.js (no build step, served by FastAPI) | Next.js 16 + React 19 + Recharts + Framer Motion | **Keep TokenLens for cloud; keep BurnLens for local.** The zero-dependency static dashboard is critical for `pip install` UX. Cloud needs the full React app. |
| **Charts** | Chart.js (CDN-loaded) | Recharts (React component library) | **Keep both.** Different deployment targets. |
| **Analytics views** | Summary, costs by model/tag, daily trend, waste analysis, budget status | Summary, timeseries, provider/model breakdown, optimization recommendations | **Merge.** Superset both views into TokenLens frontend. |

### 2.6 Data Storage

| Aspect | BurnLens | TokenLens | Recommendation |
|--------|----------|-----------|----------------|
| **Database** | SQLite (WAL mode, aiosqlite) | PostgreSQL (asyncpg, SQLAlchemy) | **Keep both.** SQLite for local, PostgreSQL for cloud. Unified query layer needed. |
| **ORM** | Raw SQL with aiosqlite | SQLAlchemy ORM | **Keep TokenLens ORM for cloud; keep raw SQL for local.** SQLite doesn't benefit from ORM overhead. |
| **Schema** | Raw CREATE TABLE statements + triggers | SQLAlchemy models + Alembic-style migrations | **Keep TokenLens** migration approach for cloud. |

### 2.7 Background Jobs

| Aspect | BurnLens | TokenLens | Recommendation |
|--------|----------|-----------|----------------|
| **Scheduler** | APScheduler (hourly detection, daily/weekly digests) | APScheduler (hourly sync, daily optimizer, nightly purge) | **Merge.** Both use APScheduler. Combine job registrations. |
| **Sync** | Cloud sync to burnlens.app (anonymised cost data) | Provider billing sync to local DB | **Keep both.** Cloud sync is push (local→cloud); provider sync is pull (provider→local). |

---

## 3. Gap Analysis

### What BurnLens Needs from TokenLens

| Gap | Details |
|-----|---------|
| **Multi-tenancy** | BurnLens has no concept of organizations. TokenLens's org-scoped data model is required for cloud. |
| **Authentication** | BurnLens has no API authentication. TokenLens has API key + SHA-256 hash approach. |
| **Billing/licensing** | BurnLens has no monetization. TokenLens has Lemon Squeezy integration with tier enforcement. |
| **Rate limiting** | BurnLens has none. TokenLens has Redis-based per-tier rate limiting. |
| **Credential encryption** | BurnLens stores admin keys in plaintext config. TokenLens uses Fernet encryption at rest. |
| **PostgreSQL support** | BurnLens only supports SQLite. Need PostgreSQL for cloud scale. |
| **Proper frontend** | BurnLens's static HTML dashboard won't scale for the cloud product. TokenLens's Next.js app is needed. |
| **Data retention policy** | BurnLens keeps data forever. TokenLens has tier-aware purge (7d free / 365d paid). |
| **Provider connection management** | BurnLens has no concept of "connections" — just env vars. TokenLens has CRUD for connections. |
| **Export to CSV/JSON** | BurnLens has basic CSV. TokenLens has configurable export with format selection. |
| **Demo/seed data** | BurnLens has none. TokenLens's seed generator helps onboarding. |

### What TokenLens Needs from BurnLens

| Gap | Details |
|-----|---------|
| **Real-time proxy** | TokenLens has no HTTP proxy. It only reads billing APIs (daily granularity). BurnLens intercepts every request in real-time. |
| **Streaming SSE passthrough** | TokenLens cannot observe streaming responses. BurnLens handles this transparently. |
| **Per-request cost tracking** | TokenLens has daily aggregates only. BurnLens tracks individual requests with latency, status code, system prompt hash. |
| **Waste detection** | TokenLens has no waste analysis. BurnLens detects context bloat, duplicate requests, model overkill, prompt waste. |
| **Shadow AI detection** | TokenLens has no concept of shadow/unapproved AI usage. BurnLens has full asset discovery + classification pipeline. |
| **CLI tooling** | TokenLens has no CLI. BurnLens has `top`, `report`, `analyze`, `doctor`, `budgets`, `customers`, `recommend`. |
| **SDK wrapper** | TokenLens requires admin API keys. BurnLens's `wrap()` function instruments SDK clients directly — zero admin access needed. |
| **Tag extraction from headers** | TokenLens requires explicit `feature_tag` in API calls. BurnLens extracts `X-BurnLens-Tag-*` headers transparently. |
| **Budget forecasting** | TokenLens alerts on threshold crossing only. BurnLens forecasts end-of-period spend. |
| **OpenTelemetry export** | TokenLens has no observability integration. BurnLens exports spans to any OTLP collector. |
| **Team/customer budgets** | TokenLens has simple alert rules. BurnLens has per-team and per-customer monthly budget tracking. |
| **System health checks** | TokenLens has a basic `/health` endpoint. BurnLens's `doctor` command runs 7 diagnostic checks. |

---

## 4. Conflict Analysis

### 4.1 Configuration Approach

| BurnLens | TokenLens | Conflict |
|----------|-----------|----------|
| YAML config files (`burnlens.yaml`) with file-search hierarchy | Env-var-only (`TOKENLENS_*` via Pydantic BaseSettings) | **Incompatible.** |

**Decision needed:** Keep YAML for local mode (developer-friendly, git-committable). Use env vars for cloud mode (12-factor, container-friendly). Config loader should support both: YAML → env var override → defaults.

### 4.2 Database Abstraction

| BurnLens | TokenLens | Conflict |
|----------|-----------|----------|
| Raw SQL strings in `queries.py` (750+ lines, SQLite-specific) | SQLAlchemy ORM with async sessions | **Incompatible.** |

**Decision needed:** For the unified codebase, introduce a repository/query layer that can target either SQLite or PostgreSQL. Options:
- (A) SQLAlchemy for everything (adds dependency to local install)
- (B) Repository pattern with two backends (more code, lighter local install)
- **(Recommended: B)** — keeps `pip install burnlens` lightweight. The local backend uses raw aiosqlite; the cloud backend uses SQLAlchemy + asyncpg.

### 4.3 Pricing Data Storage

| BurnLens | TokenLens | Conflict |
|----------|-----------|----------|
| JSON files on disk (`pricing_data/*.json`) | Hardcoded Python dict | **Minor conflict.** |

**Decision needed:** Use JSON files as the single source of truth. Generate the Python dict at build time if needed for performance. JSON files are easier for users/community to update.

### 4.4 Usage Record Granularity

| BurnLens | TokenLens | Conflict |
|----------|-----------|----------|
| Per-request records (individual API calls with latency, status, headers) | Daily aggregates per (provider, model, feature, operation) | **Fundamental difference.** |

**Decision needed:** Support both. The proxy generates per-request records. The billing API sync generates daily aggregates. The unified schema must accommodate both granularities. Dashboard queries should join/union across both when computing totals.

### 4.5 Provider Identity

| BurnLens | TokenLens | Conflict |
|----------|-----------|----------|
| Provider identified by proxy path prefix (`/proxy/openai/...`) | Provider identified by `ProviderConnection` record | **Different models.** |

**Decision needed:** In unified codebase, the proxy path determines provider for real-time data; the connection ID determines provider for billing sync. Both feed into the same usage tables. Map proxy paths → provider enum at ingestion time.

### 4.6 Tag/Feature Attribution

| BurnLens | TokenLens | Conflict |
|----------|-----------|----------|
| `X-BurnLens-Tag-*` headers → JSON `tags` column (feature, team, customer) | `feature_tag` string field on UsageRecord | **Different cardinality.** |

**Decision needed:** BurnLens's multi-tag approach (feature + team + customer as separate dimensions) is more powerful. Promote to the unified model. TokenLens's single `feature_tag` maps to BurnLens's `feature` tag. Add `team` and `customer` columns to the cloud schema.

### 4.7 Alert Rule Model

| BurnLens | TokenLens | Conflict |
|----------|-----------|----------|
| Config-file-defined budgets (daily/weekly/monthly limits in YAML) | DB-stored alert rules (CRUD via API) | **Different lifecycle.** |

**Decision needed:** Use DB-stored rules for cloud (CRUD via API/dashboard). Keep YAML-defined budgets for local-only mode as a convenience. On cloud sync, local YAML budgets could optionally push to the cloud alert rules table.

### 4.8 Authentication Model

| BurnLens | TokenLens | Conflict |
|----------|-----------|----------|
| No authentication (localhost only) | API key + org scoping | **No real conflict — BurnLens doesn't need auth in local mode.** |

**Decision needed:** Local mode remains unauthenticated (localhost). Cloud mode uses TokenLens's API key auth. When cloud sync is enabled, the sync client authenticates with the cloud API key.

---

## 5. Unified Data Model

### PostgreSQL Schema (Cloud + TimescaleDB for time-series)

```sql
-- ============================================================
-- MULTI-TENANT CORE
-- ============================================================

CREATE TABLE organizations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    slug            TEXT UNIQUE NOT NULL,
    api_key_hash    TEXT UNIQUE NOT NULL,          -- SHA-256
    tier            TEXT NOT NULL DEFAULT 'free',   -- free | personal | team | enterprise
    subscription_id TEXT,                           -- Lemon Squeezy
    subscription_status TEXT DEFAULT 'active',
    settings_json   JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- PROVIDER CONNECTIONS (cloud-managed credentials)
-- ============================================================

CREATE TABLE provider_connections (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    provider        TEXT NOT NULL,                  -- openai | anthropic | google | azure | bedrock
    display_name    TEXT,
    encrypted_key   BYTEA NOT NULL,                -- Fernet-encrypted API key
    sync_cursor     TEXT,                           -- resume pagination
    last_synced_at  TIMESTAMPTZ,
    is_active       BOOLEAN DEFAULT true,
    metadata_json   JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (org_id, provider, display_name)
);

-- ============================================================
-- REQUEST LOG (per-request from proxy — TimescaleDB hypertable)
-- ============================================================

CREATE TABLE request_log (
    id                  BIGSERIAL,
    org_id              UUID NOT NULL REFERENCES organizations(id),
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider            TEXT NOT NULL,
    model               TEXT NOT NULL,
    request_path        TEXT,
    -- tokens
    input_tokens        INTEGER DEFAULT 0,
    output_tokens       INTEGER DEFAULT 0,
    reasoning_tokens    INTEGER DEFAULT 0,
    cache_read_tokens   INTEGER DEFAULT 0,
    cache_write_tokens  INTEGER DEFAULT 0,
    -- cost
    cost_usd            NUMERIC(12,8) NOT NULL DEFAULT 0,
    -- metadata
    duration_ms         INTEGER,
    status_code         INTEGER,
    system_prompt_hash  TEXT,                       -- SHA-256 (privacy)
    -- attribution
    tag_feature         TEXT,
    tag_team            TEXT,
    tag_customer        TEXT,
    tags_json           JSONB DEFAULT '{}',         -- extensible
    -- sync
    synced_at           TIMESTAMPTZ,
    PRIMARY KEY (id, timestamp)                     -- required for hypertable
);

-- Convert to TimescaleDB hypertable (7-day chunks)
SELECT create_hypertable('request_log', 'timestamp', chunk_time_interval => INTERVAL '7 days');

-- Indexes for common query patterns
CREATE INDEX idx_request_log_org_time ON request_log (org_id, timestamp DESC);
CREATE INDEX idx_request_log_model ON request_log (org_id, model, timestamp DESC);
CREATE INDEX idx_request_log_team ON request_log (org_id, tag_team, timestamp DESC);
CREATE INDEX idx_request_log_customer ON request_log (org_id, tag_customer, timestamp DESC);

-- ============================================================
-- USAGE AGGREGATES (daily rollups from billing API sync)
-- ============================================================

CREATE TABLE usage_daily (
    id              BIGSERIAL PRIMARY KEY,
    org_id          UUID NOT NULL REFERENCES organizations(id),
    connection_id   UUID REFERENCES provider_connections(id),
    recorded_date   DATE NOT NULL,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    operation       TEXT DEFAULT 'default',
    -- tokens
    input_tokens    BIGINT DEFAULT 0,
    output_tokens   BIGINT DEFAULT 0,
    cache_read_tokens  BIGINT DEFAULT 0,
    cache_write_tokens BIGINT DEFAULT 0,
    total_tokens    BIGINT DEFAULT 0,
    -- cost
    input_cost_usd  NUMERIC(12,8) DEFAULT 0,
    output_cost_usd NUMERIC(12,8) DEFAULT 0,
    total_cost_usd  NUMERIC(12,8) DEFAULT 0,
    -- volume
    api_calls       INTEGER DEFAULT 0,
    avg_latency_ms  NUMERIC(10,2),
    -- attribution
    tag_feature     TEXT,
    tag_team        TEXT,
    tag_customer    TEXT,
    -- metadata
    raw_metadata    JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (org_id, provider, model, recorded_date, tag_feature, operation)
);

CREATE INDEX idx_usage_daily_org_date ON usage_daily (org_id, recorded_date DESC);

-- ============================================================
-- AI ASSET INVENTORY (shadow detection)
-- ============================================================

CREATE TABLE ai_assets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id),
    provider        TEXT NOT NULL,
    model_name      TEXT NOT NULL,
    endpoint_url    TEXT,
    api_key_hash    TEXT,                           -- SHA-256 fingerprint, never raw key
    -- ownership
    owner_team      TEXT,
    project         TEXT,
    -- classification
    status          TEXT NOT NULL DEFAULT 'shadow', -- shadow | active | approved | inactive | deprecated
    risk_tier       TEXT DEFAULT 'unclassified',   -- unclassified | low | medium | high
    -- spend
    monthly_spend_usd   NUMERIC(12,4) DEFAULT 0,
    monthly_requests    INTEGER DEFAULT 0,
    -- timestamps
    first_seen_at   TIMESTAMPTZ DEFAULT now(),
    last_active_at  TIMESTAMPTZ DEFAULT now(),
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    -- extensible
    tags_json       JSONB DEFAULT '{}',
    UNIQUE (org_id, provider, model_name, api_key_hash)
);

CREATE INDEX idx_assets_org_status ON ai_assets (org_id, status);
CREATE INDEX idx_assets_org_team ON ai_assets (org_id, owner_team);

-- ============================================================
-- DISCOVERY EVENTS (append-only audit log)
-- ============================================================

CREATE TABLE discovery_events (
    id              BIGSERIAL PRIMARY KEY,
    org_id          UUID NOT NULL REFERENCES organizations(id),
    asset_id        UUID REFERENCES ai_assets(id),
    event_type      TEXT NOT NULL,                  -- new_asset_detected | model_changed | provider_changed | key_rotated | asset_inactive | spend_spike
    details_json    JSONB DEFAULT '{}',
    detected_at     TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_events_org_time ON discovery_events (org_id, detected_at DESC);
CREATE INDEX idx_events_asset ON discovery_events (asset_id, detected_at DESC);

-- Immutability: prevent UPDATE and DELETE on discovery_events
CREATE OR REPLACE FUNCTION prevent_modify() RETURNS TRIGGER AS $$
BEGIN RAISE EXCEPTION 'discovery_events is append-only'; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER no_update BEFORE UPDATE ON discovery_events FOR EACH ROW EXECUTE FUNCTION prevent_modify();
CREATE TRIGGER no_delete BEFORE DELETE ON discovery_events FOR EACH ROW EXECUTE FUNCTION prevent_modify();

-- ============================================================
-- PROVIDER SIGNATURES (fingerprinting for shadow detection)
-- ============================================================

CREATE TABLE provider_signatures (
    id              SERIAL PRIMARY KEY,
    provider        TEXT UNIQUE NOT NULL,
    endpoint_pattern TEXT NOT NULL,                 -- glob pattern
    header_signature JSONB DEFAULT '{}',
    model_field_path TEXT
);

-- ============================================================
-- OPTIMIZATION RESULTS
-- ============================================================

CREATE TABLE optimization_results (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                  UUID NOT NULL REFERENCES organizations(id),
    optimization_type       TEXT NOT NULL,           -- legacy_model | model_downgrade | prompt_caching | batch_eligible | prompt_compression | provider_arbitrage | context_bloat | duplicate_request | prompt_waste
    severity                TEXT NOT NULL,           -- critical | high | medium | low
    title                   TEXT NOT NULL,
    detail                  TEXT,
    affected_model          TEXT,
    affected_feature        TEXT,
    -- economics
    current_monthly_cost    NUMERIC(12,4),
    projected_monthly_cost  NUMERIC(12,4),
    monthly_savings         NUMERIC(12,4),
    confidence_pct          INTEGER,
    -- lifecycle
    is_applied              BOOLEAN DEFAULT false,
    is_dismissed            BOOLEAN DEFAULT false,
    created_at              TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_opt_org_active ON optimization_results (org_id)
    WHERE NOT is_applied AND NOT is_dismissed;

-- ============================================================
-- ALERT RULES
-- ============================================================

CREATE TABLE alert_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id),
    name            TEXT NOT NULL,
    -- trigger
    metric          TEXT NOT NULL,                  -- daily_spend | weekly_spend | monthly_spend | model_spend | provider_spend | feature_spend | team_spend | customer_spend | token_count
    period          TEXT DEFAULT 'daily',           -- daily | weekly | monthly
    threshold       NUMERIC(12,4) NOT NULL,
    threshold_pct   INTEGER[],                      -- [80, 90, 100] for budget-style alerts
    -- filters
    provider_filter TEXT,
    model_filter    TEXT,
    team_filter     TEXT,
    customer_filter TEXT,
    -- dispatch
    webhook_url     TEXT,
    slack_webhook   TEXT,
    email_recipients TEXT[],
    terminal_notify BOOLEAN DEFAULT false,
    -- state
    is_active       BOOLEAN DEFAULT true,
    last_triggered_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- BILLING & LICENSING
-- ============================================================

CREATE TABLE webhook_events (
    id              SERIAL PRIMARY KEY,
    webhook_id      TEXT UNIQUE NOT NULL,
    event_name      TEXT NOT NULL,
    processed_at    TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- CONTINUOUS AGGREGATES (TimescaleDB materialized views)
-- ============================================================

-- Hourly rollup for dashboard queries
CREATE MATERIALIZED VIEW request_log_hourly
WITH (timescaledb.continuous) AS
SELECT
    org_id,
    time_bucket('1 hour', timestamp) AS bucket,
    provider,
    model,
    tag_team,
    tag_feature,
    COUNT(*) AS request_count,
    SUM(input_tokens) AS total_input_tokens,
    SUM(output_tokens) AS total_output_tokens,
    SUM(cost_usd) AS total_cost,
    AVG(duration_ms) AS avg_latency_ms
FROM request_log
GROUP BY org_id, bucket, provider, model, tag_team, tag_feature;

-- Daily rollup for reports
CREATE MATERIALIZED VIEW request_log_daily
WITH (timescaledb.continuous) AS
SELECT
    org_id,
    time_bucket('1 day', timestamp) AS bucket,
    provider,
    model,
    tag_team,
    tag_feature,
    tag_customer,
    COUNT(*) AS request_count,
    SUM(input_tokens) AS total_input_tokens,
    SUM(output_tokens) AS total_output_tokens,
    SUM(reasoning_tokens) AS total_reasoning_tokens,
    SUM(cache_read_tokens) AS total_cache_read_tokens,
    SUM(cost_usd) AS total_cost,
    AVG(duration_ms) AS avg_latency_ms
FROM request_log
GROUP BY org_id, bucket, provider, model, tag_team, tag_feature, tag_customer;
```

### Local SQLite Schema (Subset — No Multi-Tenancy)

The local SQLite schema mirrors the above but:
- No `org_id` columns (single-tenant)
- No `organizations` or `provider_connections` tables
- No `webhook_events` table
- `request_log` replaces `requests` table with the same columns
- `usage_daily` stores billing API aggregates
- Same `ai_assets`, `discovery_events`, `provider_signatures` tables
- No TimescaleDB features (no hypertables, no continuous aggregates)
- Append-only triggers on `discovery_events` using SQLite triggers

---

## 6. Recommended File Structure

```
burnlens/                               # Monorepo root
├── pyproject.toml                      # Shared Python build config
├── README.md
├── LICENSE
├── CLAUDE.md
├── AUDIT.md                            # This file
├── docker-compose.yml                  # Cloud deployment
├── Dockerfile                          # Cloud container
│
├── packages/
│   ├── core/                           # Shared business logic (pip: burnlens-core)
│   │   ├── pyproject.toml
│   │   └── burnlens_core/
│   │       ├── __init__.py
│   │       ├── cost/
│   │       │   ├── calculator.py       # Token → USD (from BurnLens)
│   │       │   ├── pricing.py          # JSON loader (from BurnLens)
│   │       │   └── pricing_data/       # JSON files (from BurnLens)
│   │       ├── analysis/
│   │       │   ├── waste.py            # Waste detectors (from BurnLens)
│   │       │   ├── recommender.py      # Model recommendations (from BurnLens)
│   │       │   ├── optimizer.py        # Rule engine (from TokenLens, extended)
│   │       │   └── budget.py           # Budget tracking + forecasting (from BurnLens)
│   │       ├── models/
│   │       │   ├── records.py          # RequestRecord, UsageDaily dataclasses
│   │       │   ├── assets.py           # AiAsset, DiscoveryEvent, ProviderSignature
│   │       │   └── alerts.py           # AlertRule, BudgetAlert dataclasses
│   │       ├── providers/
│   │       │   ├── base.py             # UsageProvider ABC (from TokenLens)
│   │       │   ├── openai.py           # OpenAI billing parser
│   │       │   ├── anthropic.py        # Anthropic billing parser
│   │       │   └── google.py           # Google billing parser
│   │       ├── detection/
│   │       │   ├── classifier.py       # Shadow asset classification (from BurnLens)
│   │       │   └── signatures.py       # Provider fingerprinting (from BurnLens)
│   │       └── config/
│   │           ├── pricing_config.py   # Model tier definitions
│   │           └── providers.py        # Provider routing config
│   │
│   ├── local/                          # Local proxy + CLI (pip: burnlens)
│   │   ├── pyproject.toml              # Minimal deps: fastapi, httpx, aiosqlite, typer, rich, pyyaml
│   │   └── burnlens/
│   │       ├── __init__.py             # wrap() export
│   │       ├── __main__.py
│   │       ├── cli.py                  # Typer CLI (from BurnLens)
│   │       ├── config.py              # YAML config loader (from BurnLens)
│   │       ├── proxy/
│   │       │   ├── server.py           # FastAPI proxy (from BurnLens)
│   │       │   ├── interceptor.py      # Request interception (from BurnLens)
│   │       │   ├── streaming.py        # SSE passthrough (from BurnLens)
│   │       │   └── providers.py        # Route mapping (from BurnLens)
│   │       ├── storage/
│   │       │   ├── sqlite_db.py        # SQLite backend (from BurnLens)
│   │       │   └── queries.py          # SQLite queries (from BurnLens)
│   │       ├── detection/
│   │       │   ├── wrapper.py          # SDK wrap() (from BurnLens)
│   │       │   ├── billing.py          # Billing API runner (from BurnLens)
│   │       │   └── scheduler.py        # APScheduler jobs
│   │       ├── alerts/
│   │       │   ├── engine.py           # Alert evaluation (from BurnLens)
│   │       │   ├── slack.py
│   │       │   ├── terminal.py
│   │       │   └── email.py
│   │       ├── dashboard/
│   │       │   ├── routes.py           # JSON API (from BurnLens)
│   │       │   └── static/             # HTML + Chart.js (from BurnLens)
│   │       ├── cloud/
│   │       │   └── sync.py             # Anonymised push to cloud (from BurnLens)
│   │       ├── telemetry/
│   │       │   └── otel.py             # OpenTelemetry export
│   │       ├── doctor.py
│   │       ├── export.py
│   │       └── patch.py
│   │
│   └── cloud/                          # Cloud SaaS backend (docker: burnlens-cloud)
│       ├── pyproject.toml              # Deps: fastapi, sqlalchemy, asyncpg, redis, resend, cryptography
│       ├── Dockerfile
│       └── burnlens_cloud/
│           ├── __init__.py
│           ├── app.py                  # FastAPI app factory
│           ├── config.py              # Pydantic BaseSettings (env-var driven)
│           ├── db/
│           │   ├── engine.py           # SQLAlchemy async engine (from TokenLens)
│           │   ├── models.py           # ORM models (from TokenLens, extended)
│           │   └── migrations/         # Alembic migrations
│           ├── api/
│           │   ├── auth.py             # API key authentication (from TokenLens)
│           │   ├── connections.py       # Connection CRUD (from TokenLens)
│           │   ├── usage.py            # Usage endpoints (merged)
│           │   ├── assets.py           # Asset endpoints (from BurnLens)
│           │   ├── discovery.py        # Discovery events (from BurnLens)
│           │   ├── optimizations.py    # Optimization CRUD (from TokenLens)
│           │   ├── alerts.py           # Alert rule CRUD (merged)
│           │   ├── export.py           # CSV/JSON export (merged)
│           │   └── billing.py          # Lemon Squeezy webhooks (from TokenLens)
│           ├── services/
│           │   ├── sync_worker.py      # Billing API sync (from TokenLens)
│           │   ├── ingest.py           # Receive proxy pushes (cloud sync endpoint)
│           │   ├── optimizer.py        # Extended optimizer (merged)
│           │   └── discovery_engine.py # Shadow detection (from BurnLens)
│           ├── middleware/
│           │   └── rate_limit.py       # Redis rate limiting (from TokenLens)
│           ├── lib/
│           │   ├── encryption.py       # Fernet for API keys (from TokenLens)
│           │   ├── license.py          # License validation (from TokenLens)
│           │   ├── email.py            # Resend transactional email (from TokenLens)
│           │   └── seeds.py            # Demo data generator (from TokenLens)
│           └── alerts/
│               ├── engine.py           # Alert evaluation (merged)
│               ├── slack.py            # Slack blocks (from BurnLens)
│               └── webhook.py          # Generic webhook (from TokenLens)
│
├── frontend/                           # Next.js cloud dashboard (from TokenLens)
│   ├── package.json
│   ├── next.config.js
│   └── src/
│       ├── app/
│       │   ├── page.tsx                # Landing page
│       │   ├── dashboard/              # Main dashboard (extended)
│       │   ├── assets/                 # NEW: AI asset inventory
│       │   ├── discovery/              # NEW: Discovery events timeline
│       │   ├── optimizations/
│       │   ├── connections/
│       │   ├── alerts/
│       │   ├── settings/
│       │   └── setup/
│       ├── components/
│       └── lib/
│
└── tests/
    ├── core/                           # Core library tests
    ├── local/                          # Proxy + CLI tests
    ├── cloud/                          # Cloud API tests
    └── e2e/                            # Playwright E2E tests
```

---

## 7. Build Sequence

### Phase 1: Core Extraction + Local Preservation

**Deliverable:** `packages/core` and `packages/local` working independently. `pip install burnlens` still works exactly as today.

**Tasks:**
1. Create monorepo structure with `packages/core`, `packages/local`, `packages/cloud`, `frontend`
2. Extract shared logic into `packages/core`:
   - Cost calculator + pricing loader + pricing JSON files
   - Data models (dataclasses)
   - Provider billing parsers (refactored to TokenLens's ABC pattern)
   - Shadow detection classifier + signatures
   - Waste detectors
   - Budget tracker + forecasting
3. Refactor `packages/local` to import from `burnlens-core`
4. Verify: `pip install burnlens` works, all existing tests pass, `burnlens start` works

**Definition of done:**
- All existing BurnLens tests pass
- `burnlens start && curl localhost:8420/health` returns 200
- `burnlens top`, `burnlens report`, `burnlens analyze` all work
- No regressions in proxy streaming or cost calculation
- `packages/core` is independently installable

---

### Phase 2: Cloud Backend + Unified Schema

**Deliverable:** `packages/cloud` running with PostgreSQL + TimescaleDB, receiving data from local proxies via cloud sync, with all TokenLens features working.

**Tasks:**
1. Set up PostgreSQL + TimescaleDB schema (from Section 5)
2. Port TokenLens backend to `packages/cloud`:
   - Multi-tenant org model + API key auth
   - Provider connection CRUD with encrypted credentials
   - Billing API sync worker (using core's provider parsers)
   - Optimization engine (using core's waste detectors + TokenLens's optimizer)
   - Alert rule CRUD + evaluation
3. Build cloud ingest endpoint (receives anonymised data from local proxies)
4. Implement data retention / purge (tier-aware)
5. Port TokenLens billing integration (Lemon Squeezy)
6. Add rate limiting (Redis)
7. Docker compose: cloud backend + PostgreSQL + TimescaleDB + Redis

**Definition of done:**
- Cloud API passes all TokenLens test cases
- Local proxy can sync to cloud (`burnlens sync` pushes data)
- Dashboard shows data from both proxy (real-time) and billing API (daily)
- Multi-tenant isolation verified (org A cannot see org B's data)
- TimescaleDB continuous aggregates working for dashboard queries

---

### Phase 3: Frontend Unification + Launch

**Deliverable:** Unified Next.js dashboard with all features from both products. Marketing site. Public launch.

**Tasks:**
1. Extend TokenLens frontend with BurnLens-unique views:
   - AI Asset Inventory page (shadow detection, approve/deprecate workflow)
   - Discovery Events timeline
   - Waste analysis dashboard
   - Team/customer budget dashboards
   - Per-request request log viewer (drill-down from aggregates)
2. Add local-mode dashboard redirect: `burnlens ui` can optionally open cloud dashboard
3. Landing page update (pricing, features, local vs. cloud comparison)
4. E2E tests for all new pages
5. Documentation: local quickstart, cloud setup, migration guide
6. CI/CD pipeline: monorepo build, test matrix, Docker publish

**Definition of done:**
- All dashboard pages render with real data
- E2E tests pass for critical flows (setup → connect → view data → optimize → alert)
- `pip install burnlens` installs local-only (< 7 deps)
- `docker compose up` launches full cloud stack
- Privacy story verified: no prompt content in cloud database
- README and docs updated for both modes

---

*End of audit.*
