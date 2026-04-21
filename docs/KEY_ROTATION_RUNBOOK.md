# Key Rotation Runbook

This runbook covers rotating every long-lived secret BurnLens Cloud
depends on. Follow the per-secret section; each is self-contained.

**Golden rules**

- **Two-phase rotation.** Add the new secret, run both in parallel long
  enough to catch traffic using either, then remove the old one. Never
  cut over in a single deploy.
- **Back up before you rotate.** For secrets that encrypt data at rest
  (`PII_MASTER_KEY`), a lost old key means unreadable rows. Store the
  outgoing value in the team password manager for at least 90 days after
  rotation completes.
- **Rotate, don't share.** If you suspect a secret was exposed (leaked
  commit, shared over chat, laptop compromise), rotate immediately —
  don't wait for the scheduled cycle.
- **Deploy order is Railway → app restart → verify.** Writing the new
  env var to Railway does not take effect until the process restarts.
  After setting the var, trigger a redeploy via the GitHub Action, then
  confirm with `railway logs --service burnlens-proxy`.
- **Audit.** Every rotation should be recorded with: date, actor, reason
  (scheduled / suspected-exposure / personnel-change), old-value
  fingerprint (first + last 4 chars), new-value fingerprint.

---

## Secret inventory

| Env var | What it protects | Stored where | Exposure cost |
|---|---|---|---|
| `JWT_SECRET` | Session token signatures | Railway | All logged-in sessions forgeable |
| `PII_MASTER_KEY` | HKDF root for Fernet encrypt + HMAC lookup subkeys | Railway **and** password manager backup | Every encrypted PII row becomes unreadable if lost; silent forgery possible if leaked |
| `PADDLE_WEBHOOK_SECRET` | HMAC verifies Paddle webhook payloads | Railway + Paddle dashboard | Forged subscription events could trigger billing-state flips |
| `PADDLE_API_KEY` | Server-side Paddle Billing calls | Railway + Paddle dashboard | Attacker can issue checkouts / pull customer data |
| `SENDGRID_API_KEY` | Outbound email (invitations, alerts) | Railway + SendGrid | Phishing via BurnLens-signed envelopes |
| `OTEL_ENCRYPTION_KEY` | Encrypts stored enterprise OTEL API keys (per-workspace) | Railway | Leaked customer OTEL keys |
| `bl_live_*` per-workspace API keys | Ingest authentication | User machine + DB hash | Sync-path impersonation for that workspace |

Railway is the source of truth. Azure DevOps (`origin`) is a mirror only —
never store secrets there.

---

## 1. Rotate `JWT_SECRET`

**Scope**: Cannot be hot-rotated without logging everyone out — a JWT
signed under the old key becomes invalid the moment the new key is
active. Plan a low-traffic window and communicate a "you'll be asked to
sign in again" to users.

1. Generate a new secret (≥32 chars of high entropy):
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
2. Update Railway:
   ```bash
   railway variables --service burnlens-proxy set JWT_SECRET=<new-value>
   ```
3. Redeploy via the `deploy-railway` GitHub Action, or let Railway
   rebuild on the next push.
4. Watch `railway logs --service burnlens-proxy` for fail-fast aborts —
   the app refuses to boot if `JWT_SECRET` is < 32 chars in production.
5. Verify: `curl https://api.burnlens.app/health` returns 200; open the
   frontend and confirm an existing session prompts for re-login, and
   a fresh login issues a working session cookie.
6. Old sessions fail closed (401) automatically; no cleanup needed.

**Post C-3**, the session cookie carries the JWT. After rotation, all
browsers holding the `burnlens_session` cookie will get 401 on their
next request and bounce to `/setup`. This is expected.

---

## 2. Rotate `PII_MASTER_KEY`

**Scope**: This key is the HKDF root for both the Fernet encryption
subkey (used on `*_encrypted` columns) and the HMAC subkey (used on
`*_hash` columns). Rotating it is the most consequential rotation in the
system because **losing the old key before every row has been
re-encrypted makes those rows permanently unreadable**.

Dual-key rotation is supported by the `v1:` ciphertext prefix in
`burnlens_cloud/pii_crypto.py` — the prefix version is intentionally
left at `v1` and not yet wired to swap keys. Until that machinery ships,
treat `PII_MASTER_KEY` rotation as a **full re-encrypt migration**.

### 2a. Pre-rotation (always)

1. Back up the current `PII_MASTER_KEY` to the team password manager.
   Tag the entry with the deployment date and a note that it is the
   decrypt-only key for rows written before the cutover.
2. Snapshot the DB — `pg_dump` of the `workspaces` and `users` tables
   at minimum.
3. Confirm `ENVIRONMENT=production` is set — the app refuses to start
   without a `PII_MASTER_KEY` when `ENVIRONMENT=production`.

### 2b. Planned rotation (personnel change, scheduled cycle)

1. Generate a new key:
   ```bash
   python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"
   ```
2. Write a one-shot re-encrypt script that:
   - Iterates every row in `users`, `workspaces`, and any other table
     with `*_encrypted` columns.
   - Decrypts with the old key; encrypts with the new key; updates the
     row.
   - Also recomputes every `*_hash` column because HMAC subkey derives
     from the new master.
   - Runs in batches with a transaction per batch so a crash mid-way
     leaves the DB internally consistent.
3. Deploy the script as a one-shot Railway job with BOTH the old and
   new `PII_MASTER_KEY` available as env vars (e.g. `PII_MASTER_KEY` =
   old, `PII_MASTER_KEY_NEW` = new). The script reads both, migrates,
   exits.
4. Verify row counts before and after — every row with a non-NULL
   `*_encrypted` column must still have one after the script runs.
5. Swap Railway: set `PII_MASTER_KEY` = new value. Remove
   `PII_MASTER_KEY_NEW`.
6. Redeploy the main app. It now only knows the new key.
7. Keep the old key in the password manager for 90 days in case rollback
   is needed.

### 2c. Emergency rotation (suspected key exposure)

Run 2b as written, but do NOT wait for a low-traffic window. The cost of
stale ciphertext is bounded; the cost of a leaked key is not.

If the leak was serious enough that you believe decrypted data was read,
treat every email / OAuth ID currently in `users` as compromised and
notify affected workspaces per the privacy policy.

---

## 3. Rotate `PADDLE_WEBHOOK_SECRET`

**Scope**: BurnLens verifies the `paddle-signature` header on every
webhook. Paddle signs with the current secret. During rotation, webhooks
signed with the old secret arrive alongside webhooks signed with the new
secret.

Paddle's dashboard does not support dual-secret rotation. Do this when
webhook volume is low enough that losing a handful of retries is
acceptable — Paddle retries webhooks for 3 days, so real risk window is
~seconds of in-flight requests.

1. Generate a new secret in the Paddle dashboard: *Developer Tools →
   Notifications → edit the endpoint → Rotate secret*.
2. Copy the new secret **immediately** — it is shown only once.
3. Update Railway:
   ```bash
   railway variables --service burnlens-proxy set PADDLE_WEBHOOK_SECRET=<new-value>
   ```
4. Redeploy. Watch `/billing/webhook` logs for `401` signature
   mismatches — there should be zero once the new key is active.
5. If any webhooks failed during the swap window, replay them from the
   Paddle dashboard (*Developer Tools → Notification Logs*).

---

## 4. Rotate `PADDLE_API_KEY`

1. In the Paddle dashboard, create a new API key with the same scopes as
   the current one.
2. Update Railway:
   ```bash
   railway variables --service burnlens-proxy set PADDLE_API_KEY=<new-value>
   ```
3. Redeploy. Verify by hitting `/billing/summary` for an authed
   workspace — the call should still complete.
4. In the Paddle dashboard, revoke the old key.

---

## 5. Rotate `SENDGRID_API_KEY`

1. Create a new key in the SendGrid dashboard with scope "Mail Send"
   (and nothing else).
2. Update Railway, redeploy.
3. Smoke-test by sending a team invitation to yourself and confirming
   delivery.
4. Revoke the old key in SendGrid.

---

## 6. Rotate `OTEL_ENCRYPTION_KEY`

**Scope**: This key encrypts per-workspace OTEL API keys stored in
`workspaces.otel_api_key_encrypted`. Rotation requires re-encrypting
those rows.

Same pattern as §2b: run a one-shot migration with both keys available,
then swap.

---

## 7. Rotate a compromised `bl_live_*` API key (single workspace)

Customer-initiated or incident-response.

1. Get the workspace ID. From the workspace's admin session, call
   `POST /api/v1/orgs/regenerate-key`. This issues a new `bl_live_*` and
   updates `api_key_hash` + `api_key_last4` in `workspaces`.
2. The old key stops working on the very next ingest call (hash lookup
   misses).
3. Tell the customer to update `~/.burnlens/config.yaml` on every
   machine running the proxy, or re-run `burnlens login`.

---

## Cadence

| Secret | Cadence | Trigger overrides |
|---|---|---|
| `JWT_SECRET` | Annually | Suspected exposure → immediate |
| `PII_MASTER_KEY` | Every 2 years | Suspected exposure → immediate (+ notify) |
| `PADDLE_WEBHOOK_SECRET` | Annually | Paddle advisory → immediate |
| `PADDLE_API_KEY` | Annually | Personnel change → immediate |
| `SENDGRID_API_KEY` | Annually | Personnel change → immediate |
| `OTEL_ENCRYPTION_KEY` | Every 2 years | Suspected exposure → immediate |
| `bl_live_*` customer keys | On customer request | Incident → immediate per-workspace |

Calendar the scheduled rotations and keep a RUNBOOK_AUDIT.md entry per
actual rotation. A rotation that happened but wasn't recorded is
indistinguishable from a rotation that didn't happen.
