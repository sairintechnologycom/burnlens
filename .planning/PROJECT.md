# BurnLens

## What This Is

BurnLens is an open-source LLM FinOps tool — a transparent proxy + CLI + dashboard that shows developers where their AI API money goes, plus a cloud SaaS layer that enforces billing plans, tracks usage quotas, and surfaces team-level AI spending. `pip install burnlens && burnlens start` — zero code changes, see every LLM API call's real cost.

## Core Value

Complete visibility into AI API spending with zero code changes — if you can't see it, you can't control it.

## Requirements

### Validated

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

### Active

- [ ] Hard quota enforcement at ingest (429 on over-quota) — v1.2 scope
- [ ] Password reset + email verification (Auth Essentials) — v1.2 scope
- [ ] Cloud alerting — lift budget alert logic into Railway cron for org owners — v1.2 scope
- [ ] API key plaintext reveal via `/api-keys` CRUD (foundation shipped in Phase 9) — available for v1.2 frontend integration

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

- v1.1 shipped 2026-04-30: full billing + quota enforcement live on Railway + Vercel
- Paddle products live: Cloud $29/mo (7-day trial), Teams $99/mo — plan_limits table is authoritative
- Cloud backend: `burnlens_cloud/` on Railway (FastAPI + asyncpg + Postgres)
- Frontend: `burnlens.app` on Vercel (Next.js App Router, TypeScript, custom CSS)
- Auth: session.plan + apiKey in localStorage after login; `verify_token` on all cloud routes
- OSS proxy (`burnlens/`) releases independently on PyPI — v0.3.1 current; 0.1.2/0.2.0 in flight (ROADMAP-OSS.md)
- Codebase: ~241 files, ~50k LOC total; Python (cloud backend) + TypeScript/Next.js (frontend)
- Tech stack unchanged from v1.0: FastAPI + asyncpg + Postgres + Next.js + Paddle

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
| Quota enforcement at POST /v1/ingest | Single chokepoint — all cloud usage flows through here | — v1.2 (hard 429 deferred) |

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
*Last updated: 2026-04-30 after v1.1 milestone — Billing & Quota shipped*
