# BurnLens Phase 2: Policy Guardrails & Budget Enforcement

## Build Specification for Claude Code

**Timeline:** Q3–Q4 2026 | **Duration:** 10 weeks | **Build effort:** ~8 weeks
**Depends on:** Phase 1 complete (AI Asset Registry, Detection Engine, Discovery Dashboard)

---

## 1. Phase Overview

Transform BurnLens from passive visibility into active control. Teams can define policies about which AI models are approved, set spend limits per team/project, and receive alerts or enforcement when policies are violated.

**Design principle:** Advisory first, enforcement later — start with alerts, let teams opt into hard blocks.

### Prerequisites from Phase 1

- AI Asset Registry populated with discovered assets
- Provider detection engine running and classifying endpoints
- Discovery dashboard live with asset management capabilities
- Alert infrastructure (Slack/email) operational

### Success Criteria

- Policy engine evaluating rules against every detected AI asset in real-time
- Budget guardrails with soft warnings (80% threshold) and hard caps (100%)
- Anomaly detection flagging usage spikes >200% of 30-day baseline
- Approval workflow for new model requests (Slack-integrated)
- Immutable audit log of every policy violation and enforcement action
- First paid tier launched at $49–$149/month

### Non-Goals

- No regulatory framework mapping (Phase 3)
- No compliance reporting or export (Phase 3)
- No request/response payload inspection
- No multi-tenant governance hierarchy (Phase 4)

---

## 2. Policy Engine Design

The policy engine is the core of Phase 2. It evaluates user-defined rules against AI asset data and triggers actions (alert, warn, block) when rules are violated.

### 2.1 Policy Data Model — `policies`

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `id` | UUID | uuid-v4 | Primary key |
| `name` | VARCHAR(255) | `Production model allowlist` | Human-readable policy name |
| `description` | TEXT | `Only approved models in prod` | Policy purpose |
| `scope` | JSONB | `{"team_id":"uuid"}` | What this applies to: org-wide, team, project, or tag-based |
| `rules` | JSONB | (see DSL below) | Array of rule definitions in JSON DSL |
| `action` | ENUM | `alert` | `alert` (notify only), `warn` (notify + dashboard flag), `block` (prevent if enforcement enabled) |
| `enforcement_mode` | ENUM | `advisory` | `advisory` (alerts only) or `enforced` (active blocking). Default: `advisory` |
| `enabled` | BOOLEAN | `true` | Toggle policy on/off without deleting |
| `created_by` | FK | user-uuid | Who created this policy |
| `created_at` | TIMESTAMP | auto | Creation timestamp |
| `updated_at` | TIMESTAMP | auto | Last modification |

### 2.2 Policy Rule DSL (JSON)

Rules are defined as a JSON array. Each rule has a `type`, `operator`, `value`, and optional scope override. The engine evaluates all rules in a policy with **AND logic** (all must pass). Use separate policies for OR logic.

```json
[
  {
    "type": "model_allowlist",
    "operator": "in",
    "value": ["claude-sonnet-4-20250514", "gpt-4o", "gemini-1.5-pro"],
    "description": "Only these models allowed in production"
  },
  {
    "type": "provider_blocklist",
    "operator": "not_in",
    "value": ["custom", "unknown"],
    "description": "Block unrecognized providers"
  },
  {
    "type": "budget_limit",
    "operator": "lte",
    "value": 5000,
    "unit": "usd_per_month",
    "scope": "per_team",
    "warn_threshold": 0.8,
    "description": "Max $5000/month per team"
  },
  {
    "type": "rate_limit",
    "operator": "lte",
    "value": 100000,
    "unit": "requests_per_day",
    "scope": "per_asset",
    "description": "Max 100K requests/day per model"
  },
  {
    "type": "model_version_pin",
    "operator": "eq",
    "value": "claude-sonnet-4-20250514",
    "description": "Pin to specific version, alert on drift"
  }
]
```

### 2.3 Supported Rule Types

| Rule Type | Operators | Value Type | Scope Options |
|-----------|-----------|------------|---------------|
| `model_allowlist` | `in`, `not_in` | string[] | org, team, project |
| `provider_blocklist` | `in`, `not_in` | string[] | org, team |
| `budget_limit` | `lte`, `lt` | number (USD) | org, team, project, asset |
| `rate_limit` | `lte` | number (requests) | org, team, asset |
| `model_version_pin` | `eq`, `starts_with` | string | asset, project |
| `tag_required` | `has_key`, `has_value` | string | org, team |
| `inactive_timeout` | `gte` | number (days) | org |

### 2.4 Rule Evaluation Flow

```
1. Scheduled job runs every 15 minutes (configurable)
2. For each enabled policy:
   a. Resolve scope → get list of assets this policy applies to
   b. For each asset in scope:
      i.  Evaluate each rule in the policy against asset data
      ii. If ANY rule fails → create violation record
      iii. Execute action based on policy.action + policy.enforcement_mode
3. Dedup: Don't re-create violation if identical unresolved violation exists
4. Log all evaluations (pass and fail) for audit trail
```

---

## 3. Budget Guardrails

Budget enforcement extends BurnLens's cost tracking into active spend management for AI.

### 3.1 Budget Hierarchy

```
Organization budget (total monthly AI spend cap)
  └── Team budget (per-team monthly cap, inherits from org if not set)
       └── Project budget (per-project cap, inherits from team if not set)
            └── Asset budget (per-model cap, optional)
```

**Enforcement cascades:** If a team budget is hit, all assets in that team are affected even if individual asset budgets have headroom.

### 3.2 Budget Data Model — `budgets`

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `id` | UUID | uuid-v4 | Primary key |
| `scope_type` | ENUM | `team` | `org`, `team`, `project`, `asset` |
| `scope_id` | UUID | team-uuid | FK to the scoped entity |
| `monthly_limit_usd` | DECIMAL(10,2) | 5000.00 | Monthly budget cap |
| `warn_threshold` | DECIMAL(3,2) | 0.80 | Percentage at which warning fires (default 0.80) |
| `critical_threshold` | DECIMAL(3,2) | 0.95 | Percentage at which critical alert fires (default 0.95) |
| `current_spend_usd` | DECIMAL(10,2) | 3250.00 | Current month spend (updated hourly) |
| `enabled` | BOOLEAN | true | Toggle on/off |
| `created_at` | TIMESTAMP | auto | Creation timestamp |

### 3.3 Budget Alert Thresholds

| Threshold | Default % | Action | Configurable |
|-----------|-----------|--------|--------------|
| Info | 50% | Dashboard indicator only | Yes |
| Warning | 80% | Slack/email alert to team lead | Yes |
| Critical | 95% | Alert to team lead + admin | Yes |
| Hard cap | 100% | Block (if enforced) or alert (if advisory) | No |

---

## 4. Anomaly Detection

Lightweight statistical anomaly detection on AI usage patterns. No ML model training required — uses rolling baselines.

### 4.1 Anomaly Types

| Anomaly | Detection Method | Default Threshold |
|---------|-----------------|-------------------|
| Spend spike | Daily spend > N × 30-day rolling average | N = 3x (configurable) |
| Request volume spike | Hourly requests > N × 7-day hourly average | N = 5x |
| New provider | Provider not seen in previous 90 days | Always alert |
| Model drift | Model version changed from pinned version | Alert if version_pin policy exists |
| Off-hours usage | Significant usage outside team's configured hours | Optional, disabled by default |

### 4.2 Baseline Storage — `anomaly_baselines`

| Field | Type | Description |
|-------|------|-------------|
| `id` | BIGSERIAL | Primary key |
| `asset_id` | FK | Which AI asset |
| `metric_type` | ENUM | `daily_spend`, `hourly_requests` |
| `baseline_value` | DECIMAL | Rolling average value |
| `stddev` | DECIMAL | Standard deviation |
| `window_days` | INTEGER | Window used for calculation (7 or 30) |
| `computed_at` | TIMESTAMP | When this baseline was last computed |

### 4.3 Implementation

Use Python `statsmodels` for rolling statistics. Compute baselines hourly via scheduled job. Compare each incoming data point against its baseline during the detection engine run. No external ML service dependency.

---

## 5. Approval Workflows

Simple request/approve flow for new model adoption. Integrated with Slack for fast response.

### 5.1 Workflow States

```
REQUESTED → PENDING_REVIEW → APPROVED | REJECTED | EXPIRED (14 days)
```

### 5.2 Approval Request Data Model — `approval_requests`

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `id` | UUID | uuid | Primary key |
| `requester_id` | FK | user-uuid | Who requested |
| `model_name` | VARCHAR | `gpt-4o-mini` | Requested model |
| `provider` | ENUM | `openai` | Provider |
| `justification` | TEXT | `Need for summarization pipeline` | Why this model is needed |
| `scope` | JSONB | `{"project":"chatbot-v2"}` | Where it will be used |
| `status` | ENUM | `pending_review` | Current workflow state |
| `reviewer_id` | FK (nullable) | user-uuid | Who reviewed |
| `review_note` | TEXT | `Approved for Q3 use` | Reviewer comment |
| `reviewed_at` | TIMESTAMP | auto | When decision was made |
| `expires_at` | TIMESTAMP | +14 days | Auto-expire timestamp |
| `created_at` | TIMESTAMP | auto | Request creation |

### 5.3 Slack Integration

- New request → Slack message to approver channel with Approve/Reject buttons
- Button click → PATCH `/api/v1/approvals/{id}` with decision
- Requester notified via DM on decision

---

## 6. Policy Violation Audit Log

Immutable, append-only log of every policy evaluation that resulted in a violation. This becomes the data source for Phase 3 compliance reports.

### 6.1 Violation Log — `policy_violations`

| Field | Type | Description |
|-------|------|-------------|
| `id` | BIGSERIAL | Auto-increment PK |
| `policy_id` | FK | Which policy was violated |
| `asset_id` | FK | Which AI asset triggered the violation |
| `rule_type` | VARCHAR | Which specific rule type was violated |
| `violation_details` | JSONB | Snapshot: `{"rule_value": 5000, "actual_value": 6230, "overage_pct": 24.6}` |
| `action_taken` | ENUM | `alert_sent`, `warning_shown`, `request_blocked`, `no_action` |
| `resolved` | BOOLEAN | Whether the violation has been acknowledged/resolved |
| `resolved_by` | FK (nullable) | User who resolved |
| `resolved_note` | TEXT | Resolution comment |
| `occurred_at` | TIMESTAMP | When the violation was detected (immutable) |
| `resolved_at` | TIMESTAMP (nullable) | When it was resolved |

---

## 7. API Specification

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/policies` | List all policies. Filter by `scope`, `enabled`, `enforcement_mode` |
| `POST` | `/api/v1/policies` | Create new policy with rules DSL |
| `GET` | `/api/v1/policies/{id}` | Get policy detail with violation stats |
| `PUT` | `/api/v1/policies/{id}` | Update policy rules, scope, action, or mode |
| `DELETE` | `/api/v1/policies/{id}` | Soft-delete (disable) policy |
| `POST` | `/api/v1/policies/{id}/evaluate` | Dry-run: evaluate policy against current assets without triggering actions |
| `GET` | `/api/v1/violations` | List violations. Filter by `policy`, `asset`, `resolved`, date range |
| `PATCH` | `/api/v1/violations/{id}/resolve` | Mark violation as resolved with note |
| `GET` | `/api/v1/budgets` | List budget status by team/project with % consumed |
| `POST` | `/api/v1/budgets` | Create/update budget for a scope |
| `GET` | `/api/v1/anomalies` | List detected anomalies with severity and status |
| `POST` | `/api/v1/approvals` | Submit new model approval request |
| `GET` | `/api/v1/approvals` | List approval requests. Filter by status |
| `PATCH` | `/api/v1/approvals/{id}` | Approve or reject a request |

---

## 8. Technical Implementation

### 8.1 Tech Stack Additions

| Component | Technology | Notes |
|-----------|-----------|-------|
| Rule engine | Python (custom JSON DSL evaluator) | No external dependency needed |
| Anomaly detection | `statsmodels` (rolling stats) | pip install |
| Slack integration | Slack Bolt SDK | For interactive approval buttons |
| Scheduled evaluation | APScheduler (existing) | New job: policy evaluation every 15 min |
| Audit log | PostgreSQL append-only table | No updates allowed, only inserts + soft-resolve |

### 8.2 File Structure (New Files)

```
app/
  models/
    policy.py                 # SQLAlchemy model for policies
    violation.py              # Policy violation log model
    budget.py                 # Budget data model
    approval_request.py       # Model approval workflow model
    anomaly_baseline.py       # Rolling baseline storage
  routers/
    policies.py               # CRUD + evaluate endpoints
    violations.py             # Violation list + resolve
    budgets.py                # Budget status endpoints
    anomalies.py              # Anomaly detection endpoints
    approvals.py              # Approval workflow endpoints
  services/
    policy_engine.py          # Core rule evaluation engine
    rule_evaluator.py         # Individual rule type handlers
    budget_enforcer.py        # Budget threshold checks
    anomaly_detector.py       # Statistical anomaly detection
    approval_service.py       # Workflow state machine
  jobs/
    policy_evaluation_job.py  # Scheduled policy evaluation (every 15 min)
    baseline_calculator.py    # Hourly baseline recomputation
    budget_sync_job.py        # Sync current spend from cost engine
frontend/
  src/pages/
    Policies.tsx              # Policy management page
    Violations.tsx            # Violation review page
  src/components/guardrails/
    PolicyBuilder.tsx         # Visual policy creation form
    RuleEditor.tsx            # JSON DSL rule editor
    BudgetMeter.tsx           # Budget consumption gauge
    AnomalyPanel.tsx          # Anomaly alert list
    ApprovalQueue.tsx         # Approval request queue
    ViolationTable.tsx        # Sortable violation log
```

---

## 9. Implementation Plan (8 Weeks)

| Week | Focus | Deliverables | Dependencies |
|------|-------|-------------|--------------|
| 1 | Policy data model | DB migration, policy + violation + budget + approval tables, seed policies | Phase 1 tables live |
| 2 | Rule engine core | JSON DSL parser, rule evaluator, all 7 rule types working | Week 1 |
| 3 | Budget guardrails | Budget hierarchy, threshold alerts, spend tracking integration | BurnLens cost engine |
| 4 | Anomaly detection | Rolling baselines, spike detection, anomaly alerts | Week 2 |
| 5 | Approval workflows | Request/approve flow, Slack integration, email notifications | Week 1 |
| 6 | Policy dashboard UI | Policy builder, violation list, budget meters, anomaly panel | Weeks 2–5 APIs |
| 7 | Audit log + violations | Immutable log, resolution workflow, violation dashboard | Week 2 |
| 8 | Testing + billing + deploy | Integration tests, Lemon Squeezy paid tier, production deploy | All prior weeks |

### 9.1 Testing Requirements

- **Unit tests:** Rule evaluator for each of the 7 rule types with edge cases
- **Integration tests:** Policy CRUD, violation creation, budget threshold alerts
- **End-to-end:** Create policy → asset violates rule → violation logged → alert sent → user resolves
- **Approval flow:** Request → Slack notification → approve via button → allowlist updated
- **Budget tests:** Threshold crossing at 50%, 80%, 95%, 100% with correct actions

### 9.2 Pricing

| Tier | Price | Includes |
|------|-------|----------|
| Free | $0 | Discovery only (Phase 1) |
| Starter | $49/mo | Up to 5 policies, 3 team budgets, email alerts only |
| Pro | $149/mo | Unlimited policies, unlimited budgets, Slack integration, anomaly detection, approval workflows, audit log export |
