# BurnLens Phase 4: Governance Platform (Evaluate & Expand)

## Build Specification for Claude Code

**Timeline:** Q1–Q2 2027 | **Duration:** 12 weeks | **Build effort:** ~10 weeks
**Depends on:** Phase 1 + 2 + 3 complete
**⚠️ CONDITIONAL: Only proceed if go/no-go criteria below are met**

---

## 1. Go/No-Go Criteria

Phase 4 is conditional. ALL of the following must be true before investing in these features.

| # | Criterion | Measurement | Threshold |
|---|-----------|------------|-----------|
| 1 | Active guardrails users | Teams with 1+ active policies in Phase 2 | **50+ teams** |
| 2 | Compliance report consumers | Unique users downloading reports monthly | **10+ customers** |
| 3 | Inbound feature requests | Requests for deeper governance features | **5+ unique orgs** |
| 4 | Revenue from governance tiers | MRR from Phase 2+3 paid tiers | **>$5K MRR** |
| 5 | Retention signal | Churn rate of governance tier customers | **<5% monthly** |

### Decision Framework

- **5/5 met:** Full Phase 4 build
- **3–4/5 met:** Build only the most-requested features (cherry-pick)
- **<3/5 met:** Governance stays a feature. Focus on BurnLens core cost optimization.

---

## 2. Phase Overview

Phase 4 moves BurnLens from "AI cost tool with governance features" to "lightweight AI governance platform." It adds pre-deployment gates, data sensitivity tagging, multi-tenant governance, framework alignment, and a public API.

### Success Criteria

- CI/CD integration gates blocking unapproved models before deployment
- Auto-detection of PII/sensitive data flowing to AI endpoints
- Multi-tenant governance: org-level policies cascading to teams
- Self-assessment checklists aligned to NIST AI RMF and ISO 42001
- Public governance API consumed by 5+ external integrations
- Price point: $399–$999/month

---

## 3. Model Evaluation Hooks (CI/CD Gates)

Pre-deployment gates that evaluate AI models against governance criteria before production.

### 3.1 Gate Types

| Gate | What It Checks | Trigger |
|------|---------------|---------|
| Policy compliance | Is this model on the approved list? Does it comply with all active policies? | Pre-deploy webhook |
| Cost projection | Estimated monthly cost based on projected usage vs budget remaining | Pre-deploy webhook |
| Performance baseline | Latency, error rate, cost-per-query against defined SLOs | Post-deploy canary |
| Risk classification | Auto-classify risk tier; block if high-risk without explicit approval | Pre-deploy webhook |

### 3.2 Gate Evaluation API

**Endpoint:** `POST /api/v1/gates/evaluate`

**Request:**
```json
{
  "model": "claude-sonnet-4-20250514",
  "provider": "anthropic",
  "project": "chatbot-v2",
  "team_id": "team-uuid",
  "estimated_monthly_requests": 50000,
  "deployment_env": "production",
  "requester": "deploy-pipeline"
}
```

**Response:**
```json
{
  "decision": "block",
  "gates": [
    { "gate": "policy_compliance", "result": "pass", "details": "Model is on approved list" },
    { "gate": "cost_projection", "result": "warn", "details": "Projected spend $4,200 — 84% of team budget" },
    { "gate": "risk_classification", "result": "block", "details": "High-risk (consumer-facing PII) — requires explicit approval" }
  ],
  "overall": "block",
  "block_reason": "High-risk classification requires governance approval before production deployment"
}
```

### 3.3 CI/CD Integrations

**GitHub Actions:**
```yaml
- name: BurnLens governance gate
  uses: burnlens/governance-gate-action@v1
  with:
    burnlens_api_key: ${{ secrets.BURNLENS_KEY }}
    model: claude-sonnet-4-20250514
    provider: anthropic
    project: chatbot-v2
    fail_on: block  # or warn
```

**GitLab CI:**
```yaml
governance_gate:
  stage: pre-deploy
  image: burnlens/gate-cli:latest
  script:
    - burnlens-gate evaluate --model $AI_MODEL --provider $AI_PROVIDER --project $PROJECT
  allow_failure: false
```

**Generic webhook:**
```bash
curl -X POST https://api.burnlens.app/api/v1/gates/evaluate \
  -H "Authorization: Bearer $BURNLENS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-sonnet-4-20250514","provider":"anthropic","project":"chatbot-v2"}'
```

### 3.4 Gate Data Model — `gate_evaluations`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `model_name` | VARCHAR | Model being evaluated |
| `provider` | ENUM | Provider |
| `project_id` | FK | Project context |
| `team_id` | FK | Team context |
| `gates_result` | JSONB | Per-gate results |
| `overall_decision` | ENUM | `pass`, `warn`, `block` |
| `triggered_by` | VARCHAR | `github_action`, `gitlab_ci`, `api`, `manual` |
| `evaluated_at` | TIMESTAMP | When evaluated |

---

## 4. Data Sensitivity Tagging

Auto-detect and flag AI endpoints that process sensitive data. Privacy-preserving approach.

### 4.1 Detection Methods

| Method | How It Works | Data Types Detected |
|--------|-------------|-------------------|
| Presidio integration | Microsoft Presidio library scans request payloads (opt-in) for PII patterns | Names, emails, SSN, phone, credit card, addresses |
| Header analysis | Check request headers for content-type indicators of structured data | Financial data (JSON schemas), health data (FHIR) |
| Endpoint classification | Tag based on what service calls the AI (CRM = customer data, EHR = health data) | Inferred from calling service metadata |
| Manual tagging | Users tag assets with sensitivity labels through UI | Any custom sensitivity category |

### 4.2 Privacy Architecture

- Presidio runs **LOCALLY** within BurnLens deployment — no data sent to external services
- Payload scanning is **OPT-IN only** — disabled by default, requires explicit enablement per team
- BurnLens **NEVER stores raw payloads** — only stores classification results (e.g., `contains_pii: true, types: [email, name]`)
- All scanning results are stored as aggregate metadata, not individual request records

### 4.3 Sensitivity Data Model — `sensitivity_tags`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `asset_id` | FK | AI asset being tagged |
| `detection_method` | ENUM | `presidio`, `header_analysis`, `endpoint_classification`, `manual` |
| `sensitivity_types` | JSONB | `["pii", "financial", "health"]` |
| `confidence` | DECIMAL(3,2) | Detection confidence (0.0–1.0) |
| `sample_count` | INTEGER | Number of requests sampled for this classification |
| `last_scanned_at` | TIMESTAMP | When last detection ran |
| `tagged_by` | FK (nullable) | User if manual, null if auto |

---

## 5. Multi-Tenant Governance

Organization-level policies cascading to teams with controlled overrides.

### 5.1 RBAC Model

| Role | Permissions | Scope |
|------|------------|-------|
| Org Admin | Create/edit org-wide policies, view all teams, manage RBAC, export audit trails | Organization |
| Governance Lead | Create/edit policies within assigned scope, view compliance reports, approve models | Org or Team |
| Team Lead | View team assets, manage team-level overrides (within org constraints), approve team requests | Team |
| Member | View own team's assets and policies, submit model requests, view own violations | Team |
| Auditor (read-only) | View all assets, policies, reports, and audit trails. Cannot modify anything. | Organization |

### 5.2 RBAC Data Model — `user_roles`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `user_id` | FK | User |
| `role` | ENUM | `org_admin`, `governance_lead`, `team_lead`, `member`, `auditor` |
| `scope_type` | ENUM | `org`, `team` |
| `scope_id` | UUID | Org or team ID |
| `granted_by` | FK | Who assigned this role |
| `granted_at` | TIMESTAMP | When assigned |

### 5.3 Policy Cascade Rules

1. Org-level policies apply to **ALL teams** unless explicitly exempted
2. Team-level policies can **ADD** restrictions but cannot **RELAX** org-level policies
3. If org policy blocks a model and team policy allows it, **org policy wins**
4. Exemptions require Org Admin approval and are logged in audit trail

### 5.4 Exemption Data Model — `policy_exemptions`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `policy_id` | FK | Org-level policy being exempted |
| `team_id` | FK | Team receiving exemption |
| `reason` | TEXT | Justification |
| `approved_by` | FK | Org Admin who approved |
| `expires_at` | TIMESTAMP (nullable) | Exemption expiry (null = permanent) |
| `created_at` | TIMESTAMP | When created |

---

## 6. Framework Alignment

Self-assessment checklists aligned to major AI governance frameworks. NOT automated compliance — guided evaluation with evidence linking.

### 6.1 Supported Frameworks

| Framework | Coverage | BurnLens Evidence Mapping |
|-----------|---------|--------------------------|
| NIST AI RMF | Govern, Map, Measure, Manage functions | Asset inventory → Map, Policies → Govern, Scorecard → Measure, Violations → Manage |
| ISO/IEC 42001 | AI management system requirements | Risk assessment → Clause 6, Monitoring → Clause 9, Improvement → Clause 10 |
| EU AI Act (lite) | Risk classification only (not full compliance) | Risk tier mapping, inventory registration, human oversight documentation |

### 6.2 Checklist Data Model — `framework_checklists`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `framework` | ENUM | `nist_ai_rmf`, `iso_42001`, `eu_ai_act_lite` |
| `category` | VARCHAR | Framework category (e.g., "Govern", "Clause 6") |
| `subcategory` | VARCHAR | Subcategory |
| `item_text` | TEXT | What the framework requires |
| `status` | ENUM | `not_started`, `in_progress`, `complete`, `not_applicable` |
| `evidence_links` | JSONB | Links to BurnLens reports, policies, or assets |
| `notes` | TEXT | Assessor comments |
| `assessed_by` | FK (nullable) | User who last updated |
| `assessed_at` | TIMESTAMP (nullable) | When last updated |

### 6.3 Checklist Snapshots — `framework_snapshots`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `framework` | ENUM | Framework |
| `snapshot_data` | JSONB | Full checklist state at snapshot time |
| `completion_pct` | DECIMAL(5,2) | % of items marked complete |
| `snapshot_date` | DATE | Quarterly snapshot date |

---

## 7. Public Governance API

REST API for integrating BurnLens governance data with external tools.

### 7.1 Design Principles

- **Read-heavy:** Most external consumers pull data, not push
- **Webhook events:** Real-time push for key governance events
- **API key auth:** Separate governance API keys with scope-limited permissions
- **Rate limiting:** 1000 requests/hour per API key (configurable for enterprise)
- **Versioned:** `/api/v1/governance/*` namespace

### 7.2 Governance API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/governance/assets` | External-facing asset inventory |
| `GET` | `/api/v1/governance/policies` | Active policies summary |
| `GET` | `/api/v1/governance/scorecard` | Current governance scorecard |
| `GET` | `/api/v1/governance/violations` | Recent violations |
| `GET` | `/api/v1/governance/risk-summary` | Risk distribution across assets |
| `POST` | `/api/v1/governance/webhooks` | Register webhook endpoint |
| `GET` | `/api/v1/governance/webhooks` | List registered webhooks |
| `DELETE` | `/api/v1/governance/webhooks/{id}` | Remove webhook |

### 7.3 Webhook Events

| Event | Payload | Use Case |
|-------|---------|----------|
| `asset.discovered` | Asset details + provider + status | Feed into CMDB or asset management |
| `policy.violated` | Policy + asset + violation details | Create ticket in ServiceNow/Jira |
| `approval.requested` | Request details + requester | Route to external approval system |
| `approval.decided` | Decision + reviewer + reason | Update external records |
| `risk.changed` | Asset + old risk + new risk | Trigger review in GRC platform |
| `report.generated` | Report type + download URL | Auto-distribute to stakeholders |
| `gate.evaluated` | Gate results + decision | Log in deployment tracking system |

### 7.4 Webhook Delivery

- **Retry policy:** 3 attempts with exponential backoff (1s, 10s, 60s)
- **Signature:** HMAC-SHA256 signature in `X-BurnLens-Signature` header for verification
- **Timeout:** 10 second timeout per delivery attempt
- **Dead letter:** Failed deliveries after 3 attempts logged in `webhook_failures` table

### 7.5 Webhook Data Model — `webhook_registrations`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `url` | TEXT | Delivery URL |
| `events` | JSONB | List of subscribed event types |
| `secret` | VARCHAR | Shared secret for HMAC signing |
| `active` | BOOLEAN | Toggle on/off |
| `created_by` | FK | User who registered |
| `created_at` | TIMESTAMP | When registered |

---

## 8. Technical Implementation

### 8.1 Tech Stack Additions

| Component | Technology | Notes |
|-----------|-----------|-------|
| PII detection | Microsoft Presidio | Python library, runs locally |
| CI/CD gates | FastAPI endpoint + GitHub Action + GitLab template | Custom action published to marketplace |
| RBAC | Custom middleware on FastAPI | Role + scope check on every request |
| Webhook delivery | Celery async tasks | Reliable delivery with retries |
| Framework checklists | PostgreSQL + seed data | Pre-populated NIST + ISO items |

### 8.2 File Structure (New Files)

```
app/
  models/
    user_role.py              # RBAC role assignments
    policy_exemption.py       # Org policy exemptions for teams
    gate_evaluation.py        # CI/CD gate evaluation records
    sensitivity_tag.py        # Data sensitivity classifications
    framework_checklist.py    # Framework checklist items
    framework_snapshot.py     # Quarterly checklist snapshots
    webhook_registration.py   # Webhook config
    webhook_failure.py        # Failed delivery log
  routers/
    gates.py                  # POST /api/v1/gates/evaluate
    sensitivity.py            # Sensitivity tagging endpoints
    roles.py                  # RBAC management endpoints
    frameworks.py             # Checklist CRUD + snapshots
    governance_api.py         # Public /api/v1/governance/* endpoints
    webhooks.py               # Webhook registration + management
  services/
    gate_evaluator.py         # CI/CD gate evaluation logic
    sensitivity_scanner.py    # Presidio integration + classification
    rbac_service.py           # Role/permission checking
    policy_cascade.py         # Org → team policy cascade logic
    framework_service.py      # Checklist management + evidence linking
    webhook_delivery.py       # Async webhook delivery with retries
  middleware/
    rbac_middleware.py         # Request-level permission enforcement
  cli/
    burnlens-gate/            # CLI tool for CI/CD integration
      main.py
      Dockerfile
  github-action/
    action.yml                # GitHub Action definition
    entrypoint.sh
  seed/
    nist_ai_rmf_checklist.json    # NIST AI RMF checklist items
    iso_42001_checklist.json      # ISO 42001 checklist items
    eu_ai_act_lite_checklist.json # EU AI Act risk classification items
frontend/
  src/pages/
    Gates.tsx                 # Gate evaluation results page
    Sensitivity.tsx           # Data sensitivity dashboard
    Roles.tsx                 # RBAC management page
    Frameworks.tsx            # Framework checklist page
    GovernanceAPI.tsx          # API key + webhook management
  src/components/platform/
    GateResultCard.tsx        # Individual gate result display
    SensitivityBadge.tsx      # PII/sensitivity indicator
    RoleManager.tsx           # Role assignment UI
    ChecklistProgress.tsx     # Framework completion progress
    WebhookConfig.tsx         # Webhook registration form
```

---

## 9. Implementation Plan (10 Weeks)

| Week | Focus | Deliverables | Dependencies |
|------|-------|-------------|--------------|
| 1 | Multi-tenant RBAC | Role model, permission system, policy cascade logic, middleware | Phase 3 complete |
| 2 | CI/CD gates | Gate evaluation endpoint, GitHub Action, GitLab template | Phase 2 policy engine |
| 3 | Data sensitivity tagging | Presidio integration, opt-in scanning, sensitivity metadata storage | Week 1 RBAC |
| 4–5 | Framework checklists | NIST + ISO + EU AI Act checklists, evidence linking, snapshot system | Phase 3 reports |
| 6–7 | Public API + webhooks | Governance API namespace, webhook delivery system, API key management | Weeks 1–5 |
| 8–9 | Dashboard upgrades | RBAC-aware UI, gate results page, sensitivity dashboard, framework progress | All APIs |
| 10 | Testing + deploy | RBAC permission tests, gate integration tests, webhook delivery tests, production deploy | All prior |

### 9.1 Testing Requirements

- **RBAC:** Verify every endpoint respects role permissions (member can't access admin routes)
- **Policy cascade:** Org blocks model → team allows → verify org wins
- **CI/CD gates:** End-to-end: GitHub Action → evaluate → pass/block decision returned
- **Sensitivity:** Presidio detects PII in sample payload → tag created → dashboard shows it
- **Webhooks:** Register → event fires → delivery attempted → retry on failure → dead letter on 3x fail
- **Frameworks:** Seed checklist → assess items → evidence link → snapshot → verify accuracy

### 9.2 Pricing

| Tier | Price | Includes |
|------|-------|----------|
| Enterprise | $399/mo | Everything from Business + multi-tenant RBAC (up to 10 teams), CI/CD gates (up to 3 pipelines), data sensitivity tagging, NIST AI RMF checklist |
| Platform | $999/mo | Unlimited teams, unlimited pipelines, all framework checklists, public API access, webhook integrations, custom report branding, dedicated support, 1-year audit retention |

### 9.3 What Happens If Phase 4 Is Not Built

If go/no-go criteria are not met, BurnLens continues as an **AI cost optimization platform with governance features** (Phases 1–3) as differentiation. The governance features still provide value as a retention mechanism and upsell driver. The product positioning stays as "know what AI you're spending on and keep it under control" rather than "full AI governance platform."

This is a perfectly valid outcome — the market will tell you which direction to lean.
