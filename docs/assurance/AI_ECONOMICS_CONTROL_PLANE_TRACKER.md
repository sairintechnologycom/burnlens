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
| Agent/workflow/run identity | PARTIAL | First-class local agent/workflow/workflow-run/agent-run records, optional request links, and workspace-scoped recursive run economics | `burnlens/storage/database.py`; `burnlens/storage/agent_economics.py`; `burnlens/storage/models.py`; `burnlens/proxy/interceptor.py`; `tests/test_phase1_agent_economics.py` | Phase 2A is local and unreleased; legacy agent/workflow/run keys remain globally unique and their workspace relationship safety is application-validated rather than enforced with composite foreign keys | Validate migration and tenant isolation in CI/deployment; only add stronger constraints if deployment evidence supports a safe additive migration |
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
| 1 | Model/provider registry foundation | SHIPPED for bounded pricing evidence scope (1A–1C) | Phase 1A–1C implementation and production evidence below; this does not claim a complete model registry |
| 2 | Execution identity | PARTIAL | Phase 2A adds local workflow-run identity and scoped run economics; deployment/full-suite validation remains pending, and legacy entity relations lack composite foreign keys |
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

**Verified repository state:** Phase 1A, 1B, and 1C are complete and production-verified. Phase 2 execution identity is **partial**, not shipped. Phase 2A implementation is now present locally, but has not been released or production-validated. Preserve legacy events and ledger costs. Do not start Phase 3 graph relationships until Phase 2 identity and tenant-isolation gates pass. Keep the ledger authoritative and use relational storage.

The prior handoff incorrectly marked Phase 2 shipped based on entity/table presence alone. This source-checked status supersedes that conclusion. The tracker is the session handoff/memory source of truth; re-read it and current source before implementation in a new session.

## Phase 2A — Workflow-run identity and tenant-safe attribution

**Status: IMPLEMENTED LOCALLY — RELEASE VALIDATION PENDING.** Bounded to the existing local SQLite Agent Economics store. Keep the current globally unique external IDs for compatibility, but reject attempts to move an existing ID between workspaces. Add a first-class workflow-run table keyed by `(workspace_id, workflow_run_id)`, optional links from requests and agent runs, and workspace-scoped recursive run economics. Do not rebuild the ledger or existing identity tables. Cloud Agent Economics persistence is not present in the inspected source and is outside this increment.

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
| Full repository suite | BLOCKED in environment | Collection fails for four existing cloud/TOTP test modules because `pyotp` is not installed; not a failure in Phase 2A code |
| Production deployment and post-deploy validation | PENDING | Not performed in this increment |

**Exit state:** Implementation and local acceptance checks pass. Phase 2A and Phase 2 remain PARTIAL until full CI collection passes with declared dependencies and the additive migration/tenant-isolation behavior is validated in the deployment environment. No schema backfill or cost rewrite was performed.

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
