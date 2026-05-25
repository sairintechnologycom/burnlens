# BurnLens

## What This Is

BurnLens is an open-source LLM FinOps tool — a transparent proxy + CLI + dashboard that shows developers where their AI API money goes, plus a cloud SaaS layer that enforces billing plans, tracks usage quotas, and surfaces team-level AI spending. `pip install burnlens && burnlens start` — zero code changes, see every LLM API call's real cost.

## Core Value

Complete visibility into AI API spending with zero code changes — if you can't see it, you can't control it.

## Current Milestone: v1.4 Usage Dashboard Improvements

**Goal:** Land the usage analytics UX that was deferred from v1.3 — give users a real way to slice, filter, and export their cloud usage data.

**Target features:**
- Date-range picker (7d / 30d / 90d / custom) wired into all dashboard charts (DASH-01)
- Cost breakdown by model — ranked table or chart (DASH-02)
- CSV export of filtered usage rows (DASH-03)
- Daily cost trend chart with model-distribution overlay (DASH-04)

**Last phase number:** 17 (v1.4 starts at Phase 18)

## Requirements

### Validated

- ✓ Password reset + email verification (Auth Essentials, soft-gate) — v1.2
- ✓ Transactional email system (typed TemplateSpec registry, 6 SendGrid templates) — v1.2
- ✓ Server-side budget alerting (Railway cron, 24h dedup, email + Slack) — v1.2
- ✓ Alert management UI (/alerts page, toggle/edit/threshold, viewer-role enforcement) — v1.2
- ✓ Budget-aware model downgrade routing (decide_route, fail-open, downgrade map) — v1.2
- ✓ Transparent proxy for OpenAI, Anthropic, Google — v0.1.0
- ✓ Cost calculation from token usage — v0.1.0
- ✓ SQLite storage with WAL mode — v0.1.0
- ✓ Streaming SSE passthrough — v0.1.0
- ✓ CLI commands (start, stop, top, report, analyze, ui) — v0.3.0
- ✓ Dashboard with Chart.js — v0.3.0
- ✓ Budget tracking and alerts (Slack, terminal) — v0.3.0
- ✓ Waste detection (bloat, duplicates, overkill, prompt waste) — v0.3.0
- ✓ Tag extraction from headers — v0.3.0
- ✓ burnlens doctor command — v0.3.1
- ✓ AI Asset Registry (detect, catalog, track all AI endpoints) — v1.0
- ✓ Shadow AI Detection (flag unapproved models/keys/providers) — v1.0
- ✓ Provider Signature Matching (auto-detect providers from API patterns) — v1.0
- ✓ Discovery Event Log (audit trail for all detection events) — v1.0
- ✓ Discovery Dashboard (single-pane AI footprint view) — v1.0
- ✓ Alert System for Discovery (shadow detected, model change, spend spike) — v1.0
- ✓ Asset Management API (list, filter, approve, assign assets) — v1.0
- ✓ Custom Provider Signatures (for self-hosted/private models) — v1.0
- ✓ Plan Limits Foundation (plan_limits table + resolve_limits() + per-workspace overrides) — v1.1
- ✓ Paddle Lifecycle Sync (webhook handlers + BillingContext + plan badge in Topbar) — v1.1
- ✓ Billing Self-Service (upgrade/downgrade/cancel/reactivate/invoices in Settings) — v1.1
- ✓ Quota Tracking & Soft Enforcement (monthly counters, 80%/100% emails, seat/API-key 402s, retention pruning, entitlement middleware) — v1.1
- ✓ Plan-Gated Features (LockedPanel with dynamic 402-driven copy + frosted-glass teaser + upgrade CTAs) — v1.1
- ✓ Usage Meter (sidebar meter with green/amber/red thresholds + Settings → Usage daily breakdown) — v1.1
- ✓ Hard 429 quota enforcement at ingest (API calls + tokens + spend cap + seat count, structured `QuotaExceededDetail` body) — v1.3
- ✓ API key management UI (`/api-keys` — list/revoke/create/label/scope, viewer-creator scoped per D-04) — v1.3
- ✓ Resend-verification fix for API-key users with null `owner_email` (server-side JWT identity source, fail-open) — v1.3 (AUTH-08)
- ✓ Google model routing via URL-path rewrite (polymorphic Provider hook, additive to v1.2 body rewrite) — v1.3 (ROUTE-08)

### Active (v1.4)

- [ ] Usage dashboard date-range picker — preset 7d/30d/90d + custom range, all charts respect filter (DASH-01)
- [ ] Cost breakdown by model — ranked table or chart for selected period (DASH-02)
- [ ] CSV export of filtered usage rows (DASH-03)
- [ ] Daily cost trend chart with model-distribution overlay (DASH-04)

### Out of Scope

- Policy enforcement or blocking of proxied LLM traffic — local proxy stays unmetered (free forever)
- Compliance reporting — future milestone
- Regulatory framework mapping — future milestone
- Agent-based deep inspection of request/response payloads — metadata only
- Request/response payload logging — privacy/security concern
- Custom/negotiated enterprise contracts — handled off-platform, not in-app
- Usage-based overage billing (pay-as-you-go) — v1.3+
- Annual plans and prepaid credits — v1.3+
- Self-serve plan editing for end users (admin-only via deploy in v1.1) — v1.3+

## Context

- v1.3 shipped 2026-05-25: hard 429 ingest quota enforcement, full API key lifecycle UI, AUTH-08 resend-verification fix, Google URL-path routing closed; 147 files changed, +22k/-13k lines, 119 commits over 18 days
- v1.2 shipped 2026-05-06: auth essentials, cloud alerting, alert UI, and budget-aware routing live
- v1.1 shipped 2026-04-30: full billing + quota enforcement live on Railway + Vercel
- Paddle products live: Cloud $29/mo (7-day trial), Teams $99/mo — plan_limits table is authoritative
- Cloud backend: `burnlens_cloud/` on Railway (FastAPI + asyncpg + Postgres)
- Frontend: `burnlens.app` on Vercel (Next.js App Router, TypeScript, custom CSS)
- Auth: JWT with `email_verified` + `role` claims; `verify_token` on all cloud routes
- OSS proxy (`burnlens/`) releases independently on PyPI — v0.3.1 current (ROADMAP-OSS.md)
- Codebase: ~422 files (181 changed in v1.2), ~52k Python LOC + frontend TypeScript
- Tech stack unchanged: FastAPI + asyncpg + Postgres + Next.js + Paddle + SendGrid

## Constraints

- **Tech stack**: Python 3.10+ / FastAPI / SQLite — must extend existing stack, no new infra
- **Dependencies**: 7 dependencies max principle for OSS proxy — minimize additions
- **Privacy**: Never log/store request/response payloads — metadata only
- **Performance**: Proxy overhead must stay < 20ms
- **Deployment**: Railway (cloud backend) + Vercel (frontend) — no infra changes needed
- **Compatibility**: Must not break existing BurnLens proxy/CLI/dashboard functionality

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Free tier for OSS proxy | Growth lever — teams that see AI sprawl want controls (cloud features, paid) | ✓ Validated v1.0 |
| Agentless detection first | Zero additional setup for existing users, parse what BurnLens already collects | ✓ Validated v1.0 |
| SQLite for OSS tables | Consistent with existing stack, no external DB needed | ✓ Validated v1.0 |
| Metadata only, no payloads | Privacy/security — never store request/response content | ✓ Validated v1.0 |
| Paddle over Stripe | Handles global tax/VAT as merchant of record — less ops overhead | ✓ Validated v1.1 |
| plan_limits as Postgres source of truth | Single chokepoint for all limit/quota logic; workspace overrides via JSONB merge | ✓ Validated v1.1 |
| Paddle webhooks are authoritative for plan state | App reads, never computes from checkout redirect — avoids race conditions | ✓ Validated v1.1 |
| Soft enforcement only in v1.1 | Need real usage data before choosing 429 thresholds; seat/key 402s are sufficient initially | ✓ Validated v1.1 |
| Entitlement middleware is mandatory (not just UI gating) | UI gating can be bypassed; 402 at route level is the real gate | ✓ Validated v1.1 |
| Local proxy stays unmetered | OSS product, zero friction for self-hosting — only cloud workspaces have quotas | ✓ Validated v1.1 |
| Quota enforcement at POST /v1/ingest | Single chokepoint — all cloud usage flows through here | ✓ Validated v1.3 |
| `decide_route()` never raises | Fail-open is non-negotiable for a proxy — any routing error must passthrough the original model | ✓ Validated v1.2 |
| Budget priority: customer > team > global_usd > budget_limit_usd | Customer budget is most specific, global is fallback — respects scoping hierarchy | ✓ Validated v1.2 |
| Verify-email as POST (not GET) | GET token in URL leaks to server logs, referrer headers, and browser history (CR-03) | ✓ Validated v1.2 |
| SSRF guard on Slack webhook URL | Rejects any URL not starting with https://hooks.slack.com/ — prevents SSRF via org-owner-controlled config | ✓ Validated v1.2 |
| `QuotaExceededDetail` as structured Pydantic JSON body | Clients parse `dimension/current/limit` programmatically instead of regexing free text | ✓ Validated v1.3 |
| Viewer-creator scoping (D-04) for API keys | Cross-creator access returns 404 indistinguishability (not 403) — prevents key-existence enumeration | ✓ Validated v1.3 |
| Resend-verification reads identity from server-side JWT | Never trust client-supplied email — closes AUTH-08 W-01 and prevents enumeration regressions | ✓ Validated v1.3 |
| Polymorphic `rewrite_path_for_routing()` Provider hook | Extensible — future providers can add path rewriting without core changes (closes ROUTE-08) | ✓ Validated v1.3 |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-25 after v1.3 milestone close — Phases 15–17 shipped (Hard Ingest Quota Enforcement, API Key Management, Google URL-Path Routing). Phase 18 / DASH-01–04 deferred to v1.4.*
