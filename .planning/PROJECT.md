# BurnLens

## What This Is

BurnLens is an open-source LLM FinOps tool — a transparent proxy + CLI + dashboard that shows developers where their AI API money goes. `pip install burnlens && burnlens start` — zero code changes, see every LLM API call's real cost.

## Core Value

Complete visibility into AI API spending with zero code changes — if you can't see it, you can't control it.

## Current Milestone: v1.1 Billing & Quota

**Goal:** Make the Paddle-backed plans real — surface the user's tier, let them manage billing in-app, and enforce plan limits so free/Cloud/Teams users can't exceed what they paid for.

**Target features:**
- Billing panel in Settings (plan info, invoices, manage subscription, upgrade/downgrade)
- Plan badge in Topbar (shipped — deep-links to /settings#billing)
- Quota definitions per plan (requests/mo, teams, retention, seats, API keys)
- Server-side enforcement at ingest (reject/throttle over-quota workspaces)
- Frontend gating (lock paywalled features, upgrade CTAs)
- Usage meter UI (consumption vs limit, warn at 80%)
- Paddle webhook handlers for subscription lifecycle (created/updated/canceled/past_due)

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
- ✓ Plan Limits Foundation (plan_limits table + resolver + per-workspace overrides) — v1.1 Phase 6
- ✓ Plan-Gated Features (LockedPanel with dynamic 402-driven copy, /teams + /customers migrated, frosted-glass teaser) — v1.1 Phase 10
- ✓ Usage Meter (sidebar meter with green/amber/red thresholds + Settings → Usage daily breakdown) — v1.1 Phase 10

### Active

- [ ] Billing Panel (view plan, invoices, manage subscription via Paddle)
- [ ] Plan Badge (Topbar pill showing current tier) — shipped pre-milestone
- [ ] Quota Definitions (per-plan limits: requests/mo, teams, retention, seats) — foundation shipped (Phase 6); enforcement next
- [ ] Quota Enforcement (server-side rejection/throttling when over-limit)
- [ ] Paddle Webhook Handlers (lifecycle events drive plan state)

### Out of Scope

- Policy enforcement or blocking of proxied LLM traffic — local proxy stays unmetered
- Compliance reporting — future milestone
- Regulatory framework mapping — future milestone
- Agent-based deep inspection of request/response payloads — metadata only
- Request/response payload logging — privacy/security concern
- Billing for the OSS local proxy — only cloud workspace usage is metered
- Custom/negotiated enterprise contracts — handled off-platform, not in-app

## Context

- BurnLens already ingests API billing and usage data from AI providers
- Paddle products already live: Cloud $29/mo (7-day trial), Teams $99/mo
- Auth session stores `plan` in localStorage — no enforcement wired up
- v1.1 is cloud-only scope — the local proxy/SQLite/CLI stay free and unmetered
- All quota logic lives in burnlens_cloud (Railway FastAPI + Postgres)
- Frontend is Next.js on Vercel (burnlens.app)
- Tech stack unchanged: no new infra, extend existing FastAPI + Postgres + Next.js
- Timeline target: 2–3 weeks of build effort

## Constraints

- **Tech stack**: Python 3.10+ / FastAPI / SQLite — must extend existing stack, no new infra
- **Dependencies**: 7 dependencies max principle — minimize additions
- **Privacy**: Never log/store request/response payloads — metadata only
- **Performance**: Proxy overhead must stay < 20ms
- **Deployment**: Railway (existing) — no infra changes needed
- **Compatibility**: Must not break existing BurnLens proxy/CLI/dashboard functionality

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Free tier for Phase 1 | Growth lever — teams that see AI sprawl want controls (Phase 2, paid) | ✓ Validated v1.0 |
| Agentless detection first | Zero additional setup for existing users, parse what BurnLens already collects | ✓ Validated v1.0 |
| SQLite for new tables | Consistent with existing stack, no external DB needed | ✓ Validated v1.0 |
| Metadata only, no payloads | Privacy/security — never store request/response content | ✓ Validated v1.0 |
| Paddle over Stripe | Handles global tax/VAT as merchant of record — less ops overhead | ✓ Validated (migrated 2026-04) |
| Quota enforcement at ingest | Single chokepoint — all cloud usage flows through POST /v1/ingest | — Pending |
| Local proxy stays unmetered | OSS product, zero friction for self-hosting | — Pending |

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
*Last updated: 2026-04-28 — Phase 10 (Feature Gating & Usage Visibility UI) shipped; v1.1 milestone code complete pending Phase 9 quota enforcement*
