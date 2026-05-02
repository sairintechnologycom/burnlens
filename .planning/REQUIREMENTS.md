# Requirements — v1.2 Account Security & Notifications

**Milestone:** v1.2
**Goal:** Close the auth-UX gaps and add server-side alerting so cloud users can recover accounts, verify email ownership, and get notified when spend crosses thresholds — without needing the local proxy running.
**Status:** Active
**Last updated:** 2026-04-30

---

## Auth — Password Reset

- [ ] **AUTH-01**: User can request a password reset via email (endpoint always returns 200 — no user enumeration)
- [ ] **AUTH-02**: User can set a new password via a time-limited, single-use reset token link
- [ ] **AUTH-03**: Password reset request endpoint is rate-limited (reuses existing `rate_limit.py`)

## Auth — Email Verification

- [ ] **AUTH-04**: New signups automatically trigger an email verification email
- [ ] **AUTH-05**: User can confirm their email ownership via a verification token link
- [ ] **AUTH-06**: Unverified users see a persistent dashboard banner prompting verification (soft-gate — no hard block in MVP)
- [ ] **AUTH-07**: Existing users (pre-v1.2, `email_verified_at = NULL`) are grandfathered as verified automatically — no action required

## Email — Transactional System

- [ ] **EMAIL-01**: User receives a welcome email on successful signup
- [ ] **EMAIL-02**: User receives a password-changed confirmation email after completing a reset
- [ ] **EMAIL-03**: User receives a payment receipt email after a successful Paddle payment (wired into existing `payment_succeeded` webhook handler)
- [ ] **EMAIL-04**: Transactional system supports adding new templates via a typed template registry (extends existing `burnlens_cloud/email.py` beyond invitation-only)

## Alert — Schema & Seeding

- [x] **ALERT-01**: Cloud plan workspaces have default budget alert rules auto-seeded at 80% and 100% of their plan's monthly allowance
- [x] **ALERT-02**: Alert events table records a deduplication + audit log of every alert that fired (what rule, when, to whom)

## Alert — Cron & Dispatch

- [ ] **ALERT-03**: An hourly Railway cron job evaluates all active alert rules against per-workspace spend
- [ ] **ALERT-04**: Triggered alerts are deduplicated — the same rule does not re-notify within a 24-hour window
- [ ] **ALERT-05**: Alert evaluation failures are logged but never block the cron (fail-open)
- [ ] **ALERT-06**: Org owner receives an email notification (via SendGrid) when a budget threshold is crossed
- [ ] **ALERT-07**: Org owner can optionally configure a per-workspace Slack webhook to receive threshold notifications

## Alert — Management UI

- [ ] **ALERT-08**: Org owner can view all alert rules for their workspace on the `/alerts` page
- [ ] **ALERT-09**: Org owner can enable/disable a rule, edit its threshold, and manage notification email recipients

---

## Future Requirements (deferred)

- Hard-gate email-unverified users from billing changes — deferred to v1.3 (MVP is soft-gate/banner only)
- Spike-detection alert type (z-score or percentage jump) — deferred; MVP is fixed budget thresholds only
- SMS / PagerDuty / mobile push notifications — not in scope for v1.2
- SSO / MFA — not in scope for v1.2
- Usage-based overage billing — v1.3+

## Out of Scope

- SSO, MFA, SMS, mobile push — future milestone
- Annual plans, prepaid credits — v1.3+
- Policy enforcement or blocking of proxied LLM traffic — local proxy stays unmetered (free forever)
- Request/response payload logging — privacy/security concern

---

## Traceability

| REQ-ID | Phase | Phase Name |
|--------|-------|------------|
| AUTH-01 | 11 | Auth Essentials |
| AUTH-02 | 11 | Auth Essentials |
| AUTH-03 | 11 | Auth Essentials |
| AUTH-04 | 11 | Auth Essentials |
| AUTH-05 | 11 | Auth Essentials |
| AUTH-06 | 11 | Auth Essentials |
| AUTH-07 | 11 | Auth Essentials |
| EMAIL-01 | 11 | Auth Essentials |
| EMAIL-02 | 11 | Auth Essentials |
| EMAIL-03 | 11 | Auth Essentials |
| EMAIL-04 | 11 | Auth Essentials |
| ALERT-01 | 12 | Cloud Alert Engine |
| ALERT-02 | 12 | Cloud Alert Engine |
| ALERT-03 | 12 | Cloud Alert Engine |
| ALERT-04 | 12 | Cloud Alert Engine |
| ALERT-05 | 12 | Cloud Alert Engine |
| ALERT-06 | 12 | Cloud Alert Engine |
| ALERT-07 | 12 | Cloud Alert Engine |
| ALERT-08 | 13 | Alert Management UI |
| ALERT-09 | 13 | Alert Management UI |
