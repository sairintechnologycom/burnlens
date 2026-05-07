# Requirements — v1.3 Quota Enforcement & API Key Management

## Milestone Goal

Harden the platform with real enforcement teeth — 429 hard caps at ingest, full API key lifecycle in the UI, and close the remaining v1.2 gaps (W-01, Google routing, dashboard UX).

---

## v1.3 Requirements

### QUOTA — Hard 429 Enforcement

- [ ] **QUOTA-01**: System returns 429 when workspace exceeds monthly API call quota at POST /v1/ingest
- [ ] **QUOTA-02**: System returns 429 when workspace monthly token consumption exceeds plan limit at POST /v1/ingest
- [ ] **QUOTA-03**: System returns 429 when workspace cumulative spend crosses the plan's dollar ceiling
- [ ] **QUOTA-04**: System rejects API keys belonging to seats above the plan's seat cap
- [ ] **QUOTA-05**: 429 response includes structured error body with quota dimension, current usage, and plan limit

### APIKEY — API Key Management UI

- [ ] **APIKEY-01**: Owner can list all active workspace API keys with label and last-used timestamp at `/api-keys`
- [ ] **APIKEY-02**: Owner can create a new `bl_live_xxx` key with a custom label (copy-to-clipboard on creation)
- [ ] **APIKEY-03**: Owner can revoke any key, immediately invalidating it server-side
- [ ] **APIKEY-04**: Owner can assign or edit a label/scope note on any key (e.g., "CI bot", "staging")
- [ ] **APIKEY-05**: Viewer-role users can see their own key but cannot create or revoke workspace keys

### AUTH — Bug Fix

- [ ] **AUTH-08**: Resend-verification email works for API-key users when `owner_email` is null in localStorage (reads from server-side session instead of localStorage)

### ROUTE — Google URL-Path Routing

- [ ] **ROUTE-08**: `decide_route()` applies model downgrade via URL-path rewrite for Google Generative Language API requests (extends body-rewrite-only limitation from v1.2)

### DASH — Usage Dashboard Improvements

- [ ] **DASH-01**: User can select a preset date range (7d / 30d / 90d) or custom date range for all dashboard charts
- [ ] **DASH-02**: User can view cost breakdown by model in a ranked table or chart
- [ ] **DASH-03**: User can export filtered usage data as a CSV file from the dashboard
- [ ] **DASH-04**: Dashboard displays a daily cost trend chart with model-distribution overlay

---

## Future Requirements (Deferred)

- Google URL-path routing for multi-region endpoints (follow-on to ROUTE-08)
- Usage-based overage billing (pay-as-you-go) — v1.4+
- Annual plans and prepaid credits — v1.4+
- Self-serve plan editing for end users (admin-only in v1.1) — v1.4+
- Compliance reporting / regulatory framework mapping — future milestone

---

## Out of Scope (v1.3)

| Feature | Reason |
|---------|--------|
| Policy enforcement / blocking of proxied LLM traffic | Local proxy stays unmetered (free forever) |
| Request/response payload logging | Privacy/security concern — metadata only |
| Agent-based deep inspection of payloads | Metadata only architecture |
| OSS proxy PyPI release (0.2.x) | Tracked separately in ROADMAP-OSS.md |
| Custom/negotiated enterprise contracts | Handled off-platform |

---

## Traceability

| REQ-ID | Phase | Status |
|--------|-------|--------|
| QUOTA-01 | Phase 15 | Pending |
| QUOTA-02 | Phase 15 | Pending |
| QUOTA-03 | Phase 15 | Pending |
| QUOTA-04 | Phase 15 | Pending |
| QUOTA-05 | Phase 15 | Pending |
| APIKEY-01 | Phase 16 | Pending |
| APIKEY-02 | Phase 16 | Pending |
| APIKEY-03 | Phase 16 | Pending |
| APIKEY-04 | Phase 16 | Pending |
| APIKEY-05 | Phase 16 | Pending |
| AUTH-08 | Phase 16 | Pending |
| ROUTE-08 | Phase 17 | Pending |
| DASH-01 | Phase 18 | Pending |
| DASH-02 | Phase 18 | Pending |
| DASH-03 | Phase 18 | Pending |
| DASH-04 | Phase 18 | Pending |

---

*Last updated: 2026-05-07 — v1.3 roadmap created, phase assignments filled*
