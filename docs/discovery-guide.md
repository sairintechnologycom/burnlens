# BurnLens Discovery: Shadow AI Detection & Inventory

BurnLens Discovery automatically detects, catalogs, and monitors every AI model and provider used across your organization. It surfaces shadow AI usage — unapproved models, personal API keys, unknown endpoints — so you can see your full AI footprint in one place.

## Table of Contents

- [Quick Start](#quick-start)
- [How It Works](#how-it-works)
- [Configuration](#configuration)
- [Discovery Dashboard](#discovery-dashboard)
- [API Reference](#api-reference)
- [Alert Configuration](#alert-configuration)
- [Custom Provider Signatures](#custom-provider-signatures)
- [FAQ](#faq)

---

## Quick Start

Discovery is built into BurnLens and requires no additional setup for basic functionality. If you already have BurnLens running, the discovery dashboard is available at:

```
http://localhost:8420/ui/discovery
```

For automatic billing-based detection (recommended), add your provider admin keys to `burnlens.yaml`:

```yaml
# Provider admin API keys for billing-based detection
openai_admin_key: "sk-admin-..."
anthropic_admin_key: "sk-ant-admin-..."
```

Or via environment variables:

```bash
export OPENAI_ADMIN_KEY="sk-admin-..."
export ANTHROPIC_ADMIN_KEY="sk-ant-admin-..."
burnlens start
```

BurnLens will begin detecting AI assets within the first hour of startup.

---

## How It Works

### Detection Methods

BurnLens uses two detection approaches:

**1. Proxy-Based Detection (Automatic)**
Every API call routed through the BurnLens proxy is automatically cataloged. The model, provider, endpoint, and API key hash are extracted and stored in the asset registry. No configuration needed — this works out of the box.

**2. Billing API Detection (Requires Admin Keys)**
BurnLens periodically queries your provider billing APIs (OpenAI, Anthropic, Google) to discover usage that may not flow through the proxy. This catches:
- Direct API calls that bypass the proxy
- Usage from CI/CD pipelines
- Third-party tools using your API keys

The detection engine runs hourly and is fail-open — if a billing API query fails, the proxy continues operating normally.

### Shadow AI Classification

A detected AI endpoint is classified as **shadow** if:

1. The API key hash doesn't match any key in your registered key list
2. The provider/model combination is not in your approved models list
3. The endpoint URL doesn't match any known provider signature
4. The calling service/team is not recognized in BurnLens's org hierarchy

Shadow assets appear in the dashboard's alert panel and trigger notifications (if configured).

### Asset Lifecycle

```
Detected → shadow → (user reviews) → approved
                                    → deprecated
                                    → inactive (auto, after 30 days no activity)
```

---

## Configuration

All discovery settings go in `burnlens.yaml` (or `~/.burnlens/config.yaml`).

### Minimal Configuration (Proxy Detection Only)

```yaml
# No extra config needed — proxy detection is automatic
port: 8420
```

### Full Configuration (Billing Detection + Alerts)

```yaml
port: 8420

# Admin API keys for billing-based detection
openai_admin_key: "sk-admin-..."
anthropic_admin_key: "sk-ant-admin-..."

# Alert channels
alerts:
  slack_webhook: "https://hooks.slack.com/services/T.../B.../xxx"
  terminal: true
  alert_recipients:
    - "security@yourcompany.com"
    - "platform-lead@yourcompany.com"

# Email transport (required if alert_recipients is set)
email:
  smtp_host: smtp.gmail.com
  smtp_port: 587
  smtp_user: burnlens@yourcompany.com
  smtp_password: your-app-password
  from: "BurnLens <burnlens@yourcompany.com>"
```

### Environment Variable Overrides

Admin keys can be set via env vars (takes priority over YAML):

| Env Var | Description |
|---------|-------------|
| `OPENAI_ADMIN_KEY` | OpenAI admin/billing API key |
| `ANTHROPIC_ADMIN_KEY` | Anthropic admin/billing API key |

---

## Discovery Dashboard

Access the dashboard at `http://localhost:8420/ui/discovery`.

### Summary Cards

Five KPI cards at the top:

| Card | Description |
|------|-------------|
| **Total Assets** | All detected AI models/endpoints |
| **Active This Month** | Assets with API calls in the current month |
| **Shadow Detected** | Unregistered/unapproved AI usage |
| **Unassigned** | Assets not yet assigned to a team |
| **Monthly Spend** | Total AI spend for the current month (USD) |

### Provider Breakdown

Donut chart showing asset count and spend split by provider (OpenAI, Anthropic, Google, Azure, Bedrock, etc.).

### Asset Table

Sortable, filterable table with columns:

| Column | Description |
|--------|-------------|
| Model | AI model identifier (e.g. `gpt-4o`, `claude-sonnet-4-20250514`) |
| Provider | AI provider name |
| Team | Assigned team (editable) |
| Status | `active`, `shadow`, `approved`, `inactive`, `deprecated` |
| Risk Tier | `unclassified`, `low`, `medium`, `high` |
| Spend | Current month spend in USD |
| First Seen | When this asset was first detected |
| Last Active | Most recent API call observed |

### Shadow AI Alert Panel

Highlighted list of shadow endpoints that need review. Each entry has inline actions:
- **Approve** — mark as approved (changes status from `shadow` to `approved`)
- **Assign** — assign to a team

### Filters & Search

- **Global search**: searches across model name, provider, team, endpoint URL, and tags
- **Filter dropdowns**: provider, status, risk tier, team, date range
- **Saved views**: save filter combinations for quick access (e.g. "All shadow in production"). Saved views persist in your browser's localStorage.

### Discovery Timeline

Chronological log of discovery events: new assets detected, model changes, status transitions, and alerts triggered.

---

## API Reference

All endpoints are under `/api/v1/assets`, `/api/v1/discovery`, and `/api/v1/providers`. The interactive OpenAPI docs are available at `http://localhost:8420/docs` when the proxy is running.

### Assets

#### List Assets

```
GET /api/v1/assets
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `provider` | string | Filter by provider (e.g. `openai`, `anthropic`) |
| `status` | string | Filter by status (`active`, `shadow`, `approved`, `inactive`, `deprecated`) |
| `owner_team` | string | Filter by team name |
| `risk_tier` | string | Filter by risk tier (`unclassified`, `low`, `medium`, `high`) |
| `date_since` | string | ISO date. Only assets first seen on or after this date |
| `search` | string | Full-text search across model, provider, team, endpoint, tags |
| `limit` | int | Page size (default: 50) |
| `offset` | int | Pagination offset (default: 0) |

**Response:**

```json
{
  "items": [
    {
      "id": 1,
      "provider": "anthropic",
      "model_name": "claude-sonnet-4-20250514",
      "endpoint_url": "api.anthropic.com/v1/messages",
      "api_key_hash": "a1b2c3...",
      "owner_team": "ML Platform",
      "project": null,
      "status": "approved",
      "risk_tier": "medium",
      "first_seen_at": "2026-05-15T10:30:00",
      "last_active_at": "2026-06-01T14:00:00",
      "monthly_spend_usd": 1234.56,
      "monthly_requests": 45000,
      "tags": {"env": "production", "app": "chatbot-v2"},
      "created_at": "2026-05-15T10:30:00",
      "updated_at": "2026-06-01T14:00:00"
    }
  ],
  "total": 47,
  "limit": 50,
  "offset": 0
}
```

#### Get Asset Detail

```
GET /api/v1/assets/{id}
```

Returns the asset plus its 20 most recent discovery events.

#### Update Asset

```
PATCH /api/v1/assets/{id}
```

**Request Body** (all fields optional):

```json
{
  "owner_team": "ML Platform",
  "risk_tier": "medium",
  "tags": {"env": "production"},
  "status": "approved"
}
```

#### Get Dashboard Summary

```
GET /api/v1/assets/summary
```

**Response:**

```json
{
  "total": 47,
  "by_provider": {"openai": 20, "anthropic": 15, "google": 12},
  "by_status": {"active": 30, "shadow": 10, "approved": 5, "inactive": 2},
  "by_risk_tier": {"unclassified": 25, "low": 10, "medium": 8, "high": 4},
  "new_this_week": 3
}
```

#### List Shadow Assets

```
GET /api/v1/assets/shadow
```

Convenience endpoint that returns only shadow/unregistered AI endpoints.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `date_since` | string | Only shadow assets first seen on or after this ISO date |
| `date_until` | string | Only shadow assets first seen on or before this ISO date |
| `limit` | int | Page size (default: 50) |
| `offset` | int | Pagination offset (default: 0) |

#### Approve Shadow Asset

```
POST /api/v1/assets/{id}/approve
```

Transitions a shadow asset to `approved` status. Returns 409 if the asset is not in `shadow` status.

**Response:**

```json
{
  "asset": { "...asset fields..." },
  "event_id": 42
}
```

### Discovery Events

#### List Events

```
GET /api/v1/discovery/events
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `event_type` | string | Filter: `new_asset_detected`, `model_changed`, `provider_changed`, `key_rotated`, `asset_inactive` |
| `asset_id` | int | Filter by asset ID |
| `since` | string | Events detected on or after this ISO date |
| `until` | string | Events detected on or before this ISO date |
| `limit` | int | Max results (default: 50, max: 500) |

### Provider Signatures

#### List Signatures

```
GET /api/v1/providers/signatures
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `provider` | string | Filter by provider name |

Returns all known provider signatures (built-in + custom).

#### Create Custom Signature

```
POST /api/v1/providers/signatures
```

**Request Body:**

```json
{
  "provider": "my-local-llm",
  "endpoint_pattern": "llm.internal.company.com/*",
  "header_signature": {"keys": ["x-api-key"]},
  "model_field_path": "body.model"
}
```

---

## Alert Configuration

BurnLens can notify you through Slack and email when discovery events occur.

### Alert Types

| Alert | Channel | Timing | Trigger |
|-------|---------|--------|---------|
| Shadow AI detected | Slack + email | Immediate (hourly check) | New shadow endpoint found |
| New provider detected | Slack + email | Immediate (hourly check) | First-ever usage of a provider |
| Model version change | Email digest | Daily at 8 AM UTC | Model name changed on an existing asset |
| Asset inactive 30+ days | Email digest | Weekly (Monday 8 AM UTC) | No API calls for 30 days |
| Spend spike | Slack + email | Immediate (hourly check) | Asset spend exceeds 200% of 30-day average |

### Slack Setup

1. Create an [Incoming Webhook](https://api.slack.com/messaging/webhooks) in your Slack workspace
2. Add it to `burnlens.yaml`:

```yaml
alerts:
  slack_webhook: "https://hooks.slack.com/services/T.../B.../xxx"
```

### Email Setup

1. Configure SMTP transport:

```yaml
email:
  smtp_host: smtp.gmail.com
  smtp_port: 587
  smtp_user: burnlens@yourcompany.com
  smtp_password: your-app-password
  from: "BurnLens <burnlens@yourcompany.com>"
```

2. Add recipients:

```yaml
alerts:
  alert_recipients:
    - "security@yourcompany.com"
    - "platform-lead@yourcompany.com"
```

---

## Custom Provider Signatures

BurnLens ships with built-in signatures for: **OpenAI**, **Anthropic**, **Google AI**, **Azure OpenAI**, **AWS Bedrock**, **Cohere**, and **Mistral**.

For self-hosted or private models, add a custom signature via the API:

```bash
curl -X POST http://localhost:8420/api/v1/providers/signatures \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "vllm-internal",
    "endpoint_pattern": "llm.internal.mycompany.com/*",
    "header_signature": {"keys": ["authorization"]},
    "model_field_path": "body.model"
  }'
```

The `endpoint_pattern` uses glob matching (e.g. `*.mycompany.com/*`). The `model_field_path` is the JSONPath to the model name in the request body.

Once added, any API call matching the pattern will be automatically attributed to this provider.

---

## FAQ

### Does discovery require any code changes?

No. Proxy-based detection works automatically for all traffic routed through BurnLens. Billing-based detection only requires admin API keys in the config.

### How quickly are new assets detected?

- **Proxy traffic**: Detected on the first API call (real-time)
- **Billing API**: Detected within 1 hour (hourly polling)

### What data does BurnLens store about my API calls?

Discovery stores only metadata: model name, provider, endpoint URL, API key hash (SHA-256, never the raw key), token counts, cost, and timestamps. Request and response payloads are never stored.

### Can I detect AI usage that doesn't go through the proxy?

Yes, if you configure billing API admin keys. BurnLens will query your provider billing APIs to discover usage from any source — CI/CD pipelines, third-party tools, direct SDK calls, etc.

### How do I mark a shadow asset as approved?

Either click "Approve" in the dashboard's shadow alert panel, or call the API:

```bash
curl -X POST http://localhost:8420/api/v1/assets/42/approve
```

### Can I add custom tags to assets?

Yes, via the PATCH endpoint:

```bash
curl -X PATCH http://localhost:8420/api/v1/assets/42 \
  -H "Content-Type: application/json" \
  -d '{"tags": {"env": "production", "team": "ml-platform", "app": "chatbot"}}'
```

### What happens if a billing API is unreachable?

BurnLens is fail-open. If a provider API query fails, the error is logged and the proxy continues operating normally. Detection will retry on the next hourly cycle.
