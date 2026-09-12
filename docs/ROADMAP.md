# BurnLens Master Roadmap — Agent Economics & Governance

These two roadmaps should be **merged rather than run independently**. The economics roadmap is the foundation; the execution/governance roadmap sits on top of it.

The resulting BurnLens roadmap is:

> **Economics → Intelligence → Recommendations → Integration → Governance → Action → Verification → Autonomy**

* **Detailed Implementation, Security Architecture & End-to-End Validation Plan**: [docs/AGENTIC_CONTROL_PLANE_PLAN.md](AGENTIC_CONTROL_PLANE_PLAN.md)
* **Master Progress Tracker & Certification Gates**: See [Section 0 of AGENTIC_CONTROL_PLANE_PLAN.md](AGENTIC_CONTROL_PLANE_PLAN.md#0-master-progress-tracker)

---

## Unified BurnLens Agentic Roadmap

| Seq. | Milestone                                  | What BurnLens adds                                                                                   | Primary outcome                 |
| ---- | ------------------------------------------ | ---------------------------------------------------------------------------------------------------- | ------------------------------- |
| 1    | **BL-AE-001 Agent Economics Foundation**   | Agent registry, workflow/run/task identity, parent-child agents, model/tool calls, retries, outcomes | Understand agent spend          |
| 2    | **BL-AE-002 Economics Analyst**            | Conversational investigation over deterministic BurnLens APIs                                        | Explain spend and waste         |
| 3    | **BL-AE-003 Simulation & Recommendations** | Optimization simulation, expected savings, confidence, quality risk                                  | Recommend changes               |
| 4    | **BL-AE-004 Agent/MCP API**                | BurnLens economics and policy capabilities consumable by agents                                      | Agents can query BurnLens       |
| 5    | **BL-AE-005 Governance Foundation**        | Agent actions, budgets, policy decisions, approvals, audit timeline                                  | Decide what agents may do       |
| 6    | **BL-AE-006 Assisted Execution**           | GitHub/ADO PRs, config/Terraform/routing changes with human approval                                 | Controlled action               |
| 7    | **BL-AE-007 Runtime Guardrails**           | Stop loops, enforce budgets, pause runaway agents, deny unsafe actions                               | Prevent economic/runtime damage |
| 8    | **BL-AE-008 Verified Savings**             | Compare projected vs actual savings and outcome/quality impact                                       | Prove value                     |
| 9    | **BL-AE-009 Trust & Earned Autonomy**      | Agent Trust Score, dynamic policies, autonomy levels                                                 | Reliable agents earn freedom    |
| 10   | **BL-AE-010 Controlled Autonomy**          | Detect → simulate → policy → execute → verify → rollback/expand                                      | Closed-loop economics control   |

---

# 1. BL-AE-001 — Agent Economics Foundation

**This is the immediate implementation priority.**

Extend the existing BurnLens ledger rather than creating another platform.

Add first-class entities:

```text
Agent
  ↓
Workflow
  ↓
Task / Run
  ↓
Model Calls
  ↓
Tool Calls
  ↓
Retries
  ↓
Costs
  ↓
Outcome
```

Add correlation dimensions such as:

```text
agent_id
agent_version
workflow_id
task_id
run_id
parent_agent_id
action_id
tool_name
trace_id
outcome_id
```

Produce:

* Agent spend
* Workflow spend
* Task/run spend
* Model vs tool/infrastructure cost
* Cost per accepted outcome
* Retry waste
* Tool-call waste
* Agent efficiency
* Agent/run timeline

### First vertical slice

Use **coding agents + GitHub**:

```text
Coding agent
     ↓
Task
     ↓
LLM calls
     ↓
Tool calls
     ↓
GitHub PR
     ↓
CI
     ↓
Accepted outcome
```

BurnLens should answer:

> **“This agent completed this task for $3.78, including $0.34 of avoidable waste, and the resulting PR was accepted.”**

No enforcement yet.

---

# 2. BL-AE-002 — BurnLens Economics Analyst

Once the data model is trustworthy, add a read-only BurnLens agent.

Users ask:

> Why did our agent spend increase 37%?

> Which coding agent wastes the most money?

> Which workflow has the worst cost per successful outcome?

> Why did `payments-agent` cost twice as much this week?

The LLM **must not calculate financial metrics itself**.

Architecture:

```text
User
 ↓
BurnLens Analyst
 ↓
Deterministic BurnLens APIs
 ↓
Ledger / Outcomes / Waste
 ↓
Explanation
```

The analyst explains evidence produced by deterministic services.

---

# 3. BL-AE-003 — Simulation & Recommendations

Turn existing waste intelligence into recommendations.

BurnLens identifies:

```text
Expensive model routing
Excessive retries
Long context
Duplicate tool calls
Agent loops
Poor cache usage
Low-value calls
Repeated failures
```

Every recommendation should return:

```text
Problem
Evidence
Recommendation
Expected saving
Confidence
Quality risk
Affected workflows
Rollback approach
```

Example:

```text
Change:
GPT-5.6 → smaller model
for classification step

Current spend:
$2,140/month

Estimated spend:
$1,280/month

Expected saving:
$860/month

Confidence:
94%

Quality risk:
0.6%

Rollback:
Immediate
```

Still **recommendation only**.

---

# 4. BL-AE-004 — BurnLens Agent API / MCP

Now expose BurnLens to other agents.

For example:

```text
get_agent_economics
get_task_economics
get_cost_per_outcome
find_waste
estimate_cost
simulate_model_change
check_budget
get_recommendations
```

A coding agent could therefore ask:

```text
Can I afford another debugging iteration?
```

BurnLens returns:

```text
Task budget       $10.00
Consumed           $8.20
Remaining          $1.80

Estimated action   $2.60

Recommendation:
Do not execute without budget override.
```

This makes **agents themselves BurnLens customers**.

---

# 5. BL-AE-005 — Governance Foundation

This is where the second roadmap joins the first one.

Introduce:

### Agent Registry

```text
Agent
Owner
Version
Environment
Purpose
Status
External identity
```

BurnLens records identity metadata but does **not authenticate identities itself**.

### Agent Actions

```text
Agent
Task
Tool
Action
Resource
Environment
Estimated cost
Risk
```

### Policy Decision

Keep the initial decisions simple:

```text
ALLOW
DENY
REQUIRE_APPROVAL
BUDGET_EXCEEDED
```

### Approval

Track:

```text
requested_by
approver
action
resource
decision
reason
expiry
```

And retain everything in the execution timeline.

---

# 6. BL-AE-006 — Assisted Execution

Only after recommendations are reliable should BurnLens start making changes.

Start with:

### GitHub

```text
Read repo             → Allow
Create branch         → Allow
Open PR               → Allow
Merge PR              → Approval
Modify CI/security    → Elevated approval
Protected push        → Deny
```

Then potentially:

* Azure DevOps
* Terraform
* model-routing configuration
* agent configuration
* budget configuration

The operating model remains:

> **BurnLens detects → recommends → human approves → BurnLens acts.**

---

# 7. BL-AE-007 — Runtime Guardrails

Now move some existing detection from **analytics → control**.

Examples:

```text
Retry storm
    ↓
BurnLens detects
    ↓
PAUSE
```

```text
Task budget exceeded
    ↓
STOP / APPROVAL
```

```text
Abnormal cost acceleration
    ↓
REQUIRE APPROVAL
```

```text
Repeated tool failure
    ↓
PAUSE AGENT
```

```text
Forbidden production action
    ↓
DENY
```

Introduce a **dry-run policy mode** first:

```text
Observed 18,400 actions

Would allow          17,821
Would approve           487
Would deny               92

Enforcement: OFF
```

Customers can validate rules before BurnLens starts blocking production workflows.

---

# 8. BL-AE-008 — Verified Savings

This should remain one of BurnLens' defining capabilities.

Recommendation:

```text
Expected saving:
$1,700/month
```

After rollout:

```text
Expected saving         $1,700
Actual saving           $1,520

Expected quality change <1%
Observed                 -0.2%

Outcome success
Before                   93.1%
After                    93.4%

VERIFICATION
PASS
```

BurnLens therefore distinguishes:

**Recommended savings** from **Verified savings**.

That is a significant product differentiator.

---

# 9. BL-AE-009 — Agent Trust & Earned Autonomy

Once enough execution history exists, calculate trust signals.

Possible inputs:

```text
accepted_outcome_rate
task_success_rate
rollback_rate
policy_violation_rate
approval_rejection_rate
waste_ratio
budget_overrun_rate
retry_rate
human_intervention_rate
```

Example:

```text
Agent: security-fixer

Tasks                    1,284
Accepted outcomes        1,191
Rollbacks                   3
Policy violations           0
Budget overruns              4
Waste ratio               3.7%

Trust Score
94 / 100
```

Then connect trust to governance:

```text
Trust > 90
+
Low risk
+
Cost < $5
+
Reversible action

→ Autonomous execution
```

But:

```text
Production
+
IAM/security change

→ Human approval
```

This is **earned autonomy**, not blanket autonomy.

---

# 10. BL-AE-010 — Controlled Autonomy

This becomes the eventual BurnLens closed loop:

```text
        OBSERVE
           ↓
       ATTRIBUTE
           ↓
        EXPLAIN
           ↓
         DETECT
           ↓
        SIMULATE
           ↓
       RECOMMEND
           ↓
      POLICY CHECK
           ↓
      ┌────┴─────┐
    APPROVE    DENY
       ↓
       ACT
       ↓
      VERIFY
       ↓
 ┌─────┴──────┐
EXPAND      ROLLBACK
```

Examples of suitable autonomous actions:

* Stop retry storms
* Pause runaway agents
* Enforce hard budgets
* Reduce concurrency
* Canary cheaper models
* Apply already-approved routing policies
* Roll back failed optimizations

Not autonomous initially:

* IAM modification
* Security policy changes
* Destructive infrastructure actions
* Production deployment decisions with major blast radius

---

# What BurnLens owns vs integrates

This boundary should remain explicit.

### BurnLens owns

**Economics**

* Spend
* Attribution
* Waste
* Outcome economics
* Verified savings

**Governance**

* Agent/task budgets
* Policy decisions
* Approval gates
* Runtime economic controls

**Intelligence**

* Investigation
* Simulation
* Recommendations
* Trust
* Autonomous optimization

**Evidence**

* Agent/action timeline
* Decision history
* Economic evidence
* Outcome verification

### BurnLens integrates

Do **not** build replacements for:

```text
Entra / Okta / Auth0        → Identity
GitHub / Azure DevOps       → Developer workflow
AWS / Azure IAM             → Credentials/access
Vault / Key Vault           → Secrets
OPA / Cedar / AuthZEN       → Policy primitives where useful
OpenTelemetry               → Telemetry
LangGraph / CrewAI / etc.   → Agent orchestration
```

---

# Product evolution

### BurnLens today

> **What is our AI costing us?**

### Agent Economics

> **Which agents and workflows are consuming the money, and what are we getting for it?**

### Economics Intelligence

> **Why is it happening, and what should we change?**

### Economics Governance

> **Should this agent/action be allowed given cost, risk and policy?**

### AI Economics Control Plane

> **BurnLens continuously optimizes AI economics while keeping autonomous systems inside approved cost, risk and outcome boundaries.**

So I would standardize the long-term product loop as:

# **Observe → Attribute → Explain → Simulate → Recommend → Govern → Act → Verify → Learn**

And the key sequencing principle remains:

> **Economics first → intelligence second → governance third → execution fourth → autonomy last.**

That prevents BurnLens from becoming an overbuilt generic agent platform and keeps every new capability anchored to its strongest differentiator: **proving and controlling the economics of AI work.**
