# BurnLens Cloud Backend

Cloud aggregation and billing service for BurnLens — enables multi-tenant cost tracking, dashboard access, and Stripe billing integration.

## Overview

The BurnLens cloud backend is a separate service (deployed on Vercel) that:

1. **Receives anonymised cost records** from OSS proxies via `POST /api/v1/ingest`
2. **Stores them in PostgreSQL** by workspace (multi-tenant)
3. **Serves a dashboard API** scoped to authenticated workspaces
4. **Manages Stripe billing** for plan upgrades
5. **Issues JWT tokens** for secure dashboard access

## Architecture

- **Runtime:** FastAPI on Vercel Services
- **Database:** Vercel Postgres (PostgreSQL 16+)
- **Auth:** JWT tokens + API keys
- **Billing:** Stripe webhooks

## Local Development

### Prerequisites

- Python 3.11+
- PostgreSQL 14+ (local or Docker)
- Stripe account (for testing webhooks)

### Setup

1. Clone and install dependencies:

```bash
cd burnlens-cloud
pip install -e ".[dev]"
```

2. Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
# Edit .env with your PostgreSQL connection and Stripe keys
```

3. Start Vercel dev environment (auto-handles database, routing, env vars):

```bash
vercel dev -L
```

This starts the FastAPI app at `http://localhost:3000` with all routes mounted under `/api/`.

### Testing Local Endpoints

```bash
# Sign up
curl -X POST http://localhost:3000/api/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","workspace_name":"Test"}'

# Login
curl -X POST http://localhost:3000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"api_key":"bl_live_..."}'

# Ingest records
curl -X POST http://localhost:3000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "api_key":"bl_live_...",
    "records":[{
      "timestamp":"2024-01-15T10:30:00Z",
      "provider":"openai",
      "model":"gpt-4o",
      "input_tokens":100,
      "output_tokens":50,
      "cost_usd":0.015,
      "tags":{"team":"backend"}
    }]
  }'

# Get summary (requires JWT)
curl -X GET http://localhost:3000/api/summary?period=7d \
  -H "Authorization: Bearer <token>"
```

## API Reference

### Authentication

**`POST /auth/signup`**

Create a new workspace.

Request:
```json
{
  "email": "you@company.com",
  "workspace_name": "Acme AI"
}
```

Response:
```json
{
  "api_key": "bl_live_...",
  "workspace_id": "uuid",
  "message": "Workspace created. Check email for next steps."
}
```

**`POST /auth/login`**

Authenticate and get JWT token.

Request:
```json
{
  "api_key": "bl_live_..."
}
```

Response:
```json
{
  "token": "eyJ...",
  "expires_in": 86400,
  "workspace": {
    "id": "uuid",
    "name": "Acme AI",
    "plan": "free"
  }
}
```

### Ingest

**`POST /api/v1/ingest`**

Bulk ingest cost records from OSS proxy.

Request:
```json
{
  "api_key": "bl_live_...",
  "records": [
    {
      "timestamp": "2024-01-15T10:30:00Z",
      "provider": "openai",
      "model": "gpt-4o",
      "input_tokens": 100,
      "output_tokens": 50,
      "reasoning_tokens": 0,
      "cache_read_tokens": 0,
      "cache_write_tokens": 0,
      "cost_usd": 0.015,
      "duration_ms": 1250,
      "status_code": 200,
      "tags": {"team": "backend", "feature": "search"},
      "system_prompt_hash": "sha256hash"
    }
  ]
}
```

Response:
```json
{
  "accepted": 100,
  "rejected": 0
}
```

**Error Responses:**

- `401 Unauthorized` — Invalid API key
- `429 Too Many Requests` — Free tier limit exceeded (10k records/month)
- `500 Internal Server Error` — Database error

### Dashboard API

All dashboard endpoints require JWT authentication via `Authorization: Bearer <token>` header.

**`GET /api/summary`** — Cost summary for period

Query params: `period=7d|30d|90d|...` (clamped by plan)

Response:
```json
{
  "total_cost_usd": 123.45,
  "total_requests": 5000,
  "avg_cost_per_request_usd": 0.0247,
  "models_used": 3
}
```

**`GET /api/costs/by-model`** — Cost by model

Response:
```json
[
  {
    "model": "gpt-4o",
    "provider": "openai",
    "request_count": 1000,
    "total_input_tokens": 50000,
    "total_output_tokens": 10000,
    "total_cost_usd": 45.50
  }
]
```

**`GET /api/costs/by-tag`** — Cost by team/feature/customer

Query params: `tag_type=team|feature|customer` (default: team)

**`GET /api/costs/timeline`** — Cost over time

Query params: `period=7d`, `granularity=daily|hourly`

**`GET /api/requests`** — Recent requests

Query params: `limit=50`, `period=7d`

**`GET /api/customers`** — Cost by customer

**`GET /api/waste`** — Waste detection findings (MVP: stub)

**`GET /api/budget`** — Budget status (MVP: stub)

### Billing

**`GET /billing/portal`**

Get Stripe billing portal URL for plan management.

Requires JWT authentication.

Response:
```json
{
  "url": "https://billing.stripe.com/b/session_..."
}
```

**`POST /billing/webhooks/stripe`**

Stripe webhook endpoint for subscription events.

Vercel automatically forwards to this endpoint. Configure in Stripe dashboard:
- Webhook URL: `https://api.burnlens.app/billing/webhooks/stripe`
- Events: `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`

## Plans

| Plan | Monthly Cost | Requests/Month | History | Users |
|------|----------|---------|---------|-------|
| **Free** | $0 | 10,000 | 7 days | 1 |
| **Cloud** | $29 | Unlimited | 90 days | 3 |
| **Teams** | $99 | Unlimited | 1 year | 10 |
| **Enterprise** | Custom | Unlimited | Custom | Custom |

History retention is clamped by plan:
- Free: 7 days max (regardless of `?days` param)
- Cloud: 90 days max
- Teams: 1 year max
- Enterprise: 3650 days

## Deployment

### Deploy to Vercel

```bash
# Link to Vercel
vercel link

# Set environment variables in Vercel dashboard
vercel env pull  # (or set manually in dashboard)

# Deploy
vercel deploy --prod
```

Environment variables (set in Vercel dashboard):

- `DATABASE_URL` — Vercel Postgres connection string (auto-generated)
- `JWT_SECRET` — Random 32-char hex string (generate: `python -c "import secrets; print(secrets.token_hex(32))"`)
- `STRIPE_API_KEY` — Stripe secret key (`sk_live_...`)
- `STRIPE_WEBHOOK_SECRET` — Stripe webhook signing secret (`whsec_...`)
- `ENVIRONMENT` — `production`
- `LOG_LEVEL` — `INFO`

### Vercel Postgres Setup

1. Connect Vercel Postgres in Vercel dashboard (Project Settings → Storage)
2. The connection string is automatically available as `DATABASE_URL`
3. Tables are created on first app startup

### Stripe Setup

1. Create products in Stripe:
   - **Cloud** — $29/month
   - **Teams** — $99/month
   - **Enterprise** — Custom

2. Get webhook secret:
   - Stripe dashboard → Developers → Webhooks
   - Add endpoint: `https://api.burnlens.app/billing/webhooks/stripe`
   - Events: `customer.subscription.*`, `invoice.payment_failed`
   - Copy signing secret and set as `STRIPE_WEBHOOK_SECRET`

## Testing

```bash
pytest tests/
pytest tests/ -v  # Verbose
pytest tests/ --cov=burnlens_cloud  # With coverage
```

## Troubleshooting

### Database Connection Error

**Error:** `Error while connecting to database`

**Solution:**

1. Check `DATABASE_URL` is set correctly
2. For local dev, ensure PostgreSQL is running:
   ```bash
   psql -c "SELECT 1"  # Should return 1
   ```
3. For Vercel, ensure Vercel Postgres is created and connected

### Stripe Webhook Not Firing

**Error:** Subscription events not updating workspace plan

**Solution:**

1. Check webhook URL in Stripe dashboard matches your app URL
2. Verify `STRIPE_WEBHOOK_SECRET` is set correctly
3. Check app logs for webhook errors
4. Test webhook manually in Stripe dashboard

### Free Tier Limit

**Error:** `429 Too Many Requests` with `"error": "free_tier_limit"`

**Solution:** Upgrade workspace to Cloud tier or wait until next month for limit reset

## Development Notes

### Adding New Dashboard API Endpoints

1. Add schema to `burnlens_cloud/models.py`
2. Add query to `burnlens_cloud/dashboard_api.py`
3. Decorate with `@router.get()` and `verify_token` dependency
4. Query must filter by `workspace_id` from token
5. Clamp period by plan using `clamp_days_by_plan()`

### Database Migrations

Currently using raw DDL on startup. For future migrations:

```bash
alembic init migrations
alembic revision --autogenerate -m "Description"
alembic upgrade head
```

### API Key Format

- **Live keys:** `bl_live_` + 32 random hex chars
- **Test keys:** `bl_test_` + 32 random hex chars

Keys are stored as-is in the database and never logged.

## License

Apache 2.0 — See main BurnLens repo for details.
