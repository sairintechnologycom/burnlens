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
| Pricing provenance | PARTIAL | `pricing_version`, `pricing_class`, applied-rate fingerprint, cloud reconciliation, custom pricing, per-model source labels/links for GPT-5.6/Sonnet 5 | `burnlens/storage/database.py:46`; `burnlens/cost/calculator.py:95`; `burnlens/cost/pricing_data/openai.json`; `burnlens/cost/pricing_data/anthropic.json`; `frontend/src/app/llm-pricing/page.tsx`; `burnlens_cloud/settings_api.py:193` | No archived price snapshots; most catalog entries have no independently recorded provider source | Add sources incrementally; label absent provenance as unverified |
| Unknown-model handling | PARTIAL | `unpriced` class and zero sentinel; proxy rejection and scan warnings | `burnlens/cost/calculator.py:97`; `tests/test_unpriced_model_blocked.py` | Some documentation/UI still describes or renders sentinel zero as known zero | Preserve classification across all surfaces |
| Workspace / app / repo identity | PARTIAL | Request fields, workspace metadata, repo-derived workflow IDs | `burnlens/storage/database.py:15`; `burnlens/proxy/interceptor.py:1480`; `tests/test_economics_graph_phase_c.py` | No first-class application/project relationships | Add relationships only for proven queries |
| Agent/workflow/run identity | SHIPPED | First-class local agent/workflow/workflow-run/agent-run records, optional request links, and workspace-scoped recursive run economics | `burnlens/storage/database.py`; `burnlens/storage/agent_economics.py`; `burnlens/storage/models.py`; `burnlens/proxy/interceptor.py`; `tests/test_phase1_agent_economics.py`; PyPI `burnlens` v1.26.1 | Legacy agent/workflow/run keys remain globally unique and workspace relationship safety is application-validated rather than enforced with composite foreign keys | Keep legacy IDs compatible; strengthen constraints only if deployment evidence supports a safe additive migration |
| Trace/model/tool/retry graph | PARTIAL; Phase 3A implemented locally | W3C trace capture, session/trace view, tool-call count, optional explicit parent/retry/fallback request references and workflow-run graph projection | `burnlens/proxy/interceptor.py`; `burnlens/analysis/runs.py`; `burnlens/storage/database.py`; `burnlens/storage/agent_economics.py`; `tests/test_execution_relationships.py` | Tool identity, own span IDs, internal attempt evidence, and cloud graph persistence remain absent | Release 3A after CI; retain caller-reported provenance |
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
| 1 | Model/provider registry foundation | SHIPPED for bounded pricing evidence scope (1A–1C) | Phase 1A–1C implementation and production evidence below; this does not claim a complete model registry |
| 2 | Execution identity | SHIPPED | Phase 2A released as PyPI `burnlens` v1.26.1; CI, publish workflow, installed wheel migration, and workspace-isolation smoke passed. See evidence below. |
| 3 | Execution graph | PARTIAL; 3A implemented locally | Explicit ledger request links and mounted workflow-run graph; package build and installed-wheel smoke pass. CI/publication pending; tool/attempt slices remain separate. |
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

**Phase exit:** PASS for Phase 1A. Production Postgres ingest/readback and the active API contract are verified. ClickHouse remains inactive in production; before enabling streaming, run the ClickHouse projection migration/write/read check. Phase 1B is complete for the bounded provider pricing corrections documented below.

## Phase 1B — Verified pricing metadata and corrections

**Status: DONE.** Bounded to official-source verification of OpenAI GPT-5.6 Sol/Terra/Luna and Anthropic Claude Sonnet 5. This adds source/effective-date metadata to bundled pricing and the frontend pricing snapshot, corrects these rates, and removes Sonnet 5's superseded scheduled increase. No database, ledger, cost semantics, public API, or historical records change. Other model prices remain as they were and are not newly claimed as verified.

### Implementation tracker

| Work item | Status | Acceptance evidence |
|---|---|---|
| Verify supported rates and dates against provider sources | DONE | Official OpenAI model pages and change announcements; Anthropic Sonnet 5 announcement. Sources are embedded with the provider pricing entries. |
| Correct GPT-5.6 standard/cache-write and >272K token tier rates | DONE | `burnlens/cost/pricing_data/openai.json`; exclusive 272,000-token threshold follows existing `apply_tiered` semantics. |
| Correct Sonnet 5 price lifecycle | DONE | `burnlens/cost/pricing_data/anthropic.json`; permanent $2/$10 introductory rates, no obsolete Sep 1 scheduled increase. |
| Expose provider source/effective date metadata in pricing snapshot | DONE | `burnlens/cost/pricing.py`, `scripts/build_pricing_snapshot.py`, `frontend/src/data/llm-pricing.json`; exact and longest-prefix lookup. |
| Pricing, tier-boundary, snapshot, recommender, and compatibility tests | DONE | Focused suite: 128 passed; full backend: 2,292 passed, 21 skipped; frontend: 418 passed and production build passed. |
| Tracker and rollback notes | DONE | This section. Rollback: revert these pricing JSON/provenance and snapshot changes; already recorded ledger costs and fingerprints remain untouched. |
| CI, deployment, and production verification | DONE | Direct authenticated GitHub push advanced `main` through `2ae002531fa893a606848e1d2a1c13aefa9b7d85`. GitHub Actions run [36405296758](https://github.com/sairintechnologycom/burnlens/actions/runs/36405296758) passed all three jobs. Vercel production deployment `6706941714` succeeded; `https://burnlens.app/llm-pricing` served GPT-5.6 and Sonnet 5 rates. Azure mirror runs 309 and 311 still fail because its separate `GITHUB_PAT` secret is invalid; that mirror maintenance issue did not block this verified release. |

**Expected files:** `burnlens/cost/pricing_data/openai.json`, `burnlens/cost/pricing_data/anthropic.json`, `burnlens/cost/pricing.py`, `scripts/build_pricing_snapshot.py`, generated `frontend/src/data/llm-pricing.json`, `burnlens/analysis/recommender.py` (rate comment), `tests/test_cost.py`, `tests/test_pricing_snapshot.py`, `tests/test_recommender.py`, `frontend/tests/llm-pricing.test.ts`, this tracker.

**Exit criteria:** PASS. Local focused tests passed (128); full backend suite passed (2,292 passed, 21 skipped); frontend suite/build passed (418 tests); GitHub CI passed; the production pricing page returned GPT-5.6 standard/long-context rates and Sonnet 5 at $2/$10. Pricing provenance remains in the committed data snapshot and is covered by tests. No schema migration is needed. Feature-flag rollback is unnecessary because changes affect only listed prices and metadata; reverting bundled data restores the previous calculation behavior.

**Separate pipeline maintenance:** Azure mirror runs 309, 311, 312, and 313 failed because its `GITHUB_PAT` is invalid. Phase 1B and Phase 1C commits were pushed directly using the authenticated GitHub account with push permission, then CI and production deployments were verified. Repair the Azure secret before relying on future automatic mirroring.

## Session handoff — next work

**Verified repository state (updated 2026-09-29):** Phase 1A, 1B, 1C, and Phase 2 execution identity are complete. Phase 2A shipped as PyPI `burnlens` v1.26.1. Phase 3A is implemented locally: explicit request relationships, mounted workspace-scoped graph read, local backend tests, v1.27.0 build, and installed-wheel migration/tenant-isolation smoke pass. Next: review/commit, GitHub CI, then publish the proxy package and verify the published wheel. No commit, push, tag, or publication was performed in this increment. The Railway cloud deployment is not the target for this local SQLite capability.

The prior handoff incorrectly marked Phase 2 shipped based on entity/table presence alone. This source-checked status supersedes that conclusion. The tracker is the session handoff/memory source of truth; re-read it and current source before implementation in a new session.

## Phase 2A — Workflow-run identity and tenant-safe attribution

**Status: COMPLETE — RELEASED AS v1.26.1.** Bounded to the existing local SQLite Agent Economics store. Keep the current globally unique external IDs for compatibility, but reject attempts to move an existing ID between workspaces. Add a first-class workflow-run table keyed by `(workspace_id, workflow_run_id)`, optional links from requests and agent runs, and workspace-scoped recursive run economics. Do not rebuild the ledger or existing identity tables. Cloud Agent Economics persistence is not present in the inspected source and is outside this increment.

### Phase output / implementation plan

- **A. Current state:** `agents`, `agent_workflows`, and `agent_runs` exist; `requests` has nullable agent/workflow/run/task/action correlation. `agent_runs.parent_run_id` supports recursive CTE economics. These tables are local SQLite, with globally unique IDs and workspace columns but no composite foreign keys.
- **B. Gap:** Workflow execution instances have no entity of their own. `get_run_economics()` traverses and aggregates requests/actions without resolving/scoping to the root run's workspace. Existing `INSERT OR REPLACE` upserts can replace another workspace's entity when IDs collide.
- **C. Proposed change:** Add `WorkflowRun` and an additive `workflow_runs` table with composite workspace identity; optionally attach it to requests and agent runs; reject cross-workspace ID reuse/parent association; scope run-tree traversal and spend to the root workspace. Keep null/legacy identity valid.
- **D. Graph impact:** Add `Workflow → WorkflowRun → AgentRun` and optional `Request → WorkflowRun` links. No model-call/tool-call/retry nodes in this phase.
- **E. Database changes:** Idempotently create the new table and indexes; add nullable `workflow_run_id` to requests/agent_runs. No historical backfill and no rewrite of existing primary keys. Rollback is feature/data inert: code can stop reading/writing the additive fields; leave additive columns/table in place to avoid destructive rollback.
- **F. API changes:** No public HTTP API changes. Extend storage dataclasses/CRUD and proxy identity-tag extraction with optional `workflow_run_id`.
- **G. UI changes:** None.
- **H. Security impact:** Validate workspace consistency on known workflow/run/parent relationships; avoid cross-tenant run-tree traversal and request/action aggregation. IDs remain globally unique to preserve old schema constraints. Unknown/out-of-order telemetry remains nullable/unlinked rather than being assigned across workspaces.
- **I. Tests:** Legacy request insert without new IDs; workflow-run CRUD and workspace-scoped IDs; request/agent-run optional links; reject cross-workspace duplicate IDs and known cross-workspace parents; same run IDs in request tags do not cause cross-workspace rollup; existing parent/child rollup remains numerically identical within its workspace; idempotent schema initialization.
- **J. Deployment:** Existing additive SQLite startup migrations; no flag is needed because links are optional and legacy paths remain unchanged. Deploy internally first and monitor failed identity writes / orphan-link coverage before broad use.
- **K. Rollback:** Disable optional identity extraction/link writes in code if needed. Existing `cost_usd` and old records are untouched; additive schema can safely remain.
- **L. Expected outcome:** BurnLens can represent a workflow execution separately from its reusable workflow definition and safely calculate a run's economics within one workspace.
- **M. Exit criteria:** Migration works on a fresh and existing schema; workspace collisions are rejected; run traversal/spend stay within one workspace; legacy events and existing totals remain compatible; focused tests and the relevant regression suite pass.

**Expected files:** `burnlens/storage/models.py`, `burnlens/storage/database.py`, `burnlens/storage/agent_economics.py`, `burnlens/proxy/interceptor.py`, focused `tests/test_phase1_agent_economics.py` coverage, and this tracker. Any expansion beyond these files requires evidence from implementation.

### Phase 2A implementation evidence

| Work item | Status | Evidence |
|---|---|---|
| Add first-class workspace-scoped workflow-run identity and optional request/agent-run links | DONE locally | `burnlens/storage/models.py`; `burnlens/storage/database.py`; `burnlens/storage/agent_economics.py`; `burnlens/proxy/interceptor.py` |
| Prevent known cross-workspace identity reuse and parent/run association | DONE locally | Workspace checks on identity upserts and agent-run relationships in `burnlens/storage/agent_economics.py` |
| Scope recursive traversal, request spend, action spend, and retry spend to root workspace | DONE locally | `get_run_economics()` in `burnlens/storage/agent_economics.py`; historical cross-workspace parents are excluded by the scoped CTE |
| Existing-schema migration and backward compatibility | PASS locally | Migration test drops Phase 2A additions, reruns `init_db()` twice, then verifies fields/table are restored; legacy no-ID request test passes |
| Focused regression suite | PASS | 93 tests passed across Agent Economics, economics graph, analyst, agent API/MCP, and tag plumbing |
| Lint for changed Python files | PASS | `uv run ruff check` on the five changed Python files |
| Full repository suite | PASS in GitHub CI | [Run 36520107232](https://github.com/sairintechnologycom/burnlens/actions/runs/36520107232) passed backend pytest, contract/frontend, and public-route smoke on release-prep commit `804c8fc`. |
| Proxy package published | PASS | PyPI `burnlens` v1.26.1 contains wheel and source archive. Tag-triggered [publish run 36520885753](https://github.com/sairintechnologycom/burnlens/actions/runs/36520885753) passed build and publish. |
| Installed-runtime smoke | PASS | Installed PyPI v1.26.1 into an isolated target; startup migration succeeded and run economics returned `$1.25` while excluding a `$99` request belonging to another workspace. |

**Exit state: COMPLETE.** Implementation, migration/backward-compatibility tests, focused regressions, GitHub CI, PyPI publication, and installed-wheel migration/tenant-isolation smoke pass. No schema backfill or cost rewrite was performed. Phase 3 implementation remains separate; its plan follows.

## Phase 3 — Explicit execution graph relationships

**Status: PARTIAL (2026-09-29); Phase 3A implemented locally, CI/publication pending.** A request already represents a model call, an agent run already represents a child agent, and `task_id` / `action_id` already provide optional step/action correlation. Phase 3A adds causal references around these records rather than duplicate financial events or introduce generic graph tables. Tool relationships and internal attempt evidence remain separate slices.

### Source-checked baseline before Phase 3A

- `burnlens/storage/models.py`: `RequestRecord` has `event_id`, `trace_id`, caller `parent_span_id`, workflow/run/task/action IDs. It has no own span ID or request-to-request causal reference. `GenAICostEvent` conversions do not currently carry all run identity fields; do not assume a canonical-event round trip preserves them.
- `burnlens/storage/database.py`: `insert_request()` assigns a missing event ID and deduplicates with `INSERT OR IGNORE`; `event_id` is globally unique. Keep that contract. `get_retry_stats()` infers retries from trace/model/failure/time, without a workspace predicate. Its output is evidence of a heuristic, not an explicit relationship.
- `burnlens/storage/agent_economics.py`: Phase 2 scopes recursive agent-run traversal and request spend to the root workspace. Its retry-waste metric counts failed requests; it is not the same measure as causal retry spend. Action cost is still summed separately without a ledger source link.
- `burnlens/analysis/runs.py`: the existing read-only run view groups by session first, trace second and orders requests as steps. These keys are not interchangeable with `workflow_run_id` or `agent_runs.run_id`. Preserve its API/CLI grouping and historical-schema fallback.
- `burnlens/proxy/interceptor.py`: non-streaming, streaming, and cache paths construct records separately. Both forwarding retry loops discard intermediate responses and record the final result. Current streaming code counts tool calls through the provider hook; a count still does not prove tool identity, execution, success, or cost.
- `burnlens/storage/wal.py`: serialization enumerates record fields and recovery filters against the dataclass. New fields need round-trip/recovery evidence, but no new persistence queue is needed.
- `burnlens/proxy/server.py` mounts `burnlens.dashboard.routes` under `/api`; the Agent Economics router is not mounted. Reachability tests must use `get_app()`, not a test-only router mount.

### Delivery slices

| Slice | Deliverable | Gate / boundary |
|---|---|---|
| **3A — implemented locally** | Explicit request parent/retry/fallback references; workspace-scoped workflow-run graph read; distinct-ledger cost reconciliation | Caller supplies causality; CI/publication pending; proxy internal attempts are not reconstructed |
| 3B | Tool invocation/result identity and request/action source links, reusing `AgentAction` where suitable | Agree invocation vs execution semantics and eliminate action/model cost overlap before claiming complete tool economics; no arguments/results by default |
| 3C | Proxy-internal attempt evidence for streaming and non-streaming retries | Separate nonfinancial attempt telemetry from priced ledger events; absent usage/cost remains unknown, never invented as zero |
| Later integration | Cloud sync/ingest/read projection, OTEL/Beacon adapters, run-linked outcomes | Separate end-to-end contracts and rollout evidence; no cloud graph claim from a local release |

3A does not complete the full Phase 3 graph. Keep overall Phase 3 **PARTIAL** until tool relationships and attempt evidence have their own verified runtime paths. Outcome linkage remains a Phase 7 dependency; failure-adjusted metrics remain Phase 5 work.

### Phase 3A output / implementation plan

- **A. Current state:** First-class workflow executions and agent-run trees exist. Each request is a ledger-backed model-call node with optional identity, but requests cannot explicitly identify the call that spawned, retried, or preceded a fallback.
- **B. Gap:** Trace/session/time correlation cannot distinguish fan-out from retries or recovery. Generated proxy event IDs are not exposed as a stable client correlation contract. There is no mounted workflow-run graph read path.
- **C. Proposed change:** Add three nullable request fields, `parent_event_id`, `retry_of_event_id`, and `fallback_of_event_id`. Carry them through `RequestRecord`, canonical-event conversion, local persistence, and WAL recovery. Accept dedicated per-request headers and expose the generated ledger event ID in the response. Reuse existing run/agent/task/action IDs and provider/model attributes. Add one bounded read-only graph projection for an explicit workflow-run identity.
- **D. Graph impact:** `WorkflowRun → AgentRun → Request(model call)` membership comes from existing IDs; child-agent edges come from existing `parent_run_id`. New request references point from the current call to the referenced call. Reverse them for causal display. A retry/fallback may also have a structural parent; neither relationship creates another charge. Trace/span IDs remain correlation metadata, not resolved parent nodes.
- **E. Database changes:** Add the three nullable TEXT columns using existing idempotent migrations, plus `(workspace_id, <reference>)` indexes and a workspace/event lookup index if query plans require it. Keep the existing event-ID unique index and request cost intact. No generic node/edge tables, history backfill, guessed parentage, or destructive constraint rebuild. Validation and insertion use the same SQLite transaction where necessary to prevent concurrent cycle creation.
- **F. API changes:** Dedicated headers `X-BurnLens-Parent-Event-Id`, `X-BurnLens-Retry-Of-Event-Id`, and `X-BurnLens-Fallback-Of-Event-Id`; response header `X-BurnLens-Event-Id` for each recorded proxy call. Headers must be stripped before upstream forwarding. No environment fallback for causal IDs: a process-wide predecessor would falsely link unrelated calls. Add `GET /api/workflow-runs/{workflow_run_id}/graph` to the already mounted local dashboard router with required `workspace_id` and bounded request pagination. This is the existing local dashboard trust model, not a new tenant-authenticated cloud API. Do not change `/api/runs` or existing economics response semantics.
- **G. UI changes:** None. The JSON read path provides reviewable execution evidence; a graph canvas is not an implementation prerequisite.
- **H. Security impact:** Bound reference length (128 characters), reject control characters, self-reference, simultaneous retry/fallback for one call, and cycles. Resolve every destination only in the source workspace. Missing workspace or unresolved/out-of-order targets stay unlinked; no cross-workspace target metadata or existence signal is returned. Invalid optional relationships must not discard a valid ledger charge or fail provider traffic: omit the invalid links and log a reason without sensitive payloads. Caller assertions are explicitly labeled `caller_reported`, not verified behavior.
- **I. Tests:** One focused execution-relationship test module using existing pytest/SQLite helpers, plus existing regression tests. Cover migration twice on fresh/old schemas, optional legacy insertion, dedup replay, canonical/WAL round trips, parent plus retry/fallback, malformed/self/cycle cases, out-of-order insertion, workspace isolation, bounded graph reads, and distinct-cost reconciliation. Drive normal, drained streaming, and cache paths through `handle_request()`; drive the graph route through production `get_app()`.
- **J. Deployment:** Local proxy package release via the existing PyPI tag workflow after focused checks and repository CI. Installed-wheel smoke must exercise old-schema migration, request linkage, the mounted endpoint, and workspace isolation. Async persistence means an immediately returned event ID may not yet resolve; show unresolved state and test eventual visibility. No Railway/frontend release or new flag infrastructure for this increment.
- **K. Rollback:** Stop extracting/returning relationship metadata and remove the new route if needed. Leave additive columns in place. WAL readers already ignore unknown fields; verify downgrade recovery still preserves original charges. Never rewrite historical costs to remove relationships.
- **L. Expected outcome:** A client can connect a model call to its parent, retry, or fallback and inspect a workspace-scoped workflow execution with explainable ledger spend. Missing links remain visible; unknown tool/intermediate-attempt costs remain outside any completeness claim.
- **M. Exit criteria:** All relationship validation, migration, compatibility, dedup, workspace and path-wiring checks pass; graph sums equal distinct request ledger sums; old API/CLI and retry metrics remain unchanged; CI and installed-package verification pass. Mark **3A complete**, not full Phase 3 complete.

### Relationship and read contract

1. **Identity:** Event references use BurnLens `event_id`, never provider `request_id`, local integer row ID, trace ID, or caller span ID. Preserve current generated IDs and dedup semantics; do not accept caller overrides of a proxy-generated event ID in this increment. Permit bounded opaque IDs for existing imported ledger events; do not require all historic IDs to be UUIDs.
2. **Resolution:** Store well-formed unresolved references without a foreign key requiring arrival order. Read-time joins require matching non-NULL workspace IDs on both ends. Resolve after the destination arrives; suppress invalid/cyclic references discovered then. Unknown, outside-selection, and omitted-by-pagination links are identified separately without looking up another workspace. Do not enforce timestamp order because clock skew and late persistence are real.
3. **Membership:** Select the workflow-run by `(workspace_id, workflow_run_id)` and its agent-run descendants in that workspace. Include requests directly linked to the workflow-run or its selected agent runs, using a distinct request set. Never pull additional billable requests into a run simply by following a causal reference. Missing run entities remain missing; do not fabricate them from tags.
4. **Read result:** Return workflow/run identity, ledger-backed request nodes with provider/model/status/pricing classification, run/parent/retry/fallback edges, relationship provenance, unresolved/invalid counts, pagination/truncation state, and ledger reconciliation. Deterministic pagination uses timestamp plus event ID as a tie-breaker; aggregate totals describe the full selected request set, not only the page. Cap the page at 500 requests. Show references outside the returned page as references, not extra charged nodes.
5. **Financial truth:** `ledger_cost_usd = SUM(requests.cost_usd)` over distinct selected rows. Linked and unlinked request spend partition that same set. Unknown-price rows retain their classification even if the stored sentinel is zero; include unpriced count and a cost-completeness indicator. Edge count, graph paths, retry spend, and child rollups are not additional charges. Exclude `agent_actions.cost_usd` from this ledger reconciliation until a source-link contract prevents overlap.
6. **Compatibility:** Preserve heuristic `get_retry_stats()` and existing failed-request retry-waste fields unchanged. The new graph labels only supplied causal links as explicit. Do not silently improve confidence labels or substitute a new financial definition into existing metrics.

**Acceptance fixture:** In workspace A, a workflow-run contains a parent agent and child agent. Insert call `a` ($1), call `b` ($2, parent/retry of `a`), call `c` ($3, fallback of `b`), and an unlinked call `d` ($4) in that workflow-run. Assert four ledger nodes, total $10, linked $5 (calls carrying resolved causal references), unlinked $5, and unchanged total when an event is replayed. Insert a $99 call in workspace B carrying the same workflow-run tag and a reference to `a`; A stays $10 and B never resolves A's destination. Also test destination-after-source and a page containing fewer nodes than the full aggregate.

### Implementation order and verification

1. Add record fields, canonical conversions, additive migration and centralized relationship validation in the shared `insert_request()` path. Audit all callers before changing it; every ingest path must preserve charge insertion and existing duplicate behavior.
2. Wire dedicated request/response headers across normal, streaming, and cache paths, using the exact ID queued for persistence. Allocate a missing event ID once before WAL/enqueue where needed. Streaming headers must be available before the first chunk; an aborted response must not produce a claim of a persisted charge that was never recorded.
3. Implement the workspace-scoped projection beside current Agent Economics storage helpers and mount the one dashboard route. Reuse the existing recursive run selection; do not alter the session/trace grouping read model.
4. Run focused relationship tests with event-contract, Agent Economics, runs-view, provider-hook, proxy-retry, streaming, and WAL regressions. Run required CI; after implementation, record actual commands/counts and installed-wheel evidence here before changing status.

**Expected files:** `burnlens/storage/models.py`, `burnlens/storage/database.py`, `burnlens/storage/agent_economics.py`, `burnlens/proxy/interceptor.py`, `burnlens/dashboard/routes.py`, focused `tests/test_execution_relationships.py`, and existing regression tests only where a wiring guard needs extension. `burnlens/storage/wal.py` and `burnlens/proxy/server.py` need changes only if round-trip/mounting evidence shows existing behavior is insufficient. Cloud sync/ingest and the frontend are outside 3A; do not advertise these local fields as cloud-persisted.

**Planning verification:** Traced record construction, retry loops, canonical conversion, insert/dedup, WAL recovery, run grouping/rollups, and production router mounting before implementation.

### Phase 3A implementation evidence

| Work item | Status | Evidence |
|---|---|---|
| Optional causal fields and additive indexed migration | DONE locally | `RequestRecord`, `GenAICostEvent`, shared `insert_request()` validation; legacy costs and dedup unchanged |
| Validation and tenant isolation | PASS locally | Malformed/self/conflicting references omitted without losing charges; concurrent cycle ends serialized; unknown/missing-workspace/cross-workspace references remain unresolved; historical cycles suppressed on reads |
| Proxy path wiring | PASS locally | `handle_request()` coverage for normal, drained streaming, and normal/streaming cache hits; upstream headers stripped; generated response event ID matches eventual ledger row |
| Canonical event and WAL identity | PASS locally | Run identity and references survive canonical conversion; WAL assigns missing IDs before serialization, replay deduplicates; simulated older field filter retains original charge |
| Mounted workflow-run graph | PASS locally | Production `get_app()` route requires workspace scope; bounded request pages and up to 500 agent-run nodes; explicit outside-page/outside-selection references; totals cover the full distinct ledger set |
| Ledger reconciliation and confidence | PASS locally | $10 acceptance fixture retains $5 linked/$5 unlinked causal spend and excludes another workspace's $99; old missing event/pricing identity remains unknown; action cost excluded |
| Focused regressions | PASS locally | Pinned environment: 136 passed across relationships, event contract, Agent Economics, runs view, provider hooks, retries, streaming, WAL, cache and tag plumbing. Final route/CORS and lifecycle checks: 25 passed after the header-exposure change. |
| Full backend suite | PASS locally | `/tmp/bl-phase1a-venv/bin/python -m pytest tests/ -p no:cacheprovider -q`: 2,314 passed, 21 skipped. Required permission for local mock-server binds/DNS. Existing dashboard regression now uses temporary WAL paths instead of the real home WAL. |
| Cloud contract and lint | PASS locally | Pinned cloud OpenAPI component snapshot unchanged (89 schemas); Ruff passes changed Python files; `git diff --check` passes |
| Proxy package | BUILT locally | `packaging/burnlens-proxy/pyproject.toml` prepared for v1.27.0; existing build script produces wheel and source archive |
| Installed-wheel smoke | PASS locally | Isolated v1.27.0 wheel matches source; migrates an actual installed-v1.26.1 database twice; mounted endpoint returns $2, excludes workspace B's $99, and preserves full totals on a one-request page |
| GitHub CI / PyPI release | PENDING | No remote mutation or publication performed; published-package verification remains required before marking 3A complete |

**Read contract details:** `X-BurnLens-Event-Id` is a correlation ID, not a durability receipt: recording remains asynchronous, and a stream that never starts may never create a ledger row. The local server exposes the header through its existing CORS policy. `totals.cost_complete` describes pricing availability of selected ledger requests only; it does not claim complete tool/attempt/intervention economics. Unknown or absent pricing classification makes it false. Legacy nodes with no event ID retain a local `ledger_row_id` for display, never a fabricated causal identity. Causal references remain `caller_reported`.

**Known ceiling:** Recursive cycle checks can be quadratic for a large connected request graph; the code names a materialized validated-link projection as the upgrade if measured latency warrants it. No new dependency or generic graph store was added.

**Exit state: IMPLEMENTED LOCALLY, RELEASE PENDING.** Full Phase 3 remains partial. Next is repository CI and the proxy release, followed by published-wheel verification; then scope 3B tool/source links without combining independent action costs into the ledger total.

## Phase 1C — Surface pricing evidence accurately

**Status: DONE.** The catalog had labeled each provider's rates as "verified" based only on its JSON refresh date, despite source metadata existing for only a small subset. This increment makes confidence explicit per model. It does not edit prices or attempt to infer evidence for models without a source. No tenant telemetry was queried; per-tenant usage-based prioritization remains future work when an approved aggregate source is available.

### Phase output

- **A. Current state:** The pricing page imports the generated snapshot directly. Only GPT-5.6 entries and Claude Sonnet 5 carry provenance. Provider `updated` dates are bundle refresh dates.
- **B. Gap:** The page represented refresh dates as universal verification and did not show per-model evidence.
- **C. Proposed change:** Label provider dates as catalog updates; show a provider-source link and effective date only for `VERIFIED_PROVIDER`; clearly label other catalog rows `Not source-verified`.
- **D. Graph impact:** None.
- **E. Database changes:** None.
- **F. API changes:** None.
- **G. UI changes:** Pricing catalog only.
- **H. Security impact:** Source URLs are committed static data; links open with `rel="noreferrer"`. No prompts, telemetry, credentials, or tenant data are introduced.
- **I. Tests:** Rendered-page evidence test, existing snapshot parity tests, frontend suite/build, GitHub CI and public route smoke.
- **J. Deployment:** GitHub push triggers the existing Vercel production deployment; no feature flag is needed.
- **K. Rollback:** Revert the page rendering/test and tracker changes; prices and ledger records are unaffected.
- **L. Expected outcome:** Users can tell which catalog prices have explicit provider evidence.
- **M. Exit criteria:** Verified rows link to a source and show effective date; rows with no verified evidence are labeled; no price calculation changes; tests/CI pass; production page is confirmed.

### Implementation tracker

| Work item | Status | Acceptance evidence |
|---|---|---|
| Distinguish catalog refresh date from price verification | DONE | `frontend/src/app/llm-pricing/page.tsx` says `catalog updated`, not `rates verified`. |
| Show per-model verified source/effective date or unverified label | DONE | Source links for records marked `VERIFIED_PROVIDER`; all other rows show `Not source-verified`. |
| Keep pricing and data contracts unchanged | DONE | UI reads existing snapshot provenance; no rate, DB, API, or schema edits. |
| Rendered-page regression coverage | DONE | `frontend/tests/llm-pricing-evidence.test.tsx`. |
| Production verification | DONE | GitHub Actions run [36411713410](https://github.com/sairintechnologycom/burnlens/actions/runs/36411713410) passed all three jobs on retry after a transient PyPI timeout. Vercel Production deployment `6708032531` succeeded. Live `https://burnlens.app/llm-pricing` shows linked source/effective dates for GPT-5.6 and Sonnet 5, and `Not source-verified` for entries without provenance. |

**Exit criteria:** PASS. The catalog no longer implies every model has provider-verified rates; verified rows link to evidence and show effective dates, while unverified rows are explicit. Pricing, APIs, and ledger behavior are unchanged. Focused UI/snapshot tests passed (5); full frontend suite passed (419); build passed; GitHub CI and production page verification passed. Lint completed with six existing warnings in unrelated files. Azure mirror run 313 still fails on the unrelated invalid `GITHUB_PAT`; this commit was pushed directly to GitHub and both remotes are synced.
