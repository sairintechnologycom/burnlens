# Codex-Ready Enhancement Rollout Plan for BurnLens

BurnLens is an open-source FinOps proxy for AI spend. This document outlines the phased roadmap for building out the local proxy, budget controls, anomaly detection, semantic cache, OTel exporting, and enterprise features.

## Recommended Phase Map

| Phase | Name                                   | Primary Outcome                                                    |
| ----: | -------------------------------------- | ------------------------------------------------------------------ |
|     0 | Repo Baseline & Release Safety (Done)  | Codex understands repo, current tests, and stable extension points |
|     1 | Event Contract & Attribution (Done)    | Canonical GenAI cost event schema                                  |
|     2 | Durable Local WAL & Idempotent Sync (Done) | No token/cost event loss during outages                            |
|     3 | OTel GenAI Compatibility (Done)       | Enterprise observability compatibility                             |
|     4 | Budget Engine v2 (Done)               | Real-time caps across org/team/app/customer/model                  |
|     5 | Anomaly & Runaway Agent Detection (Done) | Detect loops, spikes, abusive tenants, bad deploys                 |
|     6 | Prompt Overhead & Compression Analyzer (Done) | Identify redundant prompt/system/RAG/tool-schema waste             |
|     7 | Semantic Cache MVP (Done)              | Reduce duplicate LLM calls safely                                  |
|     8 | ClickHouse Analytics Plane (Done)      | High-cardinality, scalable analytics backend                       |
|     9 | Day-to-Day Mission Control Dashboard (Done) | Action cockpit for engineers and finance                           |
|    10 | Alerting + Click-to-Optimize Workflows | Slack/Teams/Jira/SNOW actions                                      |
|    11 | Optional Dynamic Model Routing (Done)  | Cost-aware fallback/degradation                                    |
|    12 | Enterprise Hardening                   | RBAC, SSO, audit, retention, compliance posture                    |

---

# Phase 0 — Repo Baseline & Release Safety [COMPLETED]

## Objective
Establish a safe engineering foundation before feature work.

## Technical Tasks
1. Add `ARCHITECTURE.md` (check existing `docs/ARCHITECTURE.md` and ensure completeness).
2. Add `CONTRIBUTING_AI.md` for Codex/Gemini/Claude agent instructions.
3. Add `docs/internal/current-state.md`.
4. Add `docs/internal/provider-flow.md`.
5. Add `docs/internal/database-schema.md`.
6. Add `docs/internal/release-checklist.md`.
7. Add a feature-flag helper module.
8. Add regression tests for current proxy, budget cap, streaming, CLI, and local DB behavior.

---

# Phase 1 — Canonical Event Contract & Attribution Model [COMPLETED]

## Objective
Create a canonical event schema for every LLM call.

## Technical Tasks
- Add typed event model (`GenAICostEvent` / `TokenUsageEvent`).
- Map existing provider usage into this event.
- Add metadata fields: `event_id`, `request_id`, `trace_id`, `workspace_id`, `org_id`, `team`, `feature`, `customer_hash`, `app_id`, `env`, `repo`, `branch`, `commit_sha`.
- Store pricing version on every event.
- Preserve database compatibility.
- Add tests.

---

# Phase 2 — Durable Local WAL & Idempotent Sync [COMPLETED]

## Objective
Make telemetry loss-resistant.

## Technical Tasks
- Add local append-only write-ahead event log (JSONL/MessagePack).
- UUIDv7/ULID event IDs with idempotency verification on insertion.
- Async workers for SQLite persistence and Cloud Sync pushing.
- WAL recovery, doctor, and DLQ replaying capabilities.

> [!NOTE]
> A detailed step-by-step implementation plan with failing tests, TDD steps, and command instructions has been generated at [2026-06-12-durable-local-wal-sync.md](file:///Users/bhushan/.gemini/antigravity-cli/brain/7d720b7c-33e1-4b9e-a049-c66c9419a88c/docs/plans/2026-06-12-durable-local-wal-sync.md). You can execute it task-by-task.

---

# Phase 3 — OpenTelemetry GenAI Compatibility [COMPLETED]

## Objective
Make BurnLens enterprise-ready via OTel conventions.

## Technical Tasks
- Add OTLP span and metrics exporters mapping `GenAICostEvent`.
- Map provider name, model, tokens, TTFT, latency, and status.
- Support trace propagation via `traceparent` headers.

> [!NOTE]
> A detailed step-by-step implementation plan with failing tests, TDD steps, and command instructions has been generated at [2026-06-12-otel-genai-compatibility.md](file:///Users/bhushan/Documents/Projects/burnlens/docs/plans/2026-06-12-otel-genai-compatibility.md). You can execute it task-by-task.

---

# Phase 4 — Budget Engine v2 [COMPLETED]

## Objective
Hierarchical, real-time budget enforcement.

## Technical Tasks
- Add YAML/JSON budget policy configuration model.
- Atomic counters for real-time tracking (SQLite initially, Redis later).
- Support pre-call estimation and post-call actual cost reconciliation.

---

# Phase 5 — Anomaly & Runaway Agent Detection [COMPLETED]

## Objective
Detect loop, spikes, retry storms, and abusive customers.

## Technical Tasks
- Continuously aggregate calls in sliding windows (1m, 5m, 15m, 1h).
- Run MAD/Z-score/statistical rules to flag cost spikes or runaway loops.
- Log to `anomaly_events` table and render on dashboard.

---

# Phase 6 — Prompt Overhead & Compression Analyzer

## Objective
Expose prompt token waste without violating privacy.

## Technical Tasks
- Local tokenization and classification into prompt sections (system, user, tools, RAG, history).
- Generate local recommendations (e.g. redundant system prompts, oversized schemas, low RAG output ratio).

---

# Phase 7 — Semantic Cache MVP

## Objective
Reduce duplicate LLM calls safely.

## Technical Tasks
- Build semantic caching using local vector index/SQLite vectors.
- Scope cache key by tenant/system prompt/workflow/policy.
- Add safety checks, bypass options, and cache telemetry.

---

# Phase 8 — ClickHouse Analytics Plane

## Objective
OLAP analytics backend for high-cardinality data.

## Technical Tasks
- Implement ClickHouse raw and rollup tables schema.
- Add Kafka/Redpanda/Kinesis stream producing from WAL sync.
- support Docker Compose for local multi-container development.

---

# Phase 9 — Day-to-Day Mission Control Dashboard

## Objective
Action cockpit for cost and anomalies.

## Technical Tasks
- Add mission-control API endpoints and frontend widgets.
- Surface budget ETA, runaway loops, unattributed spend, and policy violations.

---

# Phase 10 — Alerting + Click-to-Optimize Workflows

## Objective
Turn alerts into instant action.

## Technical Tasks
- Active Slack/Teams webhooks with signed action tokens.
- Add action APIs (e.g., pause API key, increase budget, downgrade model) with full audit log.

---

# Phase 11 — Optional Dynamic Model Routing

## Objective
Cost-aware fallback/degradation.

## Technical Tasks
- Complexity classification and cost-aware model registries.
- Observe-only vs active routing, integrating with LiteLLM.

---

# Phase 12 — Enterprise Hardening

## Objective
SSO, RBAC, tenant isolation, compliance audit log.

## Technical Tasks
- Workspace RBAC (Owner, Admin, Viewer, Auditor).
- Activity logs, retention/archiving policies, and deployment templates.
