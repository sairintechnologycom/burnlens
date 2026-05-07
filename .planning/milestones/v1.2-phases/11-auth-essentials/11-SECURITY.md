---
phase: 11
slug: auth-essentials
status: verified
threats_open: 0
asvs_level: 1
created: 2026-05-02
---

# Phase 11 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Frontend → Railway API | Auth requests (login, signup, reset, verify) over HTTPS | Credentials, JWT tokens, reset tokens |
| Railway API → PostgreSQL | auth_tokens table reads/writes | Token hashes (not raw tokens), user IDs, expiry timestamps |
| Railway API → SendGrid | Outbound transactional email | Reset token links (HTTPS URLs), workspace name, recipient email (PII) |
| Paddle → Railway API webhook | Incoming transaction.completed events | Payment amounts, subscription IDs, workspace custom_data |
| Railway API → Frontend (JWT) | JWT returned on login/signup | email_verified boolean claim, user_id, workspace_id |

---

## Threat Register

| Threat ID | Severity | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|----------|-----------|-------------|------------|--------|
| T11-01 | HIGH | Elevation of Privilege | auth_tokens schema | mitigate | `token_hash TEXT NOT NULL UNIQUE` — DB-level duplicate rejection; `secrets.token_urlsafe(32)` → 256-bit entropy | closed |
| T11-02 | HIGH | Elevation of Privilege | auth_tokens schema | mitigate | `expires_at TIMESTAMPTZ NOT NULL` — all token queries include `AND expires_at > now()` | closed |
| T11-03 | LOW | Information Disclosure | auth_tokens schema | mitigate | `ON DELETE CASCADE` — tokens auto-removed when user deleted | closed |
| T11-04 | LOW | Tampering | database.py migration DDL | mitigate | DDL uses `CREATE TABLE IF NOT EXISTS` literals — no user input in schema statements | closed |
| T11-05 | HIGH | Tampering | email.py template rendering | mitigate | `str.replace("{{var}}", value)` only — no dynamic code execution, no f-strings with untrusted input; values from DB or backend-generated URLs | closed |
| T11-06 | HIGH | Spoofing | email.py recipient / subject | mitigate | `recipient_email` from DB (encrypted + validated at signup); `subject` is a literal constant in TemplateSpec — never contains user input | closed |
| T11-07 | MEDIUM | Information Disclosure | email.py SendGrid key | mitigate | `settings.sendgrid_api_key` never appears in log lines; only `recipient_email` logged in exception paths | closed |
| T11-08 | LOW | Repudiation | email.py fail-open | accept | Accepted per CONTEXT.md D-03; warning logged when SendGrid key missing; `/auth/resend-verification` endpoint provides recovery path | closed |
| T11-09 | LOW | Tampering | HTML email templates | mitigate | Templates contain only static HTML + safe substituted values; `workspace_name` from DB is not attacker-controlled in email client context | closed |
| T11-10 | HIGH | Elevation of Privilege | POST /auth/reset-password | mitigate | Rate limit: 3 req / 15 min in `DEFAULT_RULES`; 256-bit token entropy | closed |
| T11-11 | MEDIUM | Elevation of Privilege | JWT email_verified claim | mitigate | Grandfathering logic: `NULL email_verified_at + no pending token → email_verified=True`; old users never incorrectly blocked | closed |
| T11-12 | LOW | Tampering | JWT token | mitigate | JWT signed with `settings.jwt_secret`; tampered payload invalidates signature | closed |
| T11-13 | HIGH | Information Disclosure | POST /auth/reset-password | mitigate | Always returns HTTP 200 with identical body regardless of email existence — no account enumeration | closed |
| T11-14 | HIGH | Elevation of Privilege | token claim (reset + verify) | mitigate | Atomic `UPDATE … SET used_at = now() WHERE … AND used_at IS NULL AND expires_at > now()` with rowcount check — replay returns 400 | closed |
| T11-15 | HIGH | Elevation of Privilege | token claim WHERE clause | mitigate | `expires_at > now()` enforced at DB level in the UPDATE WHERE clause — expired tokens unconditionally rejected | closed |
| T11-16 | HIGH | Elevation of Privilege | token entropy / rate limit | mitigate | `secrets.token_urlsafe(32)` = 256-bit entropy; 3/15min rate limit; 1h reset / 24h verify expiry | closed |
| T11-17 | HIGH | Information Disclosure | auth.py logging | mitigate | bcrypt hash never logged; `user_id` (not email) appears in log lines | closed |
| T11-18 | MEDIUM | Elevation of Privilege | POST /auth/reset-password/confirm | mitigate | 8–128 character validation before bcrypt hash; `gensalt()` ensures per-password salt | closed |
| T11-19 | LOW | Tampering | POST auth endpoints (CSRF) | accept | API-only endpoints; no browser form POST from cross-origin possible without CORS allow; rate limiting reduces attack surface | closed |
| T11-20 | HIGH | Spoofing | POST /webhook/paddle (transaction.completed) | transfer | Paddle webhook signature verification is pre-existing (Phase 7 billing.py) — handler only reached after signature passes | closed |
| T11-21 | MEDIUM | Information Disclosure | billing.py webhook handler logging | mitigate | `recipient_email` never logged; only `workspace_row["id"]` appears in log lines | closed |
| T11-22 | LOW | Tampering | payment receipt email amount | mitigate | `amount_str` is display-only in receipt — no billing action triggered; computed from Paddle-verified event data | closed |
| T11-23 | LOW | Denial of Service | billing.py webhook handler exceptions | mitigate | Fail-open pattern: all exception paths `return` early without re-raising; handler never blocks Paddle's 200 | closed |
| T11-24 | LOW | Tampering | localStorage `burnlens_email_verified` (auth state) | accept | Writing `emailVerified=true` only hides the UI verification banner — no privilege escalation; `email_verified_at` column in PostgreSQL is authoritative | closed |
| T11-25 | LOW | Spoofing | BillingStatusBanner (grandfathered users) | mitigate | `null → true` fallback in hydration: old users without stored value treated as verified, banner suppressed | closed |
| T11-26 | MEDIUM | Information Disclosure | /reset-password URL query param | mitigate | Token is single-use (atomic UPDATE claim on submit); replaying from browser history returns 400; 1h expiry limits window | closed |
| T11-27 | MEDIUM | Tampering | /reset-password + /verify-email error messages | mitigate | Error messages from `err.message` or hardcoded strings; rendered as React text nodes — never injected as raw HTML | closed |
| T11-28 | LOW | Spoofing | Auth pages (clickjacking) | transfer | Infrastructure-level `X-Frame-Options` headers apply to all Next.js pages — not introduced by this phase | closed |
| T11-29 | LOW | Tampering | localStorage `burnlens_email_verified` (frontend pages) | accept | Same as T11-24 — UI-only effect; server-side `email_verified_at` is authoritative gate | closed |
| T11-30 | LOW | Information Disclosure | GET /auth/verify-email polling | mitigate | Token claimed atomically on first successful request; subsequent requests return 400 — cannot probe token validity repeatedly | closed |

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-11-01 | T11-08 | Fail-open on missing SendGrid key silently drops verification emails. Accepted per CONTEXT.md D-03 — availability over delivery guarantee. Recovery path via `/auth/resend-verification`. | Bhushan | 2026-05-02 |
| AR-11-02 | T11-19 | CSRF surface on state-changing POST endpoints. API-only; no cross-origin browser form POST vector without CORS allow. Rate limiting reduces attack surface. Acceptable at ASVS L1. | Bhushan | 2026-05-02 |
| AR-11-03 | T11-24, T11-29 | `burnlens_email_verified` localStorage tamper. Attacker can only hide the UI verification nudge banner — no backend privilege change. Server-side `email_verified_at` is authoritative for all access control. | Bhushan | 2026-05-02 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-05-02 | 30 | 30 | 0 | gsd-security-auditor (automated) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log (AR-11-01, AR-11-02, AR-11-03)
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-05-02
