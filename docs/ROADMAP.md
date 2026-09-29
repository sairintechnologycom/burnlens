# BurnLens Product Roadmap

BurnLens is evolving from AI cost observability into an **AI Economics Control Plane**: it explains what AI work costs, what outcomes it produces, where economics break down, and how that work should run within cost, quality, and policy constraints.

> **Measure what AI costs. Prove what it creates. Control how it spends.**

BurnLens owns the economic decision loop. It is not a general-purpose LLM gateway, observability platform, agent framework, or autonomous agent. The canonical ledger remains the source of financial truth; execution context and decisions build on it.

## Product loop

```text
Observe → Attribute → Understand execution → Measure outcomes
        → Detect waste/failure → Recommend → Simulate → Decide
        → Control → Verify → Learn
```

| Layer | BurnLens responsibility |
|---|---|
| Economic ledger | Reconciled and provenance-aware cost; authoritative source for totals and historical economics |
| Execution graph | Connect workspaces, applications, workflows, runs, agents, steps, model/tool calls, retries, and outcomes |
| Economics | Cost of success and failure, waste, value per dollar, and contribution margin |
| Decision fabric | Evaluate task complexity, risk, confidence, history, budget, expected cost, and expected value |
| Policy and control | Allow, deny, route, cap, fallback, require approval, or stop; policy remains authoritative |
| Evidence loop | Compare recommendations with deployed changes, actual savings, quality, and outcomes |

Do not rewrite the ledger to add graph relationships. New event sources (SDK, proxy, OpenTelemetry, Agent Beacon, batch import) normalize into existing economic records and optional execution context. Collect identifiers, usage, timestamps, status, and relationships by default; prompts, responses, file contents, command output, and tool arguments remain opt-in data.

## Current baseline

The repository contains an earlier ten-phase Agent Economics and Governance program and its certification reports. Those documents provide history; current source reachability and gaps are recorded in the [engineering tracker](assurance/AI_ECONOMICS_CONTROL_PLANE_TRACKER.md).

The current source-traced engineering status and phase gates live in the [AI Economics Control Plane Engineering Tracker](assurance/AI_ECONOMICS_CONTROL_PLANE_TRACKER.md). The tracker supersedes older capability summaries when they conflict with current code.

**Current handoff (2026-09-29):** Pricing evidence work Phase 1A–1C is complete. Phase 2A adds workflow-run identity and workspace-scoped run economics locally. Focused tests/lint and GitHub CI pass; latest validation is [run 36520107232](https://github.com/sairintechnologycom/burnlens/actions/runs/36520107232). The v1.26.1 proxy wheel build includes this local storage code; release validation remains open. Phase 2A is not production-verified, and Phase 3 execution graph remains deferred. See the tracker’s “Session handoff — next work” section before making changes.

The codebase includes provider/proxy and scan ingestion, cost and pricing, outcomes and cost per accepted outcome, waste and recommendations, projected and verified savings, budgets and hard caps, opt-in budget-aware model downgrade, semantic cache, agent economics and analyst modules, governance, runtime guardrails, and autonomy components. The tracker records where those capabilities are reachable and where certification remains incomplete. Existing behavior and cost totals remain compatibility constraints for every phase.

The next roadmap fills in the evidence needed to make economic decisions dependable: model/pricing intelligence, a richer execution graph, failure-adjusted economics, and shadow decisions before broader control. Certification of existing governance or autonomy does not mean the future decision fabric is already complete.

## Prioritized roadmap

### 1. Model and pricing registry

**Current implementation: Phase 1A — pricing provenance compatibility.** Carry the existing provider pricing snapshot version through local storage and cloud sync, and fingerprint the applied rate when known. This does not change pricing lookup, recorded costs, or unknown-price semantics. Do not backfill prices or dates that the repository cannot prove. See the [Phase 1A tracker](assurance/AI_ECONOMICS_CONTROL_PLANE_TRACKER.md#phase-1a--pricing-provenance-compatibility).

Turn the existing provider registry and pricing data into a versioned model intelligence capability. Begin with OpenAI and Anthropic, then add providers according to customer demand and data quality.

Track provider, logical model, provider model/deployment, aliases, capabilities, context/output limits, lifecycle, region, and pricing versions. Preserve source, currency, effective dates, retrieval time, and confidence class (official, customer contract, inferred, estimated, unknown). Discovering a model does not make its price verified. Unknown models or prices must stay unknown, never become zero; changing current pricing must not rewrite historical costs.

**Exit:** aliases resolve; unknown models do not fail ingestion; pricing changes preserve historical reproducibility; lifecycle status and pricing provenance are visible. Registry updates must not alter existing ledger totals.

### 2. Execution / Agent Economics Graph

Extend correlation around the ledger to represent:

```text
Workspace → Application → Workflow → Run
                                  ├─ Agent run → Step → Model call
                                  │             ├─ Tool call
                                  │             ├─ Retry
                                  │             └─ Child agent
                                  └─ Outcome → acceptance / value / intervention
```

Support proxy/SDK context first, then OpenTelemetry and Beacon adapters. Preserve parent/trace IDs and avoid capturing sensitive payloads by default. The graph explains execution; the ledger continues to calculate cost.

**Exit:** reconstruct a workflow through agent, model/tool calls, retries, and outcome; reconcile graph-attributed amounts to current ledger totals.

### 3. Failure-adjusted and outcome economics

Make cost of a run include relevant retries, failed tools, recovery, and human intervention where evidence is available. Add cost per successful/accepted outcome, first-pass success, failure-adjusted cost, rework cost, and value per dollar. Separate unknown intervention/value from zero. Routing comparisons use expected failure and recovery cost, not token price alone.

**Exit:** successful and failed runs have explainable cost; totals reconcile to the ledger; outcome coverage and missing attribution remain visible.

### 4. Execution-aware waste and model lifecycle

Extend current waste findings with graph-evidence detectors: retry storms, loops, duplicate tool calls, repeated failed calls, unproductive handoffs, excessive depth, context amplification, expensive fallback, failure cascades, unnecessary model calls, and human escalation cost. Add affected workflow/model reports for deprecated or retiring models, with migration options only when supported by evidence.

**Exit:** each finding links to evidence, affected runs, confidence, and estimated impact; overlapping waste is not double-counted; lifecycle alerts include affected spend and workflows.

### 5. Outcome-linked recommendations and verified savings

Connect recommendation → acceptance → deployed change → measurement window → actual economics and outcome quality. Keep projected, measured, and verified savings distinct. Report quality, failure-rate, and volume changes alongside cost so a cost reduction alone is not called a win.

**Exit:** every verified saving has a baseline, measurement period, traffic normalization, outcome/quality evidence where available, and an auditable verdict.

### 6. Decision Fabric in shadow mode

Define a normalized decision contract and keep decision providers replaceable. Initial decisions:

* `model_route()` — include a **no-LLM** route (rule, API, retrieval, human) before choosing a model.
* `retry_or_stop()` — retry, fallback, escalate, or stop.
* `tool_route()` — choose an appropriate tool or execution path.

Inputs can include task class, complexity, risk, history, quality, expected value, expected economic cost, budget, and model capability. Expected economic cost includes inference, failure probability times recovery cost, latency, tools, and human intervention. Decisions return eligible routes, expected economics, confidence, and reason codes. Deterministic APIs calculate the values; optional models may classify or explain them. Policy can restrict any recommendation.

First run decisions in shadow mode beside actual execution. Record provider, signals, policy version/result, recommendation, actual route, override, result, outcome, and actual cost. Do not let shadow decisions change production traffic.

**Exit:** replayable, audited decisions; unknown signals remain explicit; policy can constrain suggestions; shadow comparisons have outcome and cost evidence.

### 7. Simulation, governed control, and learning

Compare actual execution against shadow route predictions and measure cost, outcome, confidence, and quality. Move an individual policy through disabled → observe → shadow → approval-required → enforced → autonomous. Expand only with measured evidence, explicit fail-open/fail-closed behavior, tenant isolation, least privilege, signed policy versions, auditability, and rollback.

Start with narrow, reversible controls such as retry caps, runaway-agent pauses, hard budgets, concurrency limits, and approved model canaries. Require approval for high-risk changes. Feed verified outcomes back into task/model/workflow benchmarks and calibrate future decisions; deterministic economics remains authoritative.

**Exit:** enforcement is opt-in, policy-scoped, auditable, measurable, and reversible; savings and quality are verified before expansion.

### 8. Economics Analyst and product surfaces

Extend the existing analyst to answer questions across the ledger, execution graph, outcomes, waste, model registry, simulations, and verified savings. The LLM explains evidence returned by deterministic BurnLens APIs; it does not calculate financial truth.

Evolve navigation around **Overview, Economics, Agents, Optimize, Control, Models, Investigate, and Settings** as the capabilities become real. Make Models a product area when registry, pricing, performance, and lifecycle data are ready; do not publish empty or speculative sections.

## Cross-cutting requirements

* Preserve the canonical ledger, APIs, cost totals, and existing user paths.
* Unknown cost, value, quality, or attribution is never silently represented as zero.
* Show pricing provenance and distinguish discovered, recognized, priced, verified, recommended, deprecated, and retired model states.
* Treat provider model identity separately from deployment (direct API, cloud marketplace, region, private endpoint, and customer contract).
* Keep policy authoritative over decision providers; log input signals, decision, policy result, actual route, override, result, and cost.
* Prefer integrations for identity, secrets, orchestration, telemetry, and developer workflow; BurnLens owns cross-provider economics and evidence.
* No autonomy without economics; no enforcement without shadow validation; no optimization claim without outcome-aware verification.

## Explicit non-goals

Do not build an agent framework, generic telemetry platform, general-purpose LLM gateway, or an LLM-based financial calculator. Do not begin with autonomous optimization or claim broad model coverage without verified pricing and lifecycle data.

## Positioning

> **BurnLens is the AI Economics Control Plane: it understands what AI and agents cost, what outcomes they produce, finds economic waste, and determines how AI work should run within cost, quality, and policy constraints.**
