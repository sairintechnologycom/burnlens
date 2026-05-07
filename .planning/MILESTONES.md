# Milestones

## v0.x — Core Proxy & FinOps (Shipped)

**Goal:** Build the foundational LLM FinOps proxy with cost tracking, dashboard, and CLI.

**Shipped:**
- v0.1.0: Transparent proxy (OpenAI, Anthropic, Google), cost calculation, SQLite storage, streaming SSE
- v0.3.0: Full feature release — CLI commands, dashboard, budget alerts, waste detection, tags
- v0.3.1: Normalize model display names, strip date suffixes, burnlens doctor

**Last phase number:** 0 (no GSD phases — pre-GSD development)

---

## v1.0 — Shadow AI Discovery & Inventory (Shipped)

**Goal:** Extend cost tracking into automated Shadow AI Discovery and Inventory system.
**Started:** 2026-04-10
**Completed:** 2026-04-15
**Status:** Shipped

**Shipped:**
- 5 phases: Data Foundation, Detection Engine, Asset Management API, Alert System, Discovery Dashboard
- AI asset registry with auto-detection and shadow classification
- Provider signature matching, discovery event audit log
- Discovery dashboard with Chart.js
- Alert system for shadow endpoints, model changes, spend spikes

**Last phase number:** 5

---

## v1.1 — Billing & Quota (Shipped)

**Goal:** Surface the user's tier, let them manage billing in-app, and enforce plan limits so free/Cloud/Teams users can't exceed what they paid for.
**Started:** 2026-04-18
**Completed:** 2026-04-30
**Status:** Shipped

**Shipped:**
- 5 phases (6–10), 31 plans, 178 commits
- 241 files changed, +48,179 / -1,478 lines (12 days)
- Plan limits Postgres table with `resolve_limits()` SQL function; Free/Cloud/Teams seeded with live Paddle IDs
- Paddle webhook lifecycle sync (subscription.created/updated/canceled/payment_failed) + `BillingContext` React provider
- Full billing self-service loop: upgrade/downgrade/cancel/reactivate/invoices — 5 backend endpoints + 3 frontend modals
- Quota tracking: monthly counters, 80%/100% warning emails, seat/API-key 402s, daily retention pruning, entitlement middleware
- Feature gating UI: LockedPanel with frosted-glass CTAs; UsageMeter with green/amber/red thresholds; daily breakdown in Settings

**Known deferred items at close: 25 (see STATE.md Deferred Items)**

**Last phase number:** 10

---

## v1.2 — Account Security & Notifications (Shipped)

**Goal:** Close the auth-UX gaps and add server-side alerting so cloud users can recover accounts, verify email ownership, and get notified when spend crosses thresholds — without needing the local proxy running.
**Started:** 2026-04-30
**Completed:** 2026-05-06
**Status:** Shipped

**Shipped:**
- 4 phases (11–14), 22 plans, ~150 commits
- 181 files changed, +23,628 / -1,830 lines (7 days)
- Password reset + email verification flows with single-use RETURNING-safe tokens; `BillingStatusBanner` for soft-gate verification; typed TemplateSpec registry with 6 SendGrid templates; grandfathering for pre-v1.2 users
- `alert_rules` + `alert_events` Postgres schema with idempotent 80%/100% seeding; hourly Railway cron with 24h dedup; email + SSRF-guarded Slack dispatch; fail-open cron error handling
- `/alerts` management page with toggle/edit/threshold UX; viewer-role enforcement via `isOwner`; IDOR-protected GET+PATCH backend endpoints; sidebar nav entry
- `decide_route()` in OSS proxy with 60s team-spend cache, fail-open semantics, provider downgrade map; DB columns `routed_model`+`downgrade_reason`; "Downgrades Today" dashboard stat card; `burnlens routing` CLI command; 12-test suite

**Known deferred items at close:**
- W-01: Resend-verification button silently no-ops for API-key users with null `owner_email` in localStorage
- Hard ingest 429 quota enforcement deferred to v1.3 pending real usage data
- Google URL-path model routing (downgrade map uses body rewrite only)

**Last phase number:** 14

---

## Parallel stream — OSS Proxy (Coding-Agent Wedge)

**Scope:** Open-source PyPI package `burnlens/` only. Independent release line from cloud v1.x.
**Goal:** Ship 0.1.2 (streaming token fix + CSV export) and 0.2.0 (git-aware tagging + per-API-key daily hard cap + coding-agent docs) to capture the April–October 2026 coding-agent governance window.
**Started:** 2026-04-21
**Status:** 0.1.2 in flight — **I-1 active (Google/Anthropic streaming token extraction)**
**Tracker:** `.planning/ROADMAP-OSS.md`
**Imported docs:** `.planning/oss/` (spec, prompts, standing orders)
