# Phase 11: Auth Essentials - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-30
**Phase:** 11-auth-essentials
**Areas discussed:** Token storage, SendGrid delivery mode, Frontend reset/verify routes, Payment receipt trigger

---

## Token Storage

### Where should reset/verify tokens live?

| Option | Description | Selected |
|--------|-------------|----------|
| New auth_tokens table | Single table (id, user_id, type, token_hash, expires_at, used_at). Auditable, GDPR-friendly, supports multiple pending tokens. Follows api_keys table precedent. | ✓ |
| Columns on users table | ALTER TABLE IF EXISTS pattern — reset_token_hash, reset_token_expires_at, verification_token_hash, verification_token_expires_at. Simpler, no new table. | |
| You decide | Claude picks. | |

**User's choice:** New auth_tokens table
**Notes:** Clean separation of concerns preferred.

### Token expiry windows?

| Option | Description | Selected |
|--------|-------------|----------|
| 1h reset / 24h verify | Industry standard. Short for security-sensitive reset; longer for verify (user may check later). | ✓ |
| 24h both | Simpler, consistent. Slight security trade-off for reset tokens. | |
| You decide | Claude picks. | |

**User's choice:** 1h reset / 24h verify

---

## SendGrid Delivery Mode

### How should Phase 11 integrate with SendGrid?

| Option | Description | Selected |
|--------|-------------|----------|
| SMTP relay — keep smtplib | Point existing smtplib at smtp.sendgrid.net:587. Zero code change to transport. Env vars only. | ✓ |
| SendGrid HTTP API | Add `sendgrid` Python package. Gains delivery tracking. Adds a dependency. | |

**User's choice:** SMTP relay — keep smtplib
**Notes:** Minimize changes to the transport layer.

### Sender address?

| Option | Description | Selected |
|--------|-------------|----------|
| noreply@burnlens.app | Standard transactional sender. No reply expected. | ✓ |
| hello@burnlens.app or support@burnlens.app | Friendlier, implies users can reply. Requires reply inbox. | |

**User's choice:** noreply@burnlens.app

---

## Frontend Reset/Verify Routes

### Where do reset/verify links land?

| Option | Description | Selected |
|--------|-------------|----------|
| New Next.js pages | /reset-password and /verify-email pages in frontend. Consistent UI. 2 new pages. | ✓ |
| Railway API-only | Links go to Railway endpoints directly. No new frontend pages. Raw API output UX. | |

**User's choice:** New Next.js pages

### URL paths?

| Option | Description | Selected |
|--------|-------------|----------|
| /reset-password and /verify-email | Top-level routes matching existing flat structure. | ✓ |
| /auth/reset-password and /auth/verify-email | Grouped under /auth/ for future namespacing. | |

**User's choice:** /reset-password and /verify-email (top-level, flat)

### Where does "Forgot password?" trigger live?

| Option | Description | Selected |
|--------|-------------|----------|
| On the existing /setup page | Current auth entry point. Add link there. | ✓ |
| New /forgot-password page | Separate page. Adds a third new page to Phase 11 scope. | |
| You decide | Claude determines placement. | |

**User's choice:** On the existing /setup page

---

## Payment Receipt Trigger

### What event triggers the receipt email?

| Option | Description | Selected |
|--------|-------------|----------|
| transaction.completed — add handler | Correct Paddle "payment succeeded" event. Fires on initial + renewals. Closes PDL-02 debt. | ✓ |
| subscription.activated — use existing | Fires only on initial activation. Simpler but misses renewals. | |

**User's choice:** transaction.completed — add the handler
**Notes:** Explicitly noted this closes the PDL-02 gap from v1.1.

---

## Claude's Discretion

- Token format: `secrets.token_urlsafe(32)` + SHA-256 hash (same as api_key_hash pattern)
- Typed `TemplateSpec` registry design in email.py
- Auth-token cleanup appended to existing retention_prune_task
- Verification banner: extend BillingStatusBanner.tsx with emailVerified session field
- Rate limit rule for reset endpoint: `/auth/reset` at 3 req / 15 min per IP

## Deferred Ideas

None — discussion stayed within phase scope.
