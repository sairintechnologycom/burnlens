---
phase: 07
slug: paddle-lifecycle-sync
status: verified
threats_open: 0
asvs_level: 1
created: 2026-04-19
---

# Phase 7 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

Phase 7 introduces Paddle webhook ingestion (`POST /billing/webhook`), a workspace-scoped read endpoint (`GET /billing/summary`), and three frontend surfaces that consume the resulting cache (Topbar plan pill, Settings Billing card, past_due banner). This audit verifies the 26 threats registered across Plans 01–04 against the shipped code.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Paddle → `POST /billing/webhook` | Untrusted HTTP input; authenticity via HMAC-SHA256 (`ts:raw_body`) + 300s tolerance | Subscription / transaction event envelopes (contains customer_id, subscription_id, price, status) |
| authenticated client → `GET /billing/summary` | JWT Bearer; scoped by `verify_token` dependency to caller's workspace_id | Plan, price_cents, currency, status, trial/period dates — workspace's own cache only |
| webhook handler → Postgres | Trusted; all writes via parameterised asyncpg binds | Workspace lifecycle columns + paddle_events audit row |
| browser → backend `/billing/summary` | Outbound fetch with session JWT | Same as `GET /billing/summary` above |
| URL query string → Settings page | Untrusted (`?checkout=success`); side-effect limited to a benign refresh | N/A (triggers read-only workspace-scoped fetch) |

---

## Threat Register

### Plan 01 — DDL (burnlens_cloud/database.py)

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-07-01 | Tampering | `paddle_events.payload` | mitigate | `payload JSONB NOT NULL` — `burnlens_cloud/database.py:367`; Plan 01 adds no read/mutation path, only Plan 02 writes | closed |
| T-07-02 | Repudiation | webhook event handling | mitigate | `event_id TEXT PRIMARY KEY` + `received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()` — `burnlens_cloud/database.py:364-366`; append-only (no DELETE path) | closed |
| T-07-03 | DoS (replay flood) | webhook endpoint | mitigate | `event_id` PK enables O(log n) `ON CONFLICT DO NOTHING` dedup — `burnlens_cloud/database.py:364` (PK) + `burnlens_cloud/billing.py:271` (`ON CONFLICT (event_id) DO NOTHING`) | closed |
| T-07-04 | Information Disclosure (cross-tenant on paddle_events) | `paddle_events` admin read surface | accept | No read API introduced by Plan 01 or Plan 02. Table is only touched by the webhook handler (write) and the dedup INSERT. See Accepted Risks Log. | closed |
| T-07-05 | EoP via migration | `init_db()` | mitigate | Every DDL uses `IF NOT EXISTS` / DO-block guards — `burnlens_cloud/database.py:325,331,337,343,349,362,372` | closed |

### Plan 02 — Webhook + /billing/summary (burnlens_cloud/billing.py, models.py, tests/test_billing_webhook_phase7.py)

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-07-06 | Spoofing (webhook forgery) | `paddle_webhook` | mitigate | `_verify_signature()` called before any DB write — `burnlens_cloud/billing.py:246`; 401 on failure — `burnlens_cloud/billing.py:245,247`; pytest tests 1-4 assert 401 (`tests/test_billing_webhook_phase7.py:119,133,148,162`) | closed |
| T-07-07 | Tampering (body mutation) | `paddle_webhook` | mitigate | HMAC bound to raw body bytes before JSON parse — `burnlens_cloud/billing.py:229,241,246`; `json.loads(raw_body)` only runs post-verification (`burnlens_cloud/billing.py:250`) | closed |
| T-07-08 | Replay (duplicate event flood) | `paddle_webhook` | mitigate | `INSERT ... ON CONFLICT (event_id) DO NOTHING RETURNING event_id` — `burnlens_cloud/billing.py:267-275`; `{"received": true, "deduped": true}` short-circuit — `burnlens_cloud/billing.py:276-277`; pytest test 6 pins this | closed |
| T-07-09 | Timing attack on HMAC | `_verify_signature` | mitigate | `hmac.compare_digest(expected, h1)` — `burnlens_cloud/billing.py:231`; constant-time comparison preserved | closed |
| T-07-10 | Information Disclosure (cross-tenant) | `GET /billing/summary` | mitigate | `Depends(verify_token)` + `WHERE id = $1` bound to `token.workspace_id` — `burnlens_cloud/billing.py:466,473-481`; pytest test 17 pins workspace scoping | closed |
| T-07-11 | DoS via handler retry-storm | webhook dispatch | mitigate | try/except returns 200 + writes to `paddle_events.error` — `burnlens_cloud/billing.py:279-301` (try at 279, error UPDATE at 296-298, return at 301); pytest test 12 pins this | closed |
| T-07-12 | Broken access control on /summary | endpoint router | mitigate | `Depends(verify_token)` at route — `burnlens_cloud/billing.py:466`; pytest test 16 pins 401 on missing Authorization (`tests/test_billing_webhook_phase7.py:611`) | closed |
| T-07-13 | SQL injection via payload fields | handlers | mitigate | All UPDATE/SELECT use asyncpg `$N` parameterised binds — `burnlens_cloud/billing.py:324-342` (activated), `360-375` (updated), `382-390` (canceled), `410-417` (payment_failed), `473-481` (summary). Zero f-string / `%` SQL concatenation anywhere in the file. | closed |

### Plan 03 — BillingContext (frontend/src/lib/contexts/BillingContext.tsx)

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-07-14 | Info disclosure via logs | `BillingProvider.refresh` catch block | mitigate | Only `err?.message` written to state — `frontend/src/lib/contexts/BillingContext.tsx:84`; `AuthError` returns early before any state write (line 80-82); no payload/token surfaced | closed |
| T-07-15 | Info disclosure via localStorage | `BillingContext` state | mitigate | No `localStorage.setItem` anywhere in the module (grep count = 0); state lives in `useState` / `useRef` only — `frontend/src/lib/contexts/BillingContext.tsx:61-64` | closed |
| T-07-16 | DoS via runaway polling | polling interval | mitigate | Interval gated on `document.visibilityState === "visible"` — `frontend/src/lib/contexts/BillingContext.tsx:95`; focus handler debounced by 10s staleness — line 106; `clearInterval` + `removeEventListener` cleanups — lines 99, 111 | closed |
| T-07-17 | Spoofing via pre-auth fetch | `BillingProvider` | mitigate | `if (!session) return;` in `refresh()` (line 67) and both effects (lines 92, 104); Shell.tsx session guard ensures provider never mounts pre-auth — `frontend/src/components/Shell.tsx:16-28,31-55` | closed |
| T-07-18 | Broken access control (wrong-workspace reads) | endpoint pairing | transfer | Backend `verify_token` scoping on `/billing/summary` — `burnlens_cloud/billing.py:466,481` (documented under T-07-10). Frontend has no path param / body for workspace selection; see Transferred Risks. | closed |
| T-07-18b | Cascade failure via hook misuse | `useBilling` | mitigate | Single `useContext` body — `frontend/src/lib/contexts/BillingContext.tsx:126-128`; `DEFAULT_VALUE` seeded at createContext (line 42); grep for raise/throw statements = 0 across module | closed |

### Plan 04 — UI (BillingStatusBanner.tsx, Shell.tsx, Topbar.tsx, app/settings/page.tsx)

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-07-19 | Spoofing via `?checkout=success` manipulation | Settings page mount effect | accept | Listener side-effect limited to `refreshBilling()` (read-only, workspace-scoped) + `history.replaceState` — `frontend/src/app/settings/page.tsx:28-34`. No state mutation, no external call. See Accepted Risks Log. | closed |
| T-07-20 | XSS via Paddle-supplied fields | `BillingCardBody` / Topbar / banner | mitigate | All fields render via React JSX text interpolation or `toLocaleDateString` / `Intl.NumberFormat` — `frontend/src/app/settings/page.tsx:206,219`; zero unsafe-HTML injection APIs used across the frontend surface (grep across `frontend/` returns no files). React escapes by default. | closed |
| T-07-21 | Clickjacking on disabled "Manage billing" CTA | Settings card | mitigate | `disabled` + `aria-disabled="true"` — `frontend/src/app/settings/page.tsx:266-267,301-302,384-385`; buttons receive no click / keyboard focus events | closed |
| T-07-22 | Info Disclosure via banner persistence | `BillingStatusBanner` | mitigate | `if (billing?.status !== "past_due") return null;` — `frontend/src/components/BillingStatusBanner.tsx:15`; no sessionStorage / localStorage caching in module | closed |
| T-07-23 | Privilege escalation via plan-label spoof | Topbar pill | accept | Client-side plan label is display-only; authoritative enforcement is backend via `verify_token` (Plan 02) and future Phase-9 entitlement middleware. See Accepted Risks Log. | closed |
| T-07-24 | Broken access control (wrong-workspace reads) | Settings + Topbar | transfer | `/billing/summary` workspace-scoped server-side — `burnlens_cloud/billing.py:466,481` (documented under T-07-10). No frontend path-param or override surface. See Transferred Risks. | closed |
| T-07-25 | Phishing via banner link | `BillingStatusBanner` | mitigate | `<Link href="/settings#billing">` same-origin relative — `frontend/src/components/BillingStatusBanner.tsx:36`; zero `target=` / `rel=` attributes in the module (grep returns no matches) | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-07-01 | T-07-04 | No read API / admin surface for `paddle_events` introduced in Phase 7. The table is write-only from the webhook handler; no cross-tenant read path exists. Must be revisited if an admin-read UI over `paddle_events` is ever added. | Phase 7 planner (PLAN 07-01) | 2026-04-19 |
| AR-07-02 | T-07-19 | `?checkout=success` listener triggers only a harmless `refreshBilling()` fetch of the caller's own `/billing/summary` (workspace-scoped backend) plus a benign `history.replaceState`. No state mutation, no external call, no cost amplification. Any adversary who could already reach the authenticated Settings route gains nothing by crafting the param. | Phase 7 planner (PLAN 07-04) | 2026-04-19 |
| AR-07-23 | T-07-23 | Client-side plan label (`billing?.plan ?? session?.plan`) is UI-only. Authoritative plan enforcement lives server-side: `/billing/summary` response is server-authenticated, and every gated API call is enforced by backend middleware (`verify_token` today; Phase 9 entitlement middleware extends this). Tampering with the client value only affects the label render. | Phase 7 planner (PLAN 07-04) | 2026-04-19 |

## Transferred Risks

| Risk ID | Threat Ref | Receiving Control | Evidence |
|---------|------------|-------------------|----------|
| TR-07-18 | T-07-18 | Plan 02 backend scoping (T-07-10) — `/billing/summary` binds `WHERE id = $1` to `token.workspace_id` | `burnlens_cloud/billing.py:466,473-481` (verified active); pytest `test_billing_summary_scoped_to_caller` (`tests/test_billing_webhook_phase7.py:619`) |
| TR-07-24 | T-07-24 | Plan 02 backend scoping (T-07-10) — same as TR-07-18 | Same evidence as TR-07-18 |

---

## Unregistered Threat Flags

None. All four SUMMARY.md files (`07-01-SUMMARY.md`, `07-02-SUMMARY.md`, `07-03-SUMMARY.md`, `07-04-SUMMARY.md`) explicitly state "Threat Flags: None — every mitigation in the plan's threat register is implemented". No new attack surface was discovered during implementation that fell outside the 26-threat register.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-04-19 | 26 | 26 | 0 | gsd-security-auditor (Claude Opus 4.7) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer) — 21 mitigate, 3 accept, 2 transfer
- [x] Accepted risks documented in Accepted Risks Log (AR-07-01, AR-07-02, AR-07-23)
- [x] Transferred risks documented in Transferred Risks table (TR-07-18, TR-07-24) with evidence pointing at Plan 02 T-07-10
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-04-19
