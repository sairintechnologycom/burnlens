---
phase: 11
slug: auth-essentials
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-02
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for Auth Essentials.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio (backend); Playwright (frontend E2E) |
| **Config file** | `pyproject.toml` (root); `frontend/playwright.config.ts` |
| **Quick run command** | `python -m pytest tests/test_phase11_auth.py -v` |
| **Full suite command** | `python -m pytest tests/ -v` |
| **Estimated runtime** | ~2 seconds (backend unit); ~30 seconds (E2E with live server) |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_phase11_auth.py -v`
- **After every plan wave:** Run `python -m pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 11-01-01 | 01 | 1 | AUTH-07 | T-01 / token collision | auth_tokens DDL idempotent; NOT NULL UNIQUE on token_hash | static | `pytest tests/test_phase11_auth.py -k TestA1` | ✅ | ✅ green |
| 11-02-01 | 02 | 1 | EMAIL-01 | T-02 / fail-open | send_welcome_email logs warning + returns when no SendGrid key | unit | `pytest tests/test_phase11_auth.py -k TestA2` | ✅ | ✅ green |
| 11-02-02 | 02 | 1 | EMAIL-02 | T-02 / fail-open | send_verify_email fail-open; background task spawned when key set | unit | `pytest tests/test_phase11_auth.py -k TestA2` | ✅ | ✅ green |
| 11-02-03 | 02 | 1 | EMAIL-04 | T-02 / fail-open | send_password_changed_email fail-open | unit | `pytest tests/test_phase11_auth.py -k TestA2` | ✅ | ✅ green |
| 11-03a-01 | 03a | 2 | AUTH-05 | T-03 / JWT tamper | TokenPayload.email_verified defaults True; SignupResponse defaults False | static | `pytest tests/test_phase11_auth.py -k TestA3` | ✅ | ✅ green |
| 11-03a-02 | 03a | 2 | AUTH-05 | T-04 / brute force | /auth/reset-password in DEFAULT_RULES (3/900s) | static | `pytest tests/test_phase11_auth.py -k TestA3` | ✅ | ✅ green |
| 11-03b-01 | 03b | 2 | AUTH-01 | T-05 / enumeration | POST /auth/reset-password always HTTP 200 regardless of email existence | unit | `pytest tests/test_phase11_auth.py -k TestA4` | ✅ | ✅ green |
| 11-03b-02 | 03b | 2 | AUTH-02 | T-06 / token replay | POST /auth/reset-password/confirm: 200 on valid claim; 400 on UPDATE 0 | unit | `pytest tests/test_phase11_auth.py -k TestA5` | ✅ | ✅ green |
| 11-03b-03 | 03b | 2 | AUTH-02 | T-07 / weak password | POST /auth/reset-password/confirm: 400 on password < 8 or > 128 chars | unit | `pytest tests/test_phase11_auth.py -k TestA5` | ✅ | ✅ green |
| 11-03b-04 | 03b | 2 | AUTH-03 | T-06 / token replay | POST /auth/verify-email: 200 on valid claim; 400 on UPDATE 0 | unit | `pytest tests/test_phase11_auth.py -k TestA6` | ✅ | ✅ green |
| 11-03b-05 | 03b | 2 | AUTH-04 | T-05 / enumeration | POST /auth/resend-verification always HTTP 200 | unit | `pytest tests/test_phase11_auth.py -k TestA7` | ✅ | ✅ green |
| 11-04-01 | 04 | 2 | EMAIL-03 | T-08 / receipt spam | _handle_transaction_completed calls send_payment_receipt_email; fail-open on no workspace | unit | `pytest tests/test_phase11_auth.py -k TestA8` | ✅ | ✅ green |
| 11-05a-01 | 05a | 3 | AUTH-06 | — / N/A | "Forgot password?" inline form appears and submits to /auth/reset-password | E2E | `cd frontend && npx playwright test tests/e2e/phase11_auth.spec.ts` | ✅ | ⬜ pending (needs live server) |
| 11-05b-01 | 05b | 3 | AUTH-01/02 | T-09 / history replay | /reset-password: no token → error state; ?token= → form renders | E2E | `cd frontend && npx playwright test tests/e2e/phase11_auth.spec.ts` | ✅ | ⬜ pending (needs live server) |
| 11-05b-02 | 05b | 3 | AUTH-03/07 | — / N/A | /verify-email: no token → error; ?token= → fetch on mount | E2E | `cd frontend && npx playwright test tests/e2e/phase11_auth.spec.ts` | ✅ | ⬜ pending (needs live server) |
| 11-05b-03 | 05b | 3 | AUTH-05 | T-10 / localStorage tamper | BillingStatusBanner: shows verify banner when emailVerified=false (cloud); hidden when true | E2E | `cd frontend && npx playwright test tests/e2e/phase11_auth.spec.ts` | ✅ | ⬜ pending (needs live server) |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. No new packages installed.

- `tests/test_phase11_auth.py` — 29 tests covering AUTH-01 through AUTH-07 + EMAIL-01 through EMAIL-04
- `frontend/tests/e2e/phase11_auth.spec.ts` — 8 Playwright specs covering frontend auth flows

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Email actually delivered to inbox | EMAIL-01/02/04 | Requires live SendGrid key + real email address | Configure SENDGRID_API_KEY, run signup with a real email, verify inbox receives welcome + verify emails |
| Paddle transaction.completed fires receipt in production | EMAIL-03 | Requires live Paddle subscription + webhook delivery | Complete a Paddle test-mode subscription; check email inbox for receipt |
| Reset link redirects to correct domain | AUTH-01/02 | Requires live BURNLENS_FRONTEND_URL env var | Trigger reset from production; verify link uses burnlens.app domain |

---

## Validation Audit 2026-05-02

| Metric | Count |
|--------|-------|
| Gaps found | 11 |
| Resolved (automated) | 8 backend groups (29 tests) + 4 E2E spec blocks |
| Escalated to manual-only | 3 (external service delivery verification) |
| Total test files created | 2 |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Manual-Only entry
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 5s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-05-02
