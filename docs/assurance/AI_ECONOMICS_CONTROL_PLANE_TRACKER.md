# AI Economics Control Plane Engineering Tracker

Repository source of truth for the incremental BurnLens roadmap. This tracker records implementation evidence and phase gates; a module name or certification report alone does not prove a capability is reachable from a deployed entry point.

**Discovery baseline:** `main` at `feat: deliver BurnLens Agentic Control Plane (Phases 0-10 complete)`; working tree was clean before Phase 1A work. The prior [capability matrix](BURNLENS_CURRENT_CAPABILITY_MATRIX.md) is dated 2026-09-04 and predates later source changes.

## Architecture and invariants

```text
Provider adapters → pricing data → normalized usage → requests ledger
                                                 ├─ agent/workflow IDs
                                                 ├─ trace/session read model
                                                 └─ outcomes
                                                       ↓
                                          economics / waste / budgets
                                                       ↓
                                      recommendations / simulation
                                                       ↓
                                 decisions / policy / execution
                                                       ↓
                                      verification / learning
```

The relational store is sufficient for the current relationships; no graph database is justified. Keep `requests.cost_usd` as financial truth. Add links and provenance around it. Preserve existing APIs and cost semantics, represent unknown price as unknown even where a zero sentinel is stored, keep deterministic financial calculations, and require shadow evidence before economic routing control.

## Current-state capability matrix

| Capability | Status | Existing implementation | Evidence | Gap | Recommendation |
|---|---|---|---|---|---|
| Economic ledger | SHIPPED | SQLite `requests`; cloud Postgres `request_records` | `burnlens/storage/database.py:15`; `burnlens_cloud/database.py` | No archived rate snapshots sufficient to recompute historical costs | Keep ledger; retain optional rate fingerprint as evidence only |
| Usage ingestion / normalization | SHIPPED | Proxy, scanners, provider adapters, cloud ingest/sync | `burnlens/proxy/interceptor.py`; `burnlens/providers/`; `burnlens_cloud/ingest.py` | Execution events are not all first-class normalized nodes | Extend current records |
| Provider registry | SHIPPED | Provider protocol and ten proxy registrations | `burnlens/providers/base.py`; `burnlens/providers/__init__.py:9` | OpenRouter and local/private have no first-party registration | Add only on demand |
| Model registry / identity | PARTIAL | Bundled per-provider pricing JSON, exact/prefix resolution | `burnlens/cost/pricing.py:16,110`; `burnlens/cost/pricing_data/openai.json` | No explicit deployment identity, lifecycle/capability catalog, or aliases table | Extend pricing contract compatibly; keep provider data scoped |
| Pricing provenance | PARTIAL | `pricing_version`, `pricing_class`, applied-rate fingerprint, cloud reconciliation, custom pricing, verified per-model sources for GPT-5.6/Sonnet 5 | `burnlens/storage/database.py:46`; `burnlens/cost/calculator.py:95`; `burnlens/cost/pricing_data/openai.json`; `burnlens/cost/pricing_data/anthropic.json`; `burnlens_cloud/settings_api.py:193` | No archived price snapshots; metadata describes current verified rates but does not reconstruct old costs | Continue provider-by-provider verification; preserve stored historical cost |
| Unknown-model handling | PARTIAL | `unpriced` class and zero sentinel; proxy rejection and scan warnings | `burnlens/cost/calculator.py:97`; `tests/test_unpriced_model_blocked.py` | Some documentation/UI still describes or renders sentinel zero as known zero | Preserve classification across all surfaces |
| Workspace / app / repo identity | PARTIAL | Request fields, workspace metadata, repo-derived workflow IDs | `burnlens/storage/database.py:15`; `burnlens/proxy/interceptor.py:1480`; `tests/test_economics_graph_phase_c.py` | No first-class application/project relationships | Add relationships only for proven queries |
| Agent/workflow/run identity | SHIPPED | Agent/workflow/run/task/action tables and nullable request IDs | `burnlens/storage/database.py:67`; `burnlens/storage/agent_economics.py`; `tests/test_phase1_agent_economics.py` | IDs are not consistently protected by composite workspace constraints | Preserve additive model; strengthen constraints with migration evidence |
| Trace/model/tool/retry graph | PARTIAL | W3C trace capture, session/trace run view, tool-call count, retry heuristic | `burnlens/proxy/interceptor.py:1447`; `burnlens/analysis/runs.py:97`; `burnlens/storage/database.py:1496` | No model/tool nodes, own span IDs, or causal retry edges | Link events to ledger before adding event storage |
| Outcomes / cost per outcome | SHIPPED | Accepted/rejected/failed, derived PR outcomes, workflow economics | `burnlens/storage/database.py:185`; `burnlens/storage/database.py:1448`; `tests/test_economics_graph_phase_b.py` | Outcome links to workflow/time window, not workflow-run ID | Reuse, then add run linkage |
| Budgets / proxy routing | SHIPPED | Hard caps, budget counters, optional budget downgrade, semantic cache | `burnlens/proxy/router.py`; `burnlens/config.py`; `docs/BUDGET_ENFORCEMENT.md` | No quality-aware shadow route comparison | Keep distinct from Decision Fabric |
| Waste detection | SHIPPED | Deterministic prompt/context, duplicate, overkill, cache, tool-schema and RAG detectors | `burnlens/analysis/waste.py:161` | Not execution-graph-aware | Extend after graph links exist |
| Recommendations / simulation | SHIPPED | Evidence-backed recs and model-switch/retry/cache projections | `burnlens/analysis/recommender.py`; `burnlens/recommendations/simulator.py` | No historical route-policy replay | Extend current simulator |
| Verified savings | SHIPPED | Baseline, normalized cost, outcome-rate checks and verdicts | `burnlens/verification/engine.py`; `tests/test_savings_verification.py` | Not directly linked to actual route intervention | Link future decisions to current verifier |
| Economics Analyst | PARTIAL | Analyst tools/engine and agent economics service | `burnlens/analyst/`; `burnlens/api/agent_service.py` | Reachable conversational path is not established on default server | Verify route wiring before public claim |
| Economic decision engine | MISSING | Existing budget downgrade and policy decisions cover narrower tasks | `burnlens/proxy/router.py`; `burnlens/governance/engine.py` | No normalized `model_route`, `retry_or_stop`, `tool_route` contract | Wait for trustworthy registry and attribution |
| Policy/control modules | INTERNAL / PARTIAL | Governance, guardrails, assisted execution, trust, autonomy modules | `burnlens/governance/`; `burnlens/guardrails/`; `burnlens/autonomy/` | Some are not mounted in normal proxy runtime; action policy is not route economics policy | Certify runtime reachability separately |

## Dependency edges and phase status

| Phase | Capability | Status | Gate / evidence |
|---|---|---|---|
| 0 | Baseline and contract protection | SHIPPED; revalidation needed | `tests/test_phase0_regressions.py`, `docs/assurance/PHASE_0_BASELINE_CERTIFICATION_REPORT.md`; validate actual server reachability and public truth |
| 1 | Model/provider registry foundation | IN PROGRESS | Existing provider registry/pricing JSON; Phase 1A compatibility and Phase 1B verified-pricing increments are tracked below |
| 2 | Execution identity | SHIPPED | Agent/workflow/run/task entities and correlation IDs |
| 3 | Execution graph | PARTIAL | Parent/child run CTE and trace/session run view; explicit model/tool/retry edges absent |
| 4 | Agent economics | PARTIAL | Agent/workflow/task/run rollups; separate action cost lacks source ledger link |
| 5 | Cost of failure | PARTIAL | HTTP failures and heuristic retry spend; recovery/fallback/intervention economics incomplete |
| 6 | Graph-aware waste | PARTIAL | Request-level detectors shipped; execution graph detectors absent |
| 7 | Outcome economics | SHIPPED; run linkage partial | Outcome and workflow economics are live |
| 8 | Verified savings | SHIPPED | Existing finding and baseline verification paths |
| 9 | Economics Analyst | PARTIAL | Components exist; default runtime path needs verification |
| 10 | Decision contract | MISSING for routing | Governance policy records are not economic route decisions |
| 11 | Shadow decisions | MISSING for routing | Governance shadow mode concerns action policy, not route quality |
| 12 | Simulation | PARTIAL | Existing deterministic simulations; no historical route-policy replay |
| 13 | Policy engine | PARTIAL / INTERNAL | Action policy and budget controls exist separately |
| 14 | Controlled routing | PARTIAL | Opt-in budget downgrade exists, without workload-specific route shadow evidence |

## Risks to resolve as gates

1. **Reachability:** `burnlens.api.agent_router` is exported but not mounted in `burnlens/proxy/server.py`; Phase 4 tests include it directly. MCP adapter is not mounted there either.
2. **Tool cost attribution:** `agent_actions.cost_usd` is summed with request cost, without a ledger event link. Reconcile before claiming complete execution economics.
3. **Retry causality:** retry stats infer relation by trace/model/status/time window rather than explicit event relationship.
4. **Pricing reproducibility:** historical scan pricing uses the current bundled rate; request cost is stored but applied rates are not archived.
5. **Tenant constraints:** workspace-scoped queries/tests exist, while some local relationships lack composite workspace-scoped foreign keys.
6. **Documentation truth:** unknown-price sentinel language remains inconsistent across docs/UI; prior capability matrix needs refresh against this source baseline.
7. **Migrations/flags:** local migrations are additive/idempotent; cloud Postgres uses startup DDL. No single migration ledger or common workspace rollout flag system was found.

## Phase 1A — Pricing provenance compatibility

**Status: DONE for the active production path.** Scope is intentionally limited to evidence BurnLens already has: provider pricing snapshot version and a fingerprint of the resolved bundled rate. Do not invent effective dates, verified sources, contract prices, or historical rates. Keep lookup behavior, `cost_usd`, APIs and recorded history backward compatible. The fingerprint identifies rate inputs; it does not reconstruct old prices or prove provider-source verification.

### Implementation tracker

| Work item | Status | Acceptance evidence |
|---|---|---|
| Add deterministic fingerprint for selected known price record | DONE | `burnlens/cost/calculator.py`; deterministic and rate/version sensitivity; unknown stays NULL |
| Persist optional pricing version and fingerprint with new local request | DONE | `burnlens/storage/database.py`; additive nullable SQLite migration; old rows remain NULL; stored `cost_usd` is unchanged |
| Carry existing `pricing_version` and optional fingerprint through cloud sync and ingestion | DONE | `burnlens/cloud/sync.py`, `burnlens_cloud/models.py`, `burnlens_cloud/ingest.py`; omitted fields remain accepted |
| Preserve fields in cloud request read model where applicable | DONE | `burnlens_cloud/dashboard_api.py`; optional response fields preserve compatibility with older mocked/read rows |
| Preserve provenance in ClickHouse stream schema | DONE | `burnlens_cloud/clickhouse.py`; additive columns and materialized-view refresh only for stale projection |
| Add unit/integration/regression coverage | DONE | Pinned CI dependencies: backend 2,289 passed, 21 skipped; frontend 418 passed and production build passed. Live ClickHouse checks skipped without service. |
| Documentation and rollback notes | DONE | Roadmap links this tracker. Rollback is feature/data inert: nullable additive columns can remain unused; no backfill or destructive down migration. |

### Files expected

`burnlens/cost/calculator.py`, `burnlens/storage/models.py`, `burnlens/storage/database.py`, `burnlens/cloud/sync.py`, `burnlens_cloud/models.py`, `burnlens_cloud/database.py`, `burnlens_cloud/ingest.py`, `burnlens_cloud/dashboard_api.py`, `burnlens_cloud/clickhouse.py`, `frontend/tests/contract/openapi-schemas.snapshot.json`, focused tests under `tests/`, and `docs/ROADMAP.md`.

### Exit criteria

- **PASS (automated):** Recorded costs and pricing resolution are unchanged for the existing fixture set; full repository suite passes.
- **PASS (automated):** New priced requests retain provider snapshot version and deterministic applied-price fingerprint when available.
- **PASS:** Unknown/history-missing provenance stays NULL/unknown; no fabricated backfill.
- **PASS (automated):** Existing cloud clients with omitted fields still ingest; tenant custom-price reconciliation remains workspace-scoped.
- **PASS (production):** GitHub CI and Railway health verification passed for `09cb9c4`; live OpenAPI exposes `pricing_class`, `pricing_version`, and `pricing_fingerprint`. Production ingest accepted the uniquely tagged zero-token fixture, and a read-only query inside the backend confirmed persisted `pricing_class=calculated`, `pricing_version=phase1a-live-check`, matching fingerprint, source, and tag. Zero-cost verification rows may remain in the workspace.
- **N/A (production ClickHouse path):** `streaming_enabled=false` in production; writes use PostgreSQL, so there is no active ClickHouse projection to validate. ClickHouse schema/projection unit coverage passed, but live ClickHouse verification remains a prerequisite before enabling streaming.
- **PASS (automated):** Existing API, CLI, dashboard and unknown-price behavior remain compatible.

**Phase exit:** PASS for Phase 1A. Production Postgres ingest/readback and the active API contract are verified. ClickHouse remains inactive in production; before enabling streaming, run the ClickHouse projection migration/write/read check. Phase 1B (explicit source/effective-date history or catalog) is separate work and requires candidate source dates to be validated before implementation.

## Phase 1B — Verified pricing metadata and corrections

**Status: IMPLEMENTED; automated validation and production rollout pending.** Bounded to official-source verification of OpenAI GPT-5.6 Sol/Terra/Luna and Anthropic Claude Sonnet 5. This adds source/effective-date metadata to bundled pricing and the frontend pricing snapshot, corrects these rates, and removes Sonnet 5's superseded scheduled increase. No database, ledger, cost semantics, public API, or historical records change. Other model prices remain as they were and are not newly claimed as verified.

### Implementation tracker

| Work item | Status | Acceptance evidence |
|---|---|---|
| Verify supported rates and dates against provider sources | DONE | Official OpenAI model pages and change announcements; Anthropic Sonnet 5 announcement. Sources are embedded with the provider pricing entries. |
| Correct GPT-5.6 standard/cache-write and >272K token tier rates | DONE | `burnlens/cost/pricing_data/openai.json`; exclusive 272,000-token threshold follows existing `apply_tiered` semantics. |
| Correct Sonnet 5 price lifecycle | DONE | `burnlens/cost/pricing_data/anthropic.json`; permanent $2/$10 introductory rates, no obsolete Sep 1 scheduled increase. |
| Expose provider source/effective date metadata in pricing snapshot | DONE | `burnlens/cost/pricing.py`, `scripts/build_pricing_snapshot.py`, `frontend/src/data/llm-pricing.json`; exact and longest-prefix lookup. |
| Pricing, tier-boundary, snapshot, recommender, and compatibility tests | DONE | Focused suite: 128 passed; full backend/frontend suites pending. |
| Tracker and rollback notes | DONE | This section. Rollback: revert these pricing JSON/provenance and snapshot changes; already recorded ledger costs and fingerprints remain untouched. |
| CI, deployment, and production verification | PENDING | Must pass repository CI and pricing snapshot readback before marking phase complete. |

**Expected files:** `burnlens/cost/pricing_data/openai.json`, `burnlens/cost/pricing_data/anthropic.json`, `burnlens/cost/pricing.py`, `scripts/build_pricing_snapshot.py`, generated `frontend/src/data/llm-pricing.json`, `burnlens/analysis/recommender.py` (rate comment), `tests/test_cost.py`, `tests/test_pricing_snapshot.py`, `tests/test_recommender.py`, `frontend/tests/llm-pricing.test.ts`, this tracker.

**Exit criteria:** same existing pricing behavior outside the explicitly corrected models; exact standard and long-context rates; 272,000 stays at base and 272,001 selects tier; Sonnet 5 remains at $2/$10 after Sep 1; provenance is queryable and present in the frontend snapshot; unknown models remain unknown; CI green; production deployment verified. No schema migration is needed. Feature-flag rollback is unnecessary because changes affect only listed prices and metadata; reverting bundled data restores the previous calculation behavior.
