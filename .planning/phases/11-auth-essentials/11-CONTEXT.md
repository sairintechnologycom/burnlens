# Phase 11: Auth Essentials - Context

**Gathered:** 2026-04-30
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 11 delivers password reset flow, email verification (soft-gate/banner for MVP), and a typed transactional email system — upgrading `email.py` from invitation-only to a general-purpose registry supporting welcome, password-changed, payment receipt, and verify templates via SendGrid SMTP relay.

**In scope:**
- New `auth_tokens` Postgres table for password-reset and email-verification tokens
- `POST /auth/reset-password` — request email (always 200, no user enumeration), rate-limited via existing `rate_limit.py`
- `POST /auth/reset-password/confirm` — set new password via single-use token
- `POST /auth/resend-verification` — resend verification email
- `GET /auth/verify-email?token=xxx` — confirm email ownership
- Add `email_verified_at` column to `users` table; NULL = grandfathered as verified for existing users (AUTH-07)
- New frontend pages: `/reset-password` (new-password form) and `/verify-email` (success/error) at top-level routes
- "Forgot password?" trigger added to existing `/setup` page
- Email verification soft-gate: persistent banner in dashboard for unverified users (no hard block in MVP)
- 4 new email templates: `welcome.html`, `password_changed.html`, `payment_receipt.html`, `verify_email.html`
- Typed `TemplateSpec` registry in `email.py` extending beyond invitation-only
- `transaction.completed` Paddle webhook handler (closes PDL-02 gap) → triggers payment receipt email

**Out of scope (v1.3+):**
- Hard-gating unverified users from billing changes
- SSO, MFA, SMS, mobile push
- Annual plans, prepaid credits
- Usage-based overage billing

**Non-negotiable overlay:** No compromise on security — token endpoints must be brute-force resistant, single-use, and expiry-enforced. Tiebreaker: security wins.

</domain>

<decisions>
## Implementation Decisions

### Token Storage
- **D-01:** New `auth_tokens` Postgres table: `(id UUID PK DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, type TEXT NOT NULL CHECK (type IN ('password_reset', 'email_verification')), token_hash TEXT NOT NULL UNIQUE, expires_at TIMESTAMPTZ NOT NULL, used_at TIMESTAMPTZ NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())`. Index on `(user_id, type) WHERE used_at IS NULL` for fast active-token lookups. Created via `CREATE TABLE IF NOT EXISTS` inside `init_db()` — follows the `api_keys` table precedent from Phase 9.
- **D-02:** Token expiry: **1 hour** for `password_reset` (security-sensitive), **24 hours** for `email_verification` (user may check email later). Single-use enforced atomically via `UPDATE auth_tokens SET used_at = now() WHERE token_hash = $1 AND used_at IS NULL AND expires_at > now()` — rowcount 1 = claim won, 0 = already used or expired.

### SendGrid / Email Delivery
- **D-03:** Keep existing smtplib transport — point at **SendGrid's SMTP relay** via env vars: `SMTP_HOST=smtp.sendgrid.net`, `SMTP_PORT=587`, `SMTP_USER=apikey`, `SMTP_PASSWORD=$SENDGRID_API_KEY`. Zero code change to the email.py transport layer. The `send_invitation_email` background-thread executor pattern is preserved for all new email functions.
- **D-04:** Sender address: **`noreply@burnlens.app`** for all transactional emails (welcome, verify, reset, receipt, usage warnings).
- **D-05:** 4 new HTML templates to add at `burnlens_cloud/emails/templates/`: `welcome.html`, `password_changed.html`, `payment_receipt.html`, `verify_email.html`. Follow the structure of the existing `usage_80_percent.html` / `usage_100_percent.html` templates.

### Frontend Routes
- **D-06:** Two new top-level Next.js pages following the existing flat route structure:
  - `frontend/src/app/reset-password/page.tsx` — renders new-password form, validates token via backend on submit
  - `frontend/src/app/verify-email/page.tsx` — calls backend verify endpoint on load, shows success/error state
  No `/auth/` prefix — matches existing app route structure (`/settings`, `/dashboard`, `/setup`, etc.).
- **D-07:** "Forgot password?" link/trigger added to the existing `/setup` page — the current auth entry point. The reset request flow (email input + submit) lives inline on `/setup` or as a distinct section within it.

### Payment Receipt Trigger
- **D-08:** Add `transaction.completed` webhook handler to `billing.py` dispatch (`_handle_transaction_completed()`). This is Paddle's "payment succeeded" event — fires on initial payment and every renewal charge. The new handler sends a payment receipt email via `send_payment_receipt_email()`. **Closes the PDL-02 tech debt** documented in the v1.1 retrospective. All existing handlers (`subscription.activated`, `subscription.updated`, `subscription.canceled/paused`, `transaction.payment_failed`) are unchanged.

### Claude's Discretion
- **Token format:** `secrets.token_urlsafe(32)` for generation; SHA-256 hash (`hashlib.sha256(token.encode()).hexdigest()`) before storing — identical to the `api_key_hash` pattern in `auth.py`.
- **Template registry:** Typed `TemplateSpec` dataclass (or TypedDict) in `email.py` with fields `subject: str`, `template_file: str`, `required_vars: list[str]`. Registry is a `dict[str, TemplateSpec]` mapping template names to specs — makes adding templates a one-line addition.
- **Auth-token cleanup:** Append expired-token pruning (`DELETE FROM auth_tokens WHERE expires_at < now() - interval '7 days'`) to the existing `retention_prune_task` background loop in `main.py` — no new background task needed.
- **Verification banner:** Extend `BillingStatusBanner.tsx` with an email verification state that reads `session.emailVerified` (new field from JWT/session response). Show below any billing banner. Dismiss not supported in MVP — persists until verified.
- **Rate limit rule:** Add `/auth/reset` to `DEFAULT_RULES` in `rate_limit.py`: `("/auth/reset", 3, 900)` — 3 requests per 15 minutes per IP. Satisfies AUTH-03 via existing `rate_limit.py` reuse.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` §Auth and §Email — AUTH-01–07 and EMAIL-01–04 (11 requirements). Source of truth for acceptance criteria.

### Backend Foundation — Phase 11 extends these files
- `burnlens_cloud/auth.py` — Users table structure, `verify_token()`, `require_feature()`, `get_workspace_by_api_key()` dual-read, API key cache pattern. Token format/hash approach to replicate for `auth_tokens`.
- `burnlens_cloud/email.py` — Email infrastructure: `track_email_task()`, `drain_pending_email_tasks()`, `send_usage_warning_email()` (background-thread executor pattern). Phase 11 extends this module with typed registry and 4 new send functions.
- `burnlens_cloud/rate_limit.py` — `SlidingWindowLimiter`, `RateLimitMiddleware`, `DEFAULT_RULES` tuple. AUTH-03 reuses by adding a reset-password rule.
- `burnlens_cloud/database.py` — `init_db()` with `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE IF EXISTS` migration pattern. Phase 11 adds `auth_tokens` table and `email_verified_at` column to `users` here.
- `burnlens_cloud/billing.py` — Paddle webhook dispatch. Phase 11 adds `transaction.completed` handler at the dispatch block (mirrors existing event handler structure).
- `burnlens_cloud/emails/templates/usage_80_percent.html` — Reference template for HTML structure and inline CSS style.

### Frontend Foundation — Phase 11 adds to or extends these
- `frontend/src/app/setup/page.tsx` — Existing auth entry point. Phase 11 adds "Forgot password?" trigger here.
- `frontend/src/components/BillingStatusBanner.tsx` — Existing banner component. Phase 11 extends with email verification banner state.

### v1.1 Tech Debt Context
- `.planning/phases/11-auth-essentials/../../../.planning/STATE.md` §Deferred Items — PDL-02 (transaction.completed handler missing) is resolved by D-08.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `burnlens_cloud/api_keys_api.py` — `POST /api-keys` creates a token via `secrets.token_urlsafe(32)` + hash; exact same approach for `auth_tokens` generation
- `burnlens_cloud/email.py:send_usage_warning_email()` — The canonical pattern for new `send_*_email()` functions: background-thread executor, `track_email_task()` registration, fail-open
- `burnlens_cloud/emails/templates/usage_80_percent.html` — HTML email template structure to replicate for the 4 new templates
- `frontend/src/components/BillingStatusBanner.tsx` — Extend for email verification banner (reads new `emailVerified` session field)
- `burnlens_cloud/rate_limit.py:DEFAULT_RULES` — Extend tuple with `("/auth/reset", 3, 900)` for AUTH-03

### Established Patterns
- **`init_db()` migration:** `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE IF EXISTS` — Phase 11 adds `auth_tokens` table and `email_verified_at` column to `users` via this pattern
- **Fire-and-forget email:** `asyncio.create_task(send_*(...))` + `track_email_task()` — follow for all 4 new email triggers
- **Atomic single-use claim:** `UPDATE ... SET used_at = now() WHERE ... IS NULL` pattern (see Phase 9 `notified_80_at` dedup in `ingest.py`) — Phase 11 uses for single-use token enforcement
- **Frontend flat routes:** All pages at top-level `app/` — Phase 11 adds `/reset-password` and `/verify-email` at this level
- **Webhook handler shape:** `_handle_subscription_activated(data: dict)` async pattern in `billing.py` — Phase 11 adds `_handle_transaction_completed(data: dict)` following same shape

### Integration Points
- `burnlens_cloud/auth.py:register_user()` (or equivalent signup handler) → trigger `send_welcome_email()` + `send_verify_email()` as fire-and-forget tasks (EMAIL-01, AUTH-04)
- `burnlens_cloud/billing.py` dispatch → `_handle_transaction_completed()` → `send_payment_receipt_email()` (EMAIL-03, D-08)
- `burnlens_cloud/main.py:lifespan:retention_prune_task` → append `auth_tokens` TTL cleanup
- JWT/session response → add `email_verified_at` (or boolean `email_verified`) so frontend `BillingStatusBanner.tsx` can read it without a separate API call

</code_context>

<specifics>
## Specific Ideas

- AUTH-01 endpoint MUST always return HTTP 200 with a neutral message (e.g., `{"message": "If that email exists, a reset link has been sent"}`) — no user enumeration regardless of whether the email is registered.
- AUTH-07 enforcement: the `email_verified_at IS NULL` condition on an existing user row means "verified" — the absence of a non-null timestamp is the grandfathering signal. No backfill migration, no one-time job.
- D-08 closes PDL-02: `transaction.completed` is Paddle's authoritative "payment succeeded" event. It fires for both initial checkouts and renewal charges, making it the correct trigger for payment receipts (unlike `subscription.activated` which only fires once at plan start).

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 11-auth-essentials*
*Context gathered: 2026-04-30*
