# BurnLens Phase 1: Shadow AI Discovery & Inventory

## Build Specification for Claude Code

**Timeline:** Q2–Q3 2026 | **Duration:** 12 weeks | **Build effort:** ~6 weeks
**Reuse from BurnLens:** ~60% | **New code:** ~40%

---

## 1. Phase Overview

Extend BurnLens's existing AI cost tracking into an automated Shadow AI Discovery and Inventory system. This phase is the foundation — you cannot govern what you cannot see.

BurnLens already ingests API billing and usage data from AI providers (OpenAI, Anthropic, Google). Phase 1 reuses ~60% of this existing data pipeline to build a discovery layer that identifies every AI model, endpoint, and provider being used across the organization.

### Success Criteria

- Auto-detect and catalog 95%+ of AI API calls flowing through monitored accounts
- Surface shadow AI usage (unapproved models, personal API keys) within 24 hours of first call
- Assign every discovered AI asset to a team/project/cost center
- Deliver a single-pane discovery dashboard showing total AI footprint
- Ship as a free tier feature to drive BurnLens adoption (growth lever for Phase 2 monetization)

### Non-Goals (Phase 1)

- No policy enforcement or blocking (Phase 2)
- No compliance reporting (Phase 3)
- No regulatory framework mapping
- No agent-based deep inspection of request/response payloads

---

## 2. Data Model

### 2.1 AI Asset Registry Table — `ai_assets`

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `id` | UUID | uuid-v4 | Primary key |
| `provider` | ENUM | `anthropic` | AI provider: `openai`, `anthropic`, `google`, `azure_openai`, `bedrock`, `custom` |
| `model_name` | VARCHAR(255) | `claude-sonnet-4-20250514` | Specific model identifier as reported by provider |
| `endpoint_url` | TEXT | `api.anthropic.com/v1/messages` | API endpoint being called |
| `api_key_hash` | VARCHAR(64) | sha256 hash | Hashed API key for dedup (never store raw keys) |
| `owner_team_id` | FK | team-uuid | References existing BurnLens `teams` table |
| `project_id` | FK (nullable) | project-uuid | References BurnLens `projects` table |
| `status` | ENUM | `active` | `active`, `inactive`, `shadow`, `approved`, `deprecated` |
| `risk_tier` | ENUM | `unclassified` | `unclassified`, `low`, `medium`, `high` (user-assigned, defaults unclassified) |
| `first_seen_at` | TIMESTAMP | 2026-05-15T10:30:00Z | When this asset was first detected |
| `last_active_at` | TIMESTAMP | 2026-06-01T14:00:00Z | Most recent API call observed |
| `monthly_spend_usd` | DECIMAL(10,2) | 1234.56 | Current month spend (synced from BurnLens cost engine) |
| `monthly_requests` | INTEGER | 45000 | Current month request count |
| `tags` | JSONB | `{"env":"prod"}` | Flexible key-value tags for custom classification |
| `created_at` | TIMESTAMP | auto | Record creation timestamp |
| `updated_at` | TIMESTAMP | auto | Last record update |

### 2.2 Provider Signature Table — `provider_signatures`

Pre-populated reference table for auto-detecting providers from API call patterns. Extensible by users for custom/self-hosted models.

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `id` | UUID | uuid-v4 | Primary key |
| `provider` | ENUM | `anthropic` | Provider key |
| `endpoint_pattern` | TEXT | `api.anthropic.com/*` | Glob/regex match pattern |
| `header_signature` | JSONB | `{"keys":["x-api-key","anthropic-version"]}` | Expected headers |
| `model_field_path` | TEXT | `body.model` | JSONPath to model name in request |

**Seed data required for:** OpenAI, Anthropic, Google AI, Azure OpenAI, AWS Bedrock, Cohere, Mistral

### 2.3 Discovery Event Log — `discovery_events`

Append-only log of all discovery events. Used for audit trail and anomaly detection.

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `id` | BIGSERIAL | auto | Auto-increment PK |
| `event_type` | ENUM | `new_asset_detected` | `new_asset_detected`, `model_changed`, `provider_changed`, `key_rotated`, `asset_inactive` |
| `asset_id` | FK | uuid | References `ai_assets` table |
| `details` | JSONB | `{"old":"gpt-4","new":"gpt-4o"}` | Event-specific metadata |
| `detected_at` | TIMESTAMP | auto | When the event occurred |

---

## 3. API Specification

All endpoints extend the existing BurnLens FastAPI application. Auth uses the existing BurnLens API key/JWT mechanism.

### 3.1 Discovery Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/assets` | List all AI assets. Filters: `provider`, `status`, `team_id`, `risk_tier`. Pagination: `offset`/`limit`. |
| `GET` | `/api/v1/assets/{id}` | Get single asset detail with usage history |
| `PATCH` | `/api/v1/assets/{id}` | Update asset: assign team, set risk_tier, update tags, change status |
| `GET` | `/api/v1/assets/summary` | Dashboard summary: total assets, by provider, by status, by risk, new this week |
| `GET` | `/api/v1/assets/shadow` | List shadow/unregistered AI endpoints. Filter by detection date range. |
| `POST` | `/api/v1/assets/{id}/approve` | Mark a shadow asset as approved (changes status from `shadow` to `approved`) |
| `GET` | `/api/v1/discovery/events` | List discovery events. Filter by `event_type`, `asset_id`, date range. |
| `GET` | `/api/v1/providers/signatures` | List known provider signatures |
| `POST` | `/api/v1/providers/signatures` | Add custom provider signature (for self-hosted/private models) |

### 3.2 Example Response — `GET /api/v1/assets`

```json
{
  "data": [
    {
      "id": "uuid",
      "provider": "anthropic",
      "model_name": "claude-sonnet-4-20250514",
      "endpoint_url": "api.anthropic.com/v1/messages",
      "owner_team": { "id": "team-uuid", "name": "ML Platform" },
      "status": "approved",
      "risk_tier": "medium",
      "first_seen_at": "2026-05-15T10:30:00Z",
      "last_active_at": "2026-06-01T14:00:00Z",
      "monthly_spend_usd": 1234.56,
      "monthly_requests": 45000,
      "tags": { "env": "production", "app": "chatbot-v2" }
    }
  ],
  "meta": { "total": 47, "offset": 0, "limit": 20 }
}
```

---

## 4. Detection Engine

### 4.1 Agentless Detection (Primary — Ship First)

Parse data BurnLens already collects. Zero additional setup for existing users.

- **Billing API ingestion:** Parse OpenAI, Anthropic, Google billing APIs for model names, usage volumes, and API key identifiers
- **API gateway logs:** If user connects AWS API Gateway, Azure APIM, or Kong logs, parse for AI provider endpoint patterns
- **Cloud cost data:** Match AWS Cost Explorer / Azure Cost Management line items to known AI service SKUs
- **Provider signature matching:** Compare endpoint URLs and headers against the `provider_signatures` table

### 4.2 Agent-Based Detection (Optional — Phase 1.5)

Lightweight SDK wrapper for deeper visibility. Opt-in for teams wanting request-level granularity.

- **Python SDK wrapper:** `burnlens.wrap(openai_client)` intercepts calls and logs metadata (model, tokens, latency) without modifying payloads
- **Proxy mode:** HTTP proxy that teams point their AI SDK traffic through. Logs metadata only, forwards requests unchanged.
- **IMPORTANT:** Never log or store request/response payloads in Phase 1. Metadata only (model, token count, latency, status code).

### 4.3 Shadow AI Detection Logic

A detected AI endpoint is classified as `shadow` if ANY of the following are true:

1. The API key hash does not match any key in the org's registered key list
2. The provider/model combination is not in the org's approved models list (if configured)
3. The endpoint URL does not match any known provider signature and no custom signature exists
4. The calling service/team is not recognized in BurnLens's org hierarchy

### 4.4 Alert Triggers

| Trigger | Channel | Default Threshold |
|---------|---------|-------------------|
| New shadow AI endpoint detected | Slack + email | Immediate (within 1 hour) |
| New provider first seen | Slack + email | Immediate |
| Model version change | Email digest | Daily summary |
| Asset inactive >30 days | Email digest | Weekly summary |
| Spend spike on single asset | Slack + email | >200% of 30-day average |

---

## 5. Discovery Dashboard

React-based dashboard extending the existing BurnLens UI. Single-pane view answering: how many AI models are we running, who owns them, and what's new?

### 5.1 Dashboard Components

- **Summary cards:** Total AI assets | Active this month | Shadow detected | Unassigned | Monthly AI spend
- **Provider breakdown:** Donut chart showing asset count and spend by provider (OpenAI, Anthropic, Google, Azure, Other)
- **Asset table:** Sortable, filterable table — columns: Model, Provider, Team, Status, Risk, Spend, Last Active, First Seen
- **Shadow AI alert panel:** Highlighted list of unregistered/shadow endpoints requiring review, with approve/assign actions inline
- **Timeline:** Discovery event timeline showing when new assets appeared, model changes, and alerts triggered
- **New this week:** Quick-view section showing assets first detected in past 7 days

### 5.2 Filter/Search

- **Global search:** Search by model name, provider, team, endpoint URL, or tag
- **Filters:** Provider, status (active/inactive/shadow/approved), risk tier, team, date range
- **Saved views:** Let users save filter combinations (e.g., "all shadow assets in production")

---

## 6. Technical Implementation

### 6.1 Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Backend API | FastAPI (existing) | Add new router: `/api/v1/assets`, `/api/v1/discovery` |
| Database | PostgreSQL (existing) | New tables: `ai_assets`, `provider_signatures`, `discovery_events` |
| Detection engine | Python + APScheduler | Scheduled jobs parsing billing APIs every hour |
| Provider signatures | PostgreSQL + seed data | Pre-populated for OpenAI, Anthropic, Google, Azure OpenAI, Bedrock |
| Alerts | Slack webhook + email (Resend) | Reuse existing BurnLens notification system |
| Frontend | React + Recharts (existing) | New page: `/discovery` with dashboard components |
| Deployment | Railway (existing) | No infra changes needed, just new migration + code |

### 6.2 Database Migration

```sql
-- Migration: add_ai_governance_phase1
-- Creates: ai_assets, provider_signatures, discovery_events
-- Seeds: provider_signatures with known providers
-- Indexes: 
--   ai_assets(provider)
--   ai_assets(status)
--   ai_assets(owner_team_id)
--   ai_assets(last_active_at)
--   discovery_events(asset_id, detected_at)
```

### 6.3 File Structure (New Files)

```
app/
  models/
    ai_asset.py              # SQLAlchemy model for ai_assets
    provider_signature.py     # SQLAlchemy model for provider_signatures
    discovery_event.py        # SQLAlchemy model for discovery_events
  routers/
    assets.py                 # GET/PATCH /api/v1/assets endpoints
    discovery.py              # GET /api/v1/discovery/events
    providers.py              # GET/POST /api/v1/providers/signatures
  services/
    detection_engine.py       # Core detection logic
    shadow_detector.py        # Shadow AI classification
    provider_matcher.py       # Match API calls to providers
    alert_service.py          # Trigger Slack/email alerts
  jobs/
    discovery_scheduler.py    # APScheduler job definitions
    billing_parser.py         # Parse provider billing APIs
frontend/
  src/pages/
    Discovery.tsx             # Main discovery dashboard page
  src/components/discovery/
    AssetTable.tsx            # Sortable asset table
    ShadowAlertPanel.tsx      # Shadow AI review panel
    ProviderBreakdown.tsx     # Donut chart component
    DiscoveryTimeline.tsx     # Event timeline
    SummaryCards.tsx          # Top-level metric cards
```

---

## 7. Implementation Plan (6 Weeks)

| Week | Focus | Deliverables | Dependencies |
|------|-------|-------------|--------------|
| 1 | Data model + migration | Tables created, seed data loaded, models defined | Existing BurnLens DB access |
| 2 | Detection engine core | Billing API parsers for OpenAI, Anthropic, Google. Provider matcher working. | Provider API keys |
| 3 | Asset API endpoints | All REST endpoints functional with tests | Week 1 models |
| 4 | Shadow detection + alerts | Shadow classifier working, Slack/email alerts firing | Week 2 engine |
| 5 | Discovery dashboard UI | Dashboard page with all components, connected to APIs | Week 3 APIs |
| 6 | Testing + polish + deploy | Integration tests, edge cases, deploy to production | All prior weeks |

### 7.1 Testing Requirements

- **Unit tests** for detection engine: provider matching, shadow classification, alert triggers
- **Integration tests** for API endpoints: CRUD operations, filtering, pagination
- **End-to-end test:** Simulate billing data ingestion → detection → asset creation → alert fired
- **Edge cases:** Unknown provider, malformed billing data, duplicate detection, API key rotation

### 7.2 Pricing Strategy

Phase 1 ships as a **FREE feature** within BurnLens. The discovery dashboard is available to all BurnLens users. This serves as a growth lever: teams that see their AI sprawl will naturally want controls (Phase 2, paid).

### 7.3 Key Risks

| Risk | Mitigation |
|------|-----------|
| Provider API changes (billing APIs may change format) | Abstract parser interface, each provider is a plugin |
| False positives in shadow detection (personal test keys) | Allow users to whitelist known keys |
| Data volume (high-traffic orgs, millions of events) | Aggregate events by hour, archive older than 90 days |
