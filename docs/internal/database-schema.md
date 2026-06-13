# Database Schema Specification — BurnLens

## 1. Local Database (SQLite — `~/.burnlens/burnlens.db`)

All tables are in SQLite 3 format and use Write-Ahead Logging (WAL) mode for concurrency.

### `requests`
Tracks cost, token counts, and attribution tags for every intercepted API call.
- `id` (INTEGER PRIMARY KEY AUTOINCREMENT)
- `request_id` (TEXT)
- `provider` (TEXT NOT NULL)
- `model` (TEXT NOT NULL)
- `request_path` (TEXT)
- `timestamp` (TEXT NOT NULL) — ISO 8601 UTC
- `input_tokens` (INTEGER DEFAULT 0)
- `output_tokens` (INTEGER DEFAULT 0)
- `reasoning_tokens` (INTEGER DEFAULT 0)
- `cache_read_tokens` (INTEGER DEFAULT 0)
- `cache_write_tokens` (INTEGER DEFAULT 0)
- `cost_usd` (REAL DEFAULT 0.0)
- `duration_ms` (INTEGER DEFAULT 0)
- `status_code` (INTEGER)
- `tag_feature` (TEXT)
- `tag_team` (TEXT)
- `tag_customer` (TEXT)
- `system_prompt_hash` (TEXT)
- `synced_at` (TIMESTAMP NULL) — Tracks status for SaaS cloud sync

### `ai_assets`
Inventory of discovered models, endpoints, and credentials.
- `id` (INTEGER PRIMARY KEY AUTOINCREMENT)
- `provider` (TEXT NOT NULL)
- `model_name` (TEXT NOT NULL)
- `endpoint_url` (TEXT NOT NULL)
- `api_key_hash` (TEXT) — SHA-256 hash
- `owner_team` (TEXT)
- `project` (TEXT)
- `status` (TEXT DEFAULT 'shadow') — active, inactive, shadow, approved, deprecated
- `risk_tier` (TEXT DEFAULT 'unclassified') — unclassified, low, medium, high
- `first_seen_at` (TEXT NOT NULL)
- `last_active_at` (TEXT NOT NULL)
- `monthly_spend_usd` (REAL DEFAULT 0.0)
- `monthly_requests` (INTEGER DEFAULT 0)
- `tags` (TEXT DEFAULT '{}') — Serialized JSON metadata

### `provider_signatures`
Regular expression/glob rules matching endpoint domains to provider adapters.
- `id` (INTEGER PRIMARY KEY AUTOINCREMENT)
- `provider` (TEXT NOT NULL UNIQUE)
- `endpoint_pattern` (TEXT NOT NULL) — Glob matching pattern (e.g. `api.openai.com/*`)
- `header_signature` (TEXT DEFAULT '{}') — JSON mapping of matching headers
- `model_field_path` (TEXT DEFAULT 'body.model') — Path to resolve model name in payload

### `discovery_events`
Append-only log recording Shadow AI events. Deletes and updates are blocked by DB triggers.
- `id` (INTEGER PRIMARY KEY AUTOINCREMENT)
- `event_type` (TEXT NOT NULL) — new_asset_detected, model_changed, provider_changed, key_rotated, asset_inactive
- `asset_id` (INTEGER REFERENCES ai_assets(id) NULL)
- `details` (TEXT DEFAULT '{}') — Serialized JSON metadata
- `detected_at` (TEXT NOT NULL)

### `anomaly_events`
Logs detected anomalies (cost spikes and runaway loops).
- `id` (INTEGER PRIMARY KEY AUTOINCREMENT)
- `event_type` (TEXT NOT NULL) — cost_spike, runaway_loop
- `scope` (TEXT NOT NULL) — org, team, app, customer, api_key, model
- `target` (TEXT NOT NULL) — name of the scope target (e.g. model name or 'engineering')
- `severity` (TEXT NOT NULL) — warning, critical
- `detected_at` (TEXT NOT NULL) — ISO 8601 UTC
- `details` (TEXT DEFAULT '{}') — Serialized JSON containing current values, baseline stats, and description

### `fired_alerts`
Tracks alert deduplication state to prevent redundant notifications.
- `id` (INTEGER PRIMARY KEY AUTOINCREMENT)
- `alert_key` (TEXT NOT NULL UNIQUE) — deduplication key format `anomaly:{event_type}:{scope}:{target}:{window_name}`
- `alert_type` (TEXT NOT NULL) — cost_spike, runaway_loop
- `fired_at` (TEXT NOT NULL) — ISO 8601 UTC

---

## 2. Cloud Database (PostgreSQL — `burnlens.app` SaaS)

Used by the Vercel FastAPI backend for multi-tenant aggregation.

### `users`
- `id` (UUID PRIMARY KEY DEFAULT gen_random_uuid())
- `email` (TEXT UNIQUE NOT NULL)
- `name` (TEXT)
- `google_id` (TEXT UNIQUE)
- `github_id` (TEXT UNIQUE)
- `created_at` (TIMESTAMPTZ)
- `last_login` (TIMESTAMPTZ)

### `workspaces`
- `id` (UUID PRIMARY KEY DEFAULT gen_random_uuid())
- `name` (TEXT NOT NULL)
- `plan` (TEXT DEFAULT 'free') — free, cloud, teams, enterprise
- `api_key_hash` (TEXT UNIQUE NOT NULL) — SHA-256 hash of `bl_live_` key
- `stripe_customer_id` (TEXT)
- `stripe_subscription_id` (TEXT)

### `workspace_members`
Links users to workspaces with role permissions.
- `workspace_id` (UUID REFERENCES workspaces(id) ON DELETE CASCADE)
- `user_id` (UUID REFERENCES users(id) ON DELETE CASCADE)
- `role` (TEXT NOT NULL) — owner, admin, viewer
- PRIMARY KEY (`workspace_id`, `user_id`)

### `requests`
Anonymized sync data pushed from local proxies.
- `id` (BIGSERIAL PRIMARY KEY)
- `workspace_id` (UUID REFERENCES workspaces(id) ON DELETE CASCADE)
- `timestamp` (TIMESTAMPTZ NOT NULL)
- `provider` (TEXT NOT NULL)
- `model` (TEXT NOT NULL)
- `input_tokens` (INTEGER)
- `output_tokens` (INTEGER)
- `reasoning_tokens` (INTEGER)
- `cache_read_tokens` (INTEGER)
- `cache_write_tokens` (INTEGER)
- `cost_usd` (NUMERIC(18,8))
- `duration_ms` (INTEGER)
- `tag_feature` (TEXT)
- `tag_team` (TEXT)
- `tag_customer` (TEXT)
- `system_prompt_hash` (TEXT)
- Index on (`workspace_id`, `timestamp`)
