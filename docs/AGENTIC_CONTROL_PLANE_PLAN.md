# BurnLens Agentic Control Plane

## Phased Implementation, Graph Engineering, Security & End-to-End Validation Plan

---

## 0. Master Progress Tracker

> **Tracking Rule**: This progress tracker must be updated upon the completion and certification of each phase, following the Standard Post-Phase Validation Report protocol (Section 6). Downstream phases must remain locked until prerequisite phases achieve `CERTIFIED` status.

| Phase | Milestone / Capability | Dependency | Status | Certified Commit | Date Completed | Gate Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Phase 0** | **BL-BASELINE** — Baseline & Compatibility Certification | None | `CERTIFIED` | `30b821d` | 2026-09-12 | [CERTIFIED](assurance/PHASE_0_BASELINE_CERTIFICATION_REPORT.md) |
| **Phase 1** | **BL-AE-001** — Agent Economics Foundation | BL-BASELINE | `CERTIFIED` | `30b821d` | 2026-09-12 | [CERTIFIED](assurance/PHASE_1_AGENT_ECONOMICS_REPORT.md) |
| **Phase 2** | **BL-AE-002** — Economics Analyst | BL-AE-001 | `CERTIFIED` | `30b821d` | 2026-09-12 | [CERTIFIED](assurance/PHASE_2_ECONOMICS_ANALYST_REPORT.md) |
| **Phase 3** | **BL-AE-003** — Simulation & Recommendations | BL-AE-001 | `CERTIFIED` | `30b821d` | 2026-09-12 | [CERTIFIED](assurance/PHASE_3_SIMULATION_RECOMMENDATIONS_REPORT.md) |
| **Phase 4** | **BL-AE-004** — Agent API / MCP | BL-AE-002, BL-AE-003 | `CERTIFIED` | `30b821d` | 2026-09-12 | [CERTIFIED](assurance/PHASE_4_AGENT_API_MCP_REPORT.md) |
| **Phase 5** | **BL-AE-005** — Governance Foundation (Shadow Mode) | BL-AE-004 | `CERTIFIED` | `30b821d` | 2026-09-12 | [CERTIFIED](assurance/PHASE_5_GOVERNANCE_SHADOW_REPORT.md) |
| **Phase 6** | **BL-AE-006** — Assisted Execution (Human-Approved) | BL-AE-005 | `CERTIFIED` | `30b821d` | 2026-09-12 | [CERTIFIED](assurance/PHASE_6_ASSISTED_EXECUTION_REPORT.md) |
| **Phase 7** | **BL-AE-007** — Runtime Guardrails | BL-AE-006 | `CERTIFIED` | `30b821d` | 2026-09-12 | [CERTIFIED](assurance/PHASE_7_RUNTIME_GUARDRAILS_REPORT.md) |
| **Phase 8** | **BL-AE-008** — Verified Savings | BL-AE-007 | `CERTIFIED` | `30b821d` | 2026-09-12 | [CERTIFIED](assurance/PHASE_8_VERIFIED_SAVINGS_REPORT.md) |
| **Phase 9** | **BL-AE-009** — Agent Trust & Earned Autonomy | BL-AE-008 | `CERTIFIED` | `30b821d` | 2026-09-12 | [CERTIFIED](assurance/PHASE_9_AGENT_TRUST_REPORT.md) |
| **Phase 10** | **BL-AE-010** — Controlled Autonomy | BL-AE-009 | `CERTIFIED` | `30b821d` | 2026-09-12 | [CERTIFIED](assurance/PHASE_10_CONTROLLED_AUTONOMY_REPORT.md) |

---

## 1. Objective

Evolve BurnLens from:

> **AI cost observability + outcomes**

into:

> **AI/Agent Economics & Execution Control Plane**

without rewriting or destabilizing the existing BurnLens platform.

The target evolution is:

```text
Observe
  ↓
Attribute
  ↓
Explain
  ↓
Simulate
  ↓
Recommend
  ↓
Govern
  ↓
Act
  ↓
Verify
  ↓
Learn / Earn Autonomy
```

The implementation must preserve the existing BurnLens canonical ledger as the **financial source of truth**.

Agentic capabilities are additive layers around the ledger.

---

# 2. Non-Negotiable Architecture Principles

## P1 — No ledger rewrite

Existing ingestion, pricing, deduplication, reconciliation, outcomes and cost calculations remain authoritative.

Agent information is added through optional correlation dimensions.

```text
existing event
+
optional agent context
```

Existing customers without agent metadata must experience **zero functional change**.

---

## P2 — One deterministic economics engine

Never create a separate agent cost calculator.

All:

* Agent spend
* Workflow spend
* Task spend
* Cost per outcome
* Waste
* Savings
* Budget consumption

must derive from the existing canonical BurnLens ledger.

---

## P3 — Observe before enforce

Every new control progresses through:

```text
DISABLED
   ↓
OBSERVE
   ↓
SHADOW
   ↓
APPROVAL_REQUIRED
   ↓
ENFORCED
   ↓
AUTONOMOUS
```

No capability jumps directly from implementation into production enforcement.

---

## P4 — External identity remains external

BurnLens consumes:

* Entra identities
* GitHub identities
* OAuth/OIDC identities
* AWS identities
* workload identities

BurnLens does **not** become:

* Identity Provider
* OAuth authorization server
* Secrets vault
* Workforce IAM
* Agent orchestration framework

---

# 3. Graph Engineering Model

Treat the roadmap as a dependency graph rather than a linear feature list.

```text
                         ┌──────────────────┐
                         │ Existing Ledger  │
                         └────────┬─────────┘
                                  │
                     ┌────────────▼────────────┐
                     │ AE-001 Agent Economics │
                     └────────────┬────────────┘
                                  │
               ┌──────────────────┴──────────────────┐
               │                                     │
       ┌───────▼────────┐                   ┌────────▼────────┐
       │ AE-002 Analyst │                   │ AE-003 Simulator│
       └───────┬────────┘                   └────────┬────────┘
               │                                     │
               └──────────────────┬──────────────────┘
                                  │
                         ┌────────▼─────────┐
                         │ AE-004 Agent API │
                         │      / MCP       │
                         └────────┬─────────┘
                                  │
                         ┌────────▼─────────┐
                         │ AE-005 Governance│
                         └────────┬─────────┘
                                  │
                         ┌────────▼─────────┐
                         │ AE-006 Assisted  │
                         │    Execution     │
                         └────────┬─────────┘
                                  │
                         ┌────────▼─────────┐
                         │ AE-007 Runtime   │
                         │   Guardrails     │
                         └────────┬─────────┘
                                  │
                         ┌────────▼─────────┐
                         │ AE-008 Verified  │
                         │     Savings      │
                         └────────┬─────────┘
                                  │
                         ┌────────▼─────────┐
                         │ AE-009 Trust     │
                         └────────┬─────────┘
                                  │
                         ┌────────▼─────────┐
                         │ AE-010 Controlled│
                         │     Autonomy     │
                         └──────────────────┘
```

Every node must contain:

```text
Capability
Prerequisites
Data contract
Security controls
Implementation
Automated tests
Evidence
Acceptance criteria
Rollback path
Certification status
```

A downstream node cannot become active until required upstream nodes are certified.

---

# Phase 0 — Baseline & Compatibility Certification

## Goal

Create an immutable reference point proving the existing BurnLens platform works before introducing agentic changes.

## Work

Capture baseline for:

* canonical ingestion
* pricing
* provider events
* deduplication
* reconciliation
* outcomes
* confidence
* waste analysis
* verified savings
* dashboards
* APIs
* CLI/SDK
* public routes

Create compatibility fixtures from real representative events.

## Graph node

```text
BL-BASELINE
     │
     └── prerequisite → AE-001
```

Store:

```text
baseline_commit
schema_version
fixture_version
API_contract_hash
expected_ledger_results
expected_dashboard_results
```

## Security

Confirm existing:

* workspace isolation
* tenant/RBAC boundaries
* API authentication
* secret handling
* logging redaction
* request throttling
* dependency scanning
* DB permissions

## Validation

Replay baseline fixtures.

Required invariant:

```text
fixture input
→ exact same canonical identity
→ exact same cost
→ exact same outcome
→ exact same reconciliation
```

## End-to-end test

```text
Provider event
→ ingestion
→ canonical ledger
→ pricing
→ outcome
→ dashboard/API
```

Must pass before starting AE-001.

## Expected outcome

A signed/certified compatibility baseline against which every future phase is compared.

### Gate

**PASS only if existing BurnLens behaviour is reproducible and deterministic.**

---

# Phase 1 — BL-AE-001 Agent Economics Foundation

## Goal

Make agent execution economically observable without changing existing behaviour.

## Add domain entities

```text
Agent
Workflow
Run
Task
Action
```

Example graph:

```text
User
 ↓
Agent
 ↓
Workflow
 ↓
Run
 ├── Task
 ├── Model Call
 ├── Tool Action
 ├── Retry
 └── Outcome
```

## Schema

Create:

```text
agents
agent_workflows
agent_runs
agent_tasks
agent_actions
```

Extend canonical events only with nullable correlation fields:

```text
agent_id
workflow_id
run_id
task_id
action_id
parent_run_id
```

## Important rule

```text
agent metadata
≠
financial data
```

Agent tables provide context.

The canonical ledger continues providing money.

## Parent/child graph

Use:

```text
run_id
parent_run_id
root_run_id
```

Example:

```text
Planner
 ├── Research Agent
 ├── Coding Agent
 │    └── Testing Agent
 └── Review Agent
```

This enables recursive economics.

## Outputs

BurnLens can calculate:

* Cost per agent
* Cost per workflow
* Cost per run
* Cost per task
* Model cost
* Retry cost
* Tool-associated cost
* Cost per successful outcome
* Agent efficiency

## Security

Agent metadata must inherit:

```text
workspace_id
```

on every entity.

Prevent:

```text
Workspace A agent
→ referencing Workspace B task/run/action
```

Use:

* tenant-scoped foreign keys where practical
* authorization at API/service layer
* no arbitrary external identity trust
* immutable run ownership after creation
* strict input validation

## Validation

### Compatibility test

Old event:

```text
agent_id = NULL
```

must produce exactly the same cost and canonical event as before.

### Attribution test

```text
canonical workspace spend
=
agent-attributed spend
+
unattributed spend
```

### Replay test

Same event + same context:

```text
→ deduplicated
```

Same event + conflicting agent context:

```text
→ conflict surfaced
```

not silently overwritten.

### Parent-child test

```text
Parent Agent = $10

Child A = $3
Child B = $7

rollup = $10
```

No double counting.

## E2E scenario

```text
Coding agent starts task
→ calls LLM
→ calls GitHub
→ retries model once
→ creates PR
→ outcome accepted
```

BurnLens must show:

```text
Agent
Task
Model spend
Retry waste
Actions
Outcome
Total cost
Cost per accepted outcome
```

## Expected outcome

> BurnLens can explain exactly what one agent task cost and whether it produced an accepted result.

### Certification gate

**AE-001 PASS**

Required:

* Existing flows unchanged
* Ledger reconciliation unchanged
* Agent correlation works
* Parent/child rollups correct
* Agent UI feature-flagged
* No enforcement

---

# Phase 2 — BL-AE-002 Economics Analyst

## Goal

Allow users to investigate economics conversationally.

Example questions:

```text
Why did agent spend increase?
Which workflow wastes the most money?
Why did task costs increase this week?
Which agents have poor cost/outcome?
```

## Architecture

```text
User
 ↓
Economics Analyst
 ↓
Tool/API selection
 ↓
Deterministic BurnLens API
 ↓
Structured results
 ↓
LLM explanation
```

## Critical control

The LLM must never calculate authoritative financial results from raw data.

For example:

```text
BAD

LLM → database rows → calculate $42,193
```

Use:

```text
GOOD

API → total = $42,193
LLM → explain why
```

## Graph engineering

Analyst capabilities become registered graph nodes:

```text
Question
  ↓
Intent
  ↓
Required Metric
  ↓
BurnLens API
  ↓
Evidence
  ↓
Explanation
```

Every statement should retain provenance to source metric/API.

## Security

Implement:

* tenant-scoped API credentials
* tool allowlist
* read-only analyst identity
* query limits
* no unrestricted SQL
* output redaction
* prompt-injection resistant tool boundary

## Validation

Golden question set:

```text
Q1: Which agent cost most yesterday?
Q2: What caused workflow X to increase?
Q3: What proportion was retry waste?
Q4: Which task had worst cost/outcome?
```

Expected numeric answer must equal deterministic API response.

## E2E test

```text
User asks question
→ analyst chooses correct API
→ API executes tenant-scoped query
→ evidence returned
→ analyst explains result
```

Test failure case:

```text
malicious prompt asks analyst
to reveal another workspace
```

Expected:

```text
DENIED
```

## Expected outcome

> BurnLens becomes conversational without sacrificing financial correctness.

### Gate

**AE-002 PASS** only if analyst answers match deterministic APIs within exact metric semantics.

---

# Phase 3 — BL-AE-003 Simulation & Recommendations

## Goal

Move from explaining inefficiency to proposing improvements.

## Recommendation graph

```text
Observed anomaly
      ↓
Detector
      ↓
Evidence
      ↓
Candidate optimization
      ↓
Simulation
      ↓
Expected saving
      ↓
Quality/risk analysis
      ↓
Recommendation
```

## Recommendation object

```text
recommendation_id
scope
evidence
current_cost
projected_cost
expected_saving
confidence
quality_risk
implementation_plan
rollback_plan
status
```

## Initial recommendation categories

* model overkill
* retry reduction
* context reduction
* caching opportunity
* redundant tool calls
* runaway loops
* poor routing
* repeated failures

## Security

No write access.

Recommendations are advisory only.

Protect against:

* manipulating production config
* autonomous tool calls
* secret exposure
* cross-tenant recommendations
* unbounded simulations

## Validation

Every recommendation needs:

```text
evidence
+
reproducible calculation
+
confidence
+
quality impact estimate
+
rollback strategy
```

Run historical backtesting where possible.

Example:

```text
Historical period: 30 days

Predicted saving: $900
Backtested saving: $847

variance: 5.9%
```

## E2E test

```text
High model spend detected
→ simulator evaluates cheaper model
→ expected saving produced
→ confidence calculated
→ quality risk attached
→ recommendation displayed
```

No external change occurs.

## Expected outcome

> BurnLens can tell customers what to change and why.

### Gate

**AE-003 PASS** when recommendations are reproducible and no production mutation is possible.

---

# Phase 4 — BL-AE-004 Agent API / MCP

## Goal

Allow external AI agents to consume BurnLens intelligence.

## API first

Implement deterministic APIs before MCP.

Examples:

```text
get_agent_economics
get_task_economics
find_waste
estimate_cost
simulate_change
check_budget
get_cost_per_outcome
```

Then:

```text
BurnLens APIs
     ↓
MCP adapter
```

## Graph model

Each exposed capability becomes an independently permissioned node.

```text
Agent
 ↓
BurnLens API/MCP
 ├── READ ECONOMICS
 ├── CHECK BUDGET
 ├── SIMULATE
 └── GET RECOMMENDATION
```

## Security

Implement:

* OAuth/OIDC integration
* scopes
* workspace constraints
* rate limits
* tool-level authorization
* request audit
* response filtering
* no raw DB exposure

Example:

```text
scope:economics.read
scope:simulation.execute
```

## Validation

Test:

```text
valid agent + valid workspace → PASS
valid agent + wrong workspace → DENY
invalid token → DENY
expired token → DENY
unauthorized capability → DENY
```

## E2E scenario

Coding agent asks:

```text
"Can I afford another retry?"
```

Flow:

```text
Agent
→ check_budget
→ BurnLens ledger
→ task remaining budget
→ response
```

## Expected outcome

> Other agents can safely use BurnLens as their economics intelligence service.

### Gate

**AE-004 PASS**

No external agent receives access beyond explicitly granted BurnLens capabilities.

---

# Phase 5 — BL-AE-005 Governance Foundation

## Goal

Introduce runtime decisioning without enforcement.

## Add

```text
policy_decisions
approvals
budget_rules
risk_classifications
```

## Decision model

```text
ALLOW
DENY
REQUIRE_APPROVAL
BUDGET_EXCEEDED
```

## Execution graph

```text
Agent
 ↓
Task
 ↓
Action requested
 ↓
Policy evaluation
 ↓
Decision
 ↓
SHADOW RESULT ONLY
```

At this phase:

```text
enforcement = OFF
```

## Policy examples

```text
Read repository       → ALLOW
Create branch         → ALLOW
Open PR               → ALLOW
Merge production PR   → REQUIRE_APPROVAL
Change IAM            → DENY
```

## Economic policies

```text
Task budget > $10
→ REQUIRE_APPROVAL
```

## Security

Policies themselves are sensitive resources.

Implement:

* policy RBAC
* versioning
* immutable history
* approval for production policy updates
* tenant isolation
* safe defaults
* fail closed if enforcement is later enabled

## Validation

Shadow evaluation against real historical actions.

Example:

```text
10,000 actions

Would allow       9,430
Would approve       520
Would deny           50
```

Review false positives/negatives.

## E2E test

```text
Agent requests merge
→ policy evaluates
→ REQUIRE_APPROVAL
→ event logged
→ agent still allowed because shadow mode
```

## Expected outcome

> BurnLens can accurately predict governance decisions without affecting workloads.

### Gate

**AE-005 PASS**

Policy accuracy validated before enforcement can ever activate.

---

# Phase 6 — BL-AE-006 Assisted Execution

## Goal

Allow BurnLens to execute approved recommendations.

Start with **GitHub coding workflows only**.

## Flow

```text
BurnLens recommendation
       ↓
Human review
       ↓
Approval
       ↓
Execution adapter
       ↓
GitHub branch/PR
       ↓
CI
       ↓
Result captured
```

## Allowed initially

* create branch
* modify explicitly scoped files
* create PR
* update PR

## Not allowed initially

* direct protected branch push
* automatic merge
* IAM/security policy modification
* secret access
* destructive resource action

## Security

Use short-lived credentials issued by GitHub/external IAM.

BurnLens stores no long-lived privileged secrets where avoidable.

Implement:

* least privilege
* explicit repo scope
* approval binding
* action expiry
* replay prevention
* idempotency keys
* audit logging

## Validation

Approval must be cryptographically/logically tied to:

```text
agent
task
action
resource
commit/config
expiry
```

Changing any of these invalidates the approval.

## E2E test

```text
Recommendation generated
→ human approves
→ branch created
→ change committed
→ PR opened
→ CI runs
→ PR remains unmerged
→ audit timeline complete
```

Negative tests:

```text
approval expired → DENY
repo changed → DENY
scope changed → DENY
duplicate execution → NO DUPLICATE
```

## Expected outcome

> BurnLens can safely turn recommendations into reviewable changes.

### Gate

**AE-006 PASS**

Human remains the mandatory execution authority.

---

# Phase 7 — BL-AE-007 Runtime Guardrails

## Goal

Prevent obvious economic/runtime failures.

## Initial guardrails

```text
retry storm          → PAUSE
hard budget exceeded → STOP
runaway task         → PAUSE
repeated tool error  → PAUSE
forbidden action     → DENY
```

## Graph

```text
Execution
   ↓
Runtime telemetry
   ↓
Detector
   ↓
Policy
   ↓
Guardrail decision
   ↓
PAUSE / STOP / DENY / ALLOW
```

## Security

Guardrails must be:

* deterministic
* explainable
* bounded
* reversible where possible
* protected from user-agent override

Agent cannot say:

```text
"Ignore budget limit."
```

and bypass BurnLens.

## Fail-safe design

If control plane unavailable:

Define explicitly per capability:

```text
Read-only economics
→ fail open

High-risk production action
→ fail closed

Budget enforcement
→ customer-configurable safe mode
```

## Validation

Chaos tests:

* BurnLens unavailable
* policy service timeout
* duplicated event
* delayed telemetry
* partial action completion
* webhook replay

## E2E test

```text
Agent enters retry loop
→ retries detected
→ threshold exceeded
→ policy evaluated
→ task paused
→ action recorded
→ human notified
→ restart possible
```

## Expected outcome

> BurnLens prevents measurable agentic waste without becoming a general security platform.

### Gate

**AE-007 PASS**

Guardrails demonstrate safe behaviour under fault injection.

---

# Phase 8 — BL-AE-008 Verified Savings

## Goal

Prove recommendations created real economic value.

## Verification graph

```text
Recommendation
   ↓
Projected baseline
   ↓
Change
   ↓
Observation window
   ↓
Actual economics
   ↓
Outcome / quality
   ↓
Verification
```

## Verification record

```text
recommendation_id

projected_saving
actual_saving
variance

baseline_outcome_rate
new_outcome_rate

quality_change
confidence

PASS / FAIL / INCONCLUSIVE
```

## Security

Verification calculations must:

* use immutable recommendation baseline
* prevent post-hoc baseline manipulation
* preserve evidence
* record calculation version

## Validation

Test:

```text
Projected = $1,700
Actual = $1,520
Quality = acceptable

→ VERIFIED PASS
```

Negative:

```text
Saving achieved
but outcome quality drops 7%

→ VERIFIED FAIL
```

## E2E test

```text
detect
→ recommend
→ approve
→ PR/config change
→ deployment
→ collect economics
→ collect outcomes
→ compare
→ verify
```

## Expected outcome

> BurnLens distinguishes hypothetical savings from proven savings.

### Gate

**AE-008 PASS**

Verification is reproducible from stored evidence.

---

# Phase 9 — BL-AE-009 Agent Trust & Earned Autonomy

## Goal

Create an evidence-based autonomy model.

## Signals

```text
task_success_rate
accepted_outcome_rate
rollback_rate
policy_violation_rate
approval_rejection_rate
budget_overrun_rate
retry_rate
waste_ratio
human_intervention_rate
```

## Trust graph

```text
Historical executions
       ↓
Outcome evidence
       ↓
Policy evidence
       ↓
Economic evidence
       ↓
Risk normalization
       ↓
Trust score
```

Do not use an opaque LLM-generated trust score.

Trust must remain deterministic/explainable.

## Example

```text
Agent Trust: 94

Success          97%
Accepted         95%
Violations        0
Rollback         0.3%
Waste            2.7%
```

## Security

Prevent:

* self-reported trust metrics
* score manipulation
* circular scoring
* sparse-history overconfidence

New agents default to low autonomy.

## Validation

Backtest:

Would previously high-trust agents actually have produced safe outcomes under increased autonomy?

Measure:

```text
false trust
false distrust
rollback rate
policy incidents
```

## E2E test

```text
Trusted agent
+ low-risk task
+ <$5 expected spend
+ reversible action
→ autonomous permission

Same agent
+ production IAM change
→ human approval still required
```

## Expected outcome

> Autonomy is earned from evidence rather than granted globally.

### Gate

**AE-009 PASS**

Trust affects only explicitly eligible actions.

---

# Phase 10 — BL-AE-010 Controlled Autonomy

## Goal

Close the economics loop.

```text
DETECT
   ↓
INVESTIGATE
   ↓
SIMULATE
   ↓
POLICY CHECK
   ↓
ACT
   ↓
VERIFY
   ↓
EXPAND / ROLLBACK
```

## Initially autonomous

Only actions satisfying all:

```text
low risk
reversible
small blast radius
high confidence
within budget
sufficient trust
policy approved
rollback available
```

Examples:

* stop retry storm
* pause runaway task
* enforce hard budget
* reduce concurrency
* canary cheaper model
* rollback failed optimization

## Explicitly excluded initially

* IAM modification
* destructive infrastructure changes
* secret operations
* high-blast-radius production changes
* irreversible data operations

## Security

Add:

```text
autonomy ceiling
blast-radius limits
canary percentage
maximum spend delta
automatic rollback
kill switch
global workspace disable
```

Every autonomous action requires a complete audit chain.

## E2E certification scenario

Run one complete scenario:

```text
1. Agent starts task

2. BurnLens attributes:
   user
   agent
   workflow
   model calls
   tool calls
   spend

3. Retry anomaly detected

4. Economics Analyst explains cause

5. Simulator identifies optimization

6. Recommendation created

7. Policy evaluates risk

8. Action approved/autonomously eligible

9. Canary optimization executed

10. Metrics observed

11. Savings measured

12. Outcome quality checked

13A. PASS
     → expand

OR

13B. FAIL
     → rollback

14. Verified Savings record created

15. Agent trust updated
```

## Expected outcome

> BurnLens safely optimizes agent economics within explicit cost, risk and outcome boundaries.

### Gate

**AE-010 CERTIFIED**

Only then should BurnLens position itself as supporting controlled autonomous optimization.

---

# 4. Cross-Phase Security Architecture

Security must not be a final-stage workstream.

It exists across every graph node.

## Identity

External identity provider remains authoritative.

```text
Human → OIDC/OAuth
Agent → external workload identity
```

BurnLens maps identities to its internal execution context.

---

## Authorization

Every request evaluates:

```text
Workspace
User
Agent
Task
Tool
Action
Resource
Environment
Risk
Budget
```

---

## Data isolation

Every domain object carries:

```text
workspace_id
```

Cross-workspace references must fail.

---

## Credentials

Prefer:

```text
short-lived
scoped
externally issued
non-exportable where possible
```

Never expose credentials to LLM context.

---

## Audit

Capture:

```text
initiator
agent
task
tool
resource
policy
approval
execution
result
cost
outcome
timestamp
trace_id
```

---

## Prompt/tool security

Treat agent input as untrusted.

Protect against:

* prompt injection
* tool injection
* resource substitution
* approval replay
* malicious URLs
* secret exfiltration
* indirect instructions from repository/document content

---

# 5. Mandatory Test Pyramid Per Phase

Every phase must complete five layers.

## Layer 1 — Unit

Test individual calculations and policies.

## Layer 2 — Contract

Validate API/schema compatibility.

## Layer 3 — Integration

Example:

```text
Agent → BurnLens → ledger
```

or:

```text
BurnLens → GitHub
```

## Layer 4 — Security

Negative and adversarial scenarios.

## Layer 5 — End-to-End

Full business journey.

No phase gets certification from unit tests alone.

---

# 6. Standard Post-Phase Validation Report

Every milestone should produce the same certification artifact.

```text
PHASE:
BUILD:
COMMIT:
ENVIRONMENT:

FUNCTIONAL STATUS:
PASS / PARTIAL / FAIL

COMPATIBILITY:
PASS / FAIL

SECURITY:
PASS / FAIL

DATA RECONCILIATION:
PASS / FAIL

E2E:
PASS / FAIL

PERFORMANCE:
PASS / FAIL

ROLLBACK:
TESTED / NOT TESTED

OPEN RISKS:

BLOCKERS:

EVIDENCE:

VERDICT:
CERTIFIED
CONDITIONALLY CERTIFIED
NOT CERTIFIED
```

No subjective "looks good."

---

# 7. Global Regression Suite

Run this after **every phase**.

```text
Existing ingestion                    PASS
Existing pricing                      PASS
Existing dedup                        PASS
Existing outcomes                     PASS
Existing reconciliation               PASS
Existing dashboards                   PASS
Existing APIs                         PASS
Existing CLI                          PASS
Existing public routes                PASS

Agent-disabled workspace              PASS
Agent-enabled workspace               PASS

Tenant isolation                      PASS
AuthN/AuthZ                            PASS
Replay protection                     PASS
Rate limiting                         PASS

Agent attribution reconciliation      PASS
Cost/outcome calculation              PASS
```

This is what protects the existing BurnLens product while the new platform evolves.

---

# 8. First Golden End-to-End Journey

The first canonical use case should remain deliberately narrow.

## Scenario

> Coding agent fixes a vulnerable dependency.

```text
Human
 ↓
Coding Agent
 ↓
BurnLens Task
 ↓
LLM calls
 ↓
Repository reads
 ↓
Code change
 ↓
Tests
 ↓
GitHub PR
 ↓
Human approval
 ↓
Merge
 ↓
Outcome accepted
 ↓
Economics calculated
 ↓
Savings eventually verified
```

BurnLens should ultimately display:

```text
Task
Fix vulnerable dependency

Agent
Codex security-fixer v2.3

Total cost           $3.78
Model cost           $2.73
CI/tool cost         $0.71
Retry waste          $0.34

Outcome              ACCEPTED

Policy decisions      8
Denied                 0
Human approvals        1

Cost / outcome        $3.78

Projected saving      $420/month
Verified saving       $398/month

Agent trust           94
```

This one journey should grow through the phases rather than inventing a different demo for every milestone.

---

# 9. Recommended Execution Order

Do not combine phases simply because implementation appears easy.

Execute:

```text
Phase 0
Baseline

↓

Phase 1
Agent Economics

↓

Phase 2
Economics Analyst

↓

Phase 3
Simulation

↓

Phase 4
Agent API / MCP

↓

Phase 5
Governance Shadow Mode

↓

Phase 6
Human-approved Execution

↓

Phase 7
Runtime Guardrails

↓

Phase 8
Verified Savings

↓

Phase 9
Trust

↓

Phase 10
Controlled Autonomy
```

The fundamental safety principle is:

> **No autonomy without economics.
> No action without simulation.
> No enforcement without shadow validation.
> No trust without historical evidence.
> No optimization claim without verification.**

---

# 10. Final Target Architecture

```text
               ┌──────────────────────┐
               │ Humans / AI Agents   │
               └──────────┬───────────┘
                          │
               ┌──────────▼───────────┐
               │ BurnLens Agent API   │
               │      / MCP           │
               └──────────┬───────────┘
                          │
      ┌───────────────────┼────────────────────┐
      │                   │                    │
┌─────▼──────┐    ┌──────▼───────┐    ┌──────▼─────┐
│ Economics  │    │ Intelligence │    │ Governance │
│ Engine     │    │ Analyst      │    │ Engine     │
└─────┬──────┘    └──────┬───────┘    └──────┬─────┘
      │                   │                    │
      │            ┌──────▼───────┐            │
      │            │ Simulation & │            │
      │            │ Recommend    │            │
      │            └──────┬───────┘            │
      │                   │                    │
      └───────────────────┼────────────────────┘
                          │
                 ┌────────▼────────┐
                 │ Execution      │
                 │ Adapters       │
                 └────────┬────────┘
                          │
              GitHub / ADO / Cloud / MCP
                          │
                 ┌────────▼────────┐
                 │ Verification   │
                 │ + Trust        │
                 └────────┬────────┘
                          │
                 ┌────────▼────────┐
                 │ Existing       │
                 │ BurnLens       │
                 │ Canonical      │
                 │ Ledger         │
                 └─────────────────┘
```

The **canonical ledger remains underneath the entire graph**.

That is what allows BurnLens to become much more agentic without compromising the core product that already works.

## Final engineering rule

Each phase should be considered a separately certifiable production increment.

The team should never implement:

> Agent Economics + Analyst + MCP + Policies + Execution

as one large initiative.

The correct pattern is:

> **Implement node → test → security review → E2E → certify → enable narrowly → observe → move to next node.**

That creates an auditable path from today's BurnLens to the long-term **AI Economics Control Plane** while maintaining backward compatibility and controlling operational risk.
