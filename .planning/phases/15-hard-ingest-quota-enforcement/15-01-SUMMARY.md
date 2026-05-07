---
phase: "15-hard-ingest-quota-enforcement"
plan: "01"
subsystem: "cloud-ingest"
tags: ["schema-migration", "quota", "wave-1", "postgres", "pydantic"]
dependency_graph:
  requires:
    - "15-00 — RED TDD scaffold (test_phase15_quota_hard.py)"
  provides:
    - "burnlens_cloud/database.py — 4 idempotent column migrations + 8-column resolve_limits() SQL function"
    - "burnlens_cloud/models.py — QuotaExceededDetail model + extended ResolvedLimits"
    - "burnlens_cloud/plans.py — resolve_limits() wrapper passing monthly_token_cap and monthly_spend_cap_usd"
  affects:
    - "burnlens_cloud/ingest.py — Plan 02 will import QuotaExceededDetail and call resolve_limits() to enforce caps"
tech_stack:
  added: []
  patterns:
    - "DO $$ IF NOT EXISTS ALTER TABLE pattern for idempotent Postgres column migrations"
    - "CREATE OR REPLACE FUNCTION for zero-downtime SQL function upgrades"
    - "NULL = unlimited convention for plan cap fields (QUOTA-02, QUOTA-03)"
key_files:
  created: []
  modified:
    - burnlens_cloud/database.py
    - burnlens_cloud/models.py
    - burnlens_cloud/plans.py
decisions:
  - "monthly_token_cap BIGINT NULL (not NOT NULL DEFAULT 0) — NULL semantics = unlimited; avoids accidental enforcement on existing workspaces (T-15-02 accept)"
  - "monthly_spend_cap_usd NUMERIC(12,2) NULL on plan_limits; NUMERIC(12,8) NOT NULL DEFAULT 0 on workspace_usage_cycles — different precision for caps vs. accumulators"
  - "resolve_limits() RETURNS TABLE adds monthly_token_cap BIGINT and monthly_spend_cap_usd NUMERIC — NUMERIC (no precision) in RETURNS TABLE is compatible with asyncpg Decimal type"
  - "QuotaExceededDetail uses float for current and limit fields — covers both int and float values; avoids float|int union syntax for Python 3.10+ compatibility"
metrics:
  duration: "2m"
  completed_date: "2026-05-07"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 3
---

# Phase 15 Plan 01: Hard Ingest Quota Enforcement — Schema & Model Layer Summary

**One-liner:** 4 idempotent Postgres column migrations (token_count, spend_usd on workspace_usage_cycles; monthly_token_cap, monthly_spend_cap_usd on plan_limits) plus 8-column resolve_limits() SQL function and QuotaExceededDetail Pydantic model establishing the data layer contract for Plan 02 enforcement.

## Tasks Completed

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 1 | Schema migrations + updated resolve_limits() SQL function (6 to 8 columns) | 2bcc8ef | burnlens_cloud/database.py |
| 2 | QuotaExceededDetail model + ResolvedLimits extension + plans.py wrapper update | 41a5142 | burnlens_cloud/models.py, burnlens_cloud/plans.py |

## Verification Results

```
grep -c "monthly_token_cap" burnlens_cloud/database.py     # 5 (>= 4 required)
grep -c "monthly_spend_cap_usd" burnlens_cloud/database.py # 5 (>= 4 required)

resolve_limits() RETURNS TABLE now has 8 columns:
  plan, monthly_request_cap, seat_count, retention_days,
  api_key_count, gated_features, monthly_token_cap, monthly_spend_cap_usd

QuotaExceededDetail exists in models.py
ResolvedLimits has monthly_token_cap: Optional[int] and monthly_spend_cap_usd: Optional[float]
plans.py constructor passes both new fields from asyncpg row dict

python -c "from burnlens_cloud.models import QuotaExceededDetail, ResolvedLimits; print('OK')"
# OK

pytest tests/test_phase15_quota_hard.py --collect-only -q
# 16 tests collected, 0 collection errors
```

## Schema Changes

### workspace_usage_cycles — new columns

| Column | Type | Default | Purpose |
|--------|------|---------|---------|
| token_count | BIGINT NOT NULL | 0 | Accumulates sum(input+output+reasoning tokens) per cycle (QUOTA-02) |
| spend_usd | NUMERIC(12,8) NOT NULL | 0 | Accumulates sum(cost_usd) per cycle (QUOTA-03) |

### plan_limits — new columns

| Column | Type | Default | Purpose |
|--------|------|---------|---------|
| monthly_token_cap | BIGINT | NULL | Monthly token ceiling; NULL = unlimited (QUOTA-02) |
| monthly_spend_cap_usd | NUMERIC(12,2) | NULL | Monthly spend ceiling in USD; NULL = unlimited (QUOTA-03) |

## Model Changes

### QuotaExceededDetail (new)

Structured 429 response detail for POST /v1/ingest quota violations:
- `error: str = "quota_exceeded"`
- `dimension: str` — which quota was breached ("requests", "tokens", "spend_usd", "seats")
- `current: float` — workspace's current usage value
- `limit: float` — plan ceiling that was exceeded
- `retry_after: str = "next billing cycle"`

### ResolvedLimits (extended)

Added two new fields between `api_key_count` and `gated_features`:
- `monthly_token_cap: Optional[int] = None`
- `monthly_spend_cap_usd: Optional[float] = None`

### plans.py resolve_limits() wrapper

Extended ResolvedLimits constructor call to include:
- `monthly_token_cap=row["monthly_token_cap"]`
- `monthly_spend_cap_usd=row["monthly_spend_cap_usd"]`

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. This plan is schema/model layer only. No enforcement logic was added; that is Plan 02.

## Threat Surface Scan

The resolve_limits() SQL function update adds two new COALESCE expressions reading from workspaces.limit_overrides JSONB:
- `(w.limit_overrides->>'monthly_token_cap')::bigint` — explicit cast; invalid string returns NULL (falls back to plan default, not bypass). T-15-01 mitigation applied.
- `(w.limit_overrides->>'monthly_spend_cap_usd')::numeric` — same pattern.

No new network endpoints, auth paths, or file access patterns introduced. Changes are confined to database schema migrations and Pydantic models.

## Self-Check

Files modified:
- [x] burnlens_cloud/database.py exists and contains `monthly_token_cap` (5 occurrences)
- [x] burnlens_cloud/models.py exists and contains `QuotaExceededDetail` class
- [x] burnlens_cloud/plans.py exists and contains `monthly_token_cap=row["monthly_token_cap"]`

Commits:
- [x] 2bcc8ef — feat(15-01): add schema migrations and update resolve_limits() to 8 columns
- [x] 41a5142 — feat(15-01): add QuotaExceededDetail model and extend ResolvedLimits with cap fields

## Self-Check: PASSED
