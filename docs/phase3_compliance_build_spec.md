# BurnLens Phase 3: Compliance Reporting Lite

## Build Specification for Claude Code

**Timeline:** Q4 2026–Q1 2027 | **Duration:** 10 weeks | **Build effort:** ~8 weeks
**Depends on:** Phase 1 + Phase 2 complete

---

## 1. Phase Overview

Package discovery and guardrails data from Phases 1–2 into exportable compliance reports and governance scorecards. The goal is NOT full regulatory compliance — it is providing teams with an "evidence package" they can show their board, auditors, or compliance officers that says: "We know what AI we run, we have controls, and here is proof."

This phase is the **retention lock**. Once a compliance officer depends on BurnLens for monthly governance reports, switching costs become very high.

### Success Criteria

- Generate a complete AI Inventory Report (PDF/CSV) covering all discovered assets
- Risk classification system with 3-tier scoring based on configurable criteria
- Per-team policy adherence scorecard showing compliance percentage and trends
- Tamper-evident audit trail export for external auditor consumption
- Automated scheduled reports delivered weekly/monthly via email
- Price point: $149–$399/month

### Non-Goals

- No mapping to specific regulatory frameworks (EU AI Act articles, NIST subcategories)
- No automated regulatory compliance checking
- No legal opinion or compliance certification
- No multi-tenant governance hierarchy (Phase 4)

---

## 2. Risk Classification System

Simple, user-configurable 3-tier risk scoring. BurnLens provides sensible defaults; organizations customize criteria and weights to match their risk appetite.

### 2.1 Default Risk Criteria

| Criterion | Description | Low (1) | Medium (2) | High (3) |
|-----------|-------------|---------|------------|----------|
| Data sensitivity | What data does the AI process? | Public data only | Internal business data | PII, financial, health |
| Exposure | Who sees the AI output? | Internal tools only | B2B customers | Consumer-facing |
| Spend volume | Monthly cost of this asset | <$500/month | $500–$5,000 | >$5,000 |
| Autonomy level | Human oversight in the loop? | Human reviews all output | Human spot-checks | Fully autonomous |
| Compliance scope | Regulatory applicability | No regulations | Industry guidelines | Legal mandate |

### 2.2 Scoring Logic

- Each criterion scores 1 (low), 2 (medium), or 3 (high)
- **Overall risk = max(all criteria scores)**
- If ANY criterion is high, the asset is high-risk
- Users can override the auto-score per asset with justification

### 2.3 Risk Score Data Model — `risk_scores`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `asset_id` | FK | References `ai_assets` table |
| `criteria_scores` | JSONB | Per-criterion scores with labels and reasons |
| `overall_risk` | ENUM | `low`, `medium`, `high` |
| `override_risk` | ENUM (nullable) | Manual override value |
| `override_reason` | TEXT (nullable) | Justification for override |
| `override_by` | FK (nullable) | User who overrode |
| `scored_at` | TIMESTAMP | When auto-scored |
| `updated_at` | TIMESTAMP | Last update |

**Example `criteria_scores` JSONB:**

```json
{
  "data_sensitivity": { "value": 3, "label": "high", "reason": "Processes customer PII" },
  "exposure": { "value": 2, "label": "medium", "reason": "B2B dashboard" },
  "spend_volume": { "value": 1, "label": "low", "reason": "$320/month" },
  "autonomy_level": { "value": 2, "label": "medium", "reason": "Spot-check only" },
  "compliance_scope": { "value": 1, "label": "low", "reason": "No regulation" }
}
```

### 2.4 Risk Criteria Configuration — `risk_criteria_config`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `org_id` | FK | Organization |
| `criterion_key` | VARCHAR | `data_sensitivity`, `exposure`, etc. |
| `enabled` | BOOLEAN | Toggle criterion on/off |
| `low_description` | TEXT | What constitutes "low" for this org |
| `medium_description` | TEXT | What constitutes "medium" |
| `high_description` | TEXT | What constitutes "high" |
| `low_threshold` | JSONB (nullable) | Auto-score rules for low (for numeric criteria like spend) |
| `high_threshold` | JSONB (nullable) | Auto-score rules for high |

---

## 3. Compliance Scorecard

Per-team and org-wide scorecard showing how well the organization governs its AI usage.

### 3.1 Scorecard Metrics

| Metric | Calculation | Target |
|--------|------------|--------|
| Inventory coverage | % of AI assets with assigned owner + risk tier | >95% |
| Policy adherence | % of assets with zero unresolved violations in last 30 days | >90% |
| Shadow AI ratio | % of assets in `shadow`/unregistered status | <5% |
| Budget compliance | % of teams within budget limits | >95% |
| Violation resolution time | Median days from violation detected to resolved | <3 days |
| Approval compliance | % of new models that went through approval workflow | >80% |
| **Overall governance score** | Weighted average of all above (0–100 scale) | >80 |

### 3.2 Scorecard Data Model — `scorecard_snapshots`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `scope_type` | ENUM | `org`, `team` |
| `scope_id` | UUID | Org or team ID |
| `metrics` | JSONB | All 7 metric values + overall score |
| `snapshot_date` | DATE | Date of snapshot |
| `created_at` | TIMESTAMP | When computed |

### 3.3 Trending

- Store scorecard snapshots **weekly** via scheduled job
- Display 12-week trend line per metric on dashboard
- Show month-over-month improvement/decline indicators (↑ ↓ →)
- Teams can see their score vs org average

---

## 4. Report Types

### 4.1 AI Inventory Report

Complete catalog of all AI assets with governance metadata.

- **Contents:** All AI assets with provider, model, owner team, risk tier, status, monthly spend, request volume, first seen, last active, tags
- **Filters:** By team, risk tier, provider, status, date range
- **Summary section:** Total assets, breakdown by risk tier, top 10 by spend, new assets this period, inactive assets
- **Formats:** PDF (formatted with BurnLens branding) + CSV (raw data export)

### 4.2 Policy Adherence Report

Policy violation history and resolution status over a given period.

- **Contents:** Policy list with violation count, top violated policies, violation timeline, resolution rate, mean time to resolve
- **Per-team breakdown:** Each team's policy score, violations, and trend
- **Format:** PDF report + JSON data export

### 4.3 Governance Evidence Package

The flagship deliverable. A combined PDF for auditors or board members.

**Sections:**
1. **Executive summary** — One-page governance scorecard with overall score, key metrics, trend arrows
2. **AI inventory snapshot** — Summarized asset list with risk classification
3. **Policy framework** — List of active policies with scope and enforcement mode
4. **Violation and resolution log** — Audit trail of violations and how they were resolved
5. **Budget adherence** — Spend vs budget by team/project
6. **Appendix** — Detailed audit trail export (optional, can be separate file)

**Explicit disclaimer on page 1:** "This report provides evidence of AI governance practices. It is not a compliance certification or legal opinion."

### 4.4 Audit Trail Export

Tamper-evident export for external auditor consumption.

- **Format:** JSON Lines (`.jsonl`) with each line being a signed event
- **Signing:** HMAC-SHA256 hash chain — each event includes hash of previous event, creating tamper-evident chain
- **Content:** Discovery events + policy violations + approval decisions + configuration changes
- **Verification:** Include a verification endpoint and downloadable script that auditors can run

**Hash chain structure:**

```json
{"seq": 1, "event_type": "asset.discovered", "data": {...}, "timestamp": "...", "prev_hash": "000000", "hash": "sha256_of_this_record"}
{"seq": 2, "event_type": "policy.violated", "data": {...}, "timestamp": "...", "prev_hash": "hash_of_seq_1", "hash": "sha256_of_this_record"}
```

---

## 5. Scheduled Reports

Automated report generation and delivery on user-configured schedule.

### 5.1 Schedule Configuration — `report_schedules`

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `id` | UUID | uuid | Primary key |
| `report_type` | ENUM | `governance_package` | `inventory`, `adherence`, `evidence_package`, `audit_trail` |
| `frequency` | ENUM | `monthly` | `weekly`, `biweekly`, `monthly`, `quarterly` |
| `recipients` | JSONB | `["cto@company.com"]` | Email addresses for delivery |
| `filters` | JSONB | `{"team_id":"uuid"}` | Optional filters to scope the report |
| `next_run_at` | TIMESTAMP | 2026-12-01T08:00Z | Next scheduled generation time |
| `last_run_at` | TIMESTAMP (nullable) | 2026-11-01T08:00Z | Last successful run |
| `enabled` | BOOLEAN | true | Toggle on/off |
| `created_by` | FK | user-uuid | Who configured this schedule |

### 5.2 Generated Reports Storage — `generated_reports`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `schedule_id` | FK (nullable) | If generated from schedule (null for on-demand) |
| `report_type` | ENUM | Type of report |
| `format` | ENUM | `pdf`, `csv`, `jsonl`, `json` |
| `file_path` | TEXT | Storage path (S3-compatible) |
| `file_size_bytes` | INTEGER | File size |
| `filters_used` | JSONB | Snapshot of filters at generation time |
| `generated_at` | TIMESTAMP | When generated |
| `expires_at` | TIMESTAMP | Auto-delete after 90 days (configurable) |

---

## 6. API Specification

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/compliance/scorecard` | Current scorecard (org-wide or per-team with `?team_id=`) |
| `GET` | `/api/v1/compliance/scorecard/history` | Weekly scorecard snapshots for trending |
| `GET` | `/api/v1/risk/scores` | Risk scores for all assets. Filter by `risk_tier`. |
| `PUT` | `/api/v1/risk/scores/{asset_id}` | Override risk score with justification |
| `GET` | `/api/v1/risk/config` | Get org's risk criteria configuration |
| `PUT` | `/api/v1/risk/config` | Update risk criteria configuration |
| `POST` | `/api/v1/reports/generate` | Generate report on-demand. Body: `{type, filters, format}` |
| `GET` | `/api/v1/reports/{id}/download` | Download generated report (PDF/CSV/JSONL) |
| `GET` | `/api/v1/reports` | List previously generated reports |
| `DELETE` | `/api/v1/reports/{id}` | Delete a generated report |
| `POST` | `/api/v1/reports/schedules` | Create scheduled report configuration |
| `GET` | `/api/v1/reports/schedules` | List scheduled report configurations |
| `PUT` | `/api/v1/reports/schedules/{id}` | Update schedule config |
| `DELETE` | `/api/v1/reports/schedules/{id}` | Delete schedule |
| `GET` | `/api/v1/audit/export` | Export audit trail (JSONL with hash chain). Params: `start_date`, `end_date` |
| `GET` | `/api/v1/audit/verify` | Verify audit trail hash chain integrity |

---

## 7. Technical Implementation

### 7.1 Tech Stack Additions

| Component | Technology | Notes |
|-----------|-----------|-------|
| PDF generation | WeasyPrint | HTML→PDF with CSS styling. BurnLens branded templates. |
| CSV export | Python `csv` module | Standard library, no dependency |
| JSONL export | Python `json` module | Line-delimited JSON with HMAC chain |
| Hash chain | `hashlib` (HMAC-SHA256) | Built-in, no external dependency |
| Scheduled jobs | Celery + Celery Beat | For reliable scheduled report generation |
| Email delivery | Resend API | Already used in BurnLens for alerts |
| Report storage | S3-compatible (Railway volume or R2) | Store generated reports, 90-day retention default |

### 7.2 File Structure (New Files)

```
app/
  models/
    risk_score.py             # Risk classification model
    risk_criteria_config.py   # Org-specific risk criteria
    scorecard_snapshot.py     # Weekly scorecard snapshots
    report_schedule.py        # Scheduled report config
    generated_report.py       # Generated report metadata
  routers/
    compliance.py             # Scorecard endpoints
    risk.py                   # Risk scoring + config endpoints
    reports.py                # Generate, list, download reports
    audit.py                  # Audit trail export + verify
  services/
    risk_scorer.py            # Auto-scoring engine
    scorecard_calculator.py   # Compute 7 governance metrics
    report_generator.py       # Orchestrates report generation
    pdf_renderer.py           # WeasyPrint HTML→PDF rendering
    csv_exporter.py           # CSV data export
    audit_chain.py            # HMAC hash chain builder + verifier
    report_scheduler.py       # Celery task for scheduled reports
  templates/
    reports/
      inventory.html          # HTML template for inventory PDF
      adherence.html          # HTML template for adherence PDF
      evidence_package.html   # HTML template for governance package
      base.html               # Shared header/footer/branding
      styles.css              # Report CSS (print-optimized)
  jobs/
    scorecard_snapshot_job.py  # Weekly scorecard computation
    risk_rescore_job.py        # Nightly auto-rescore on new data
    report_generation_job.py   # Celery beat scheduled reports
    report_cleanup_job.py      # Delete expired reports
frontend/
  src/pages/
    Compliance.tsx             # Scorecard + trends page
    Reports.tsx                # Report management page
  src/components/compliance/
    ScorecardView.tsx          # Governance score display
    MetricTrend.tsx            # 12-week trend chart
    RiskMatrix.tsx             # Risk tier distribution view
    ReportGenerator.tsx        # On-demand report form
    ScheduleManager.tsx        # Schedule CRUD UI
    AuditExport.tsx            # Audit trail export UI
```

---

## 8. Implementation Plan (8 Weeks)

| Week | Focus | Deliverables | Dependencies |
|------|-------|-------------|--------------|
| 1 | Risk scoring engine | Criteria model, scoring logic, auto-score job, override API | Phase 1+2 data |
| 2 | Compliance scorecard | 7 metrics calculated, weekly snapshot job, trending storage | Phase 2 violations data |
| 3 | PDF report generator | WeasyPrint setup, inventory report template, evidence package template | Weeks 1–2 |
| 4 | Audit trail export | JSONL exporter, HMAC hash chain, verification endpoint | Phase 2 audit log |
| 5–6 | Compliance dashboard UI | Scorecard page, risk matrix, report generator UI, download management | Weeks 1–4 APIs |
| 7 | Scheduled reports | Schedule config, Celery beat jobs, email delivery via Resend | Week 3 templates |
| 8 | Testing + deploy | Report accuracy tests, hash chain verification tests, production deploy | All prior |

### 8.1 Testing Requirements

- **Risk scoring:** Verify auto-scoring logic across all 5 criteria combinations
- **Scorecard accuracy:** Cross-check metric calculations against raw data
- **PDF generation:** Visual verification of all 3 report templates with sample data
- **Hash chain:** Verify tamper detection (modify one record → chain breaks)
- **Scheduled delivery:** End-to-end: schedule → generation → email delivery → download works
- **Edge cases:** Org with zero assets, team with no policies, empty violation log

### 8.2 Pricing

| Tier | Price | Includes |
|------|-------|----------|
| Growth | $149/mo | Risk scoring, compliance scorecard, on-demand reports (5/month), audit trail export |
| Business | $399/mo | Unlimited reports, scheduled delivery, governance evidence package, custom branding on reports, extended audit retention (1 year) |
