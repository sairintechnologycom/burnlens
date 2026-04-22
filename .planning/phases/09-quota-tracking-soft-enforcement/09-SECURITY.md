---
phase: 9
slug: quota-tracking-soft-enforcement
status: verified
threats_open: 0
asvs_level: 1
created: 2026-04-22
---

# Phase 9 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Verified against implementation at `burnlens_cloud/**`. Implementation files are read-only per GSD contract.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| DB migration authority | `init_db()` runs at app boot; DDL executed with asyncpg pool privileges | schema DDL, backfill rows |
| Backfill cross-row reads | Backfill SELECT reads every `workspaces.api_key_hash`; INSERT writes `api_keys` | hashed keys (no plaintext) |
| SMTP outbound | `send_usage_warning_email` crosses app ↔ SendGrid | owner email (decrypted at send time) |
| Template file read | `emails/templates/usage_{threshold}_percent.html` path-joined from internal "80"/"100" literal | HTML template bytes |
| JWT / API-key ingress → workspace scope | `verify_token` → `TokenPayload.workspace_id`; `get_workspace_by_api_key` → `(workspace_id, plan)` | bearer auth, API-key hash lookup |
| `plan_limits.gated_features` | JSONB sourced from seeded migrations; not user-mutable | feature-flag booleans |
| Client → `/api-keys` handlers | HTTP cross-boundary; DB scoping uses `token.workspace_id` only | plaintext key emitted once on create |
| Plaintext key emission | Server → client exactly once at create | `bl_live_...` string |
| Ingest → counter UPSERT | API-key → workspace scope; counter write is server-authoritative | request count increments |
| Threshold email trigger | Internal app event; no client input influences dispatch | owner email, cycle metadata |
| Paddle → billing webhook | Signature verified upstream (Phase 7); handler trusts payload | `workspace_id`, period bounds |
| Webhook → `workspace_usage_cycles` | Internal DB write; values server-derived from verified payload | cycle row seed |
| Client → `/team/*` | Bearer/cookie auth; `require_feature("teams_view")` gate | team management ops |
| Entitlement gate | `require_feature` reads `plan_limits.gated_features`; clients cannot influence | 402 response or handler dispatch |
| Client → `/api/v1/usage/by-customer`, `/customers`, `/usage/by-team` | Bearer auth + `require_feature` gate at dependency layer | attribution aggregates |
| Internal scheduler → DELETE `request_records` | No external input; scheduler iterates server-known workspace ids | row deletions (hard delete) |
| Per-workspace DELETE | Every DELETE constrained by `WHERE workspace_id = $1` | scoped row deletions |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Evidence | Status |
|-----------|----------|-----------|-------------|------------|----------|--------|
| T-09-01 | Tampering | Plan 01 · `workspace_usage_cycles` UPSERT race | mitigate | `UNIQUE(workspace_id, cycle_start)` enforces one counter row per cycle | `burnlens_cloud/database.py:815-816` (`idx_workspace_usage_cycles_ws_start` UNIQUE) | closed |
| T-09-02 | Elevation of Privilege | Plan 01 · `api_keys` cross-tenant via key_hash collision | mitigate | `key_hash TEXT NOT NULL UNIQUE`; dual-read joins `w.active = true` | `burnlens_cloud/database.py:828`, `burnlens_cloud/auth.py:554-556` | closed |
| T-09-03 | Information Disclosure | Plan 01 · Backfill duplicates keys cross-tenant | mitigate | Set-based `INSERT … SELECT … WHERE NOT EXISTS (key_hash match)` — re-runs insert 0 | `burnlens_cloud/database.py:850-854` | closed |
| T-09-04 | Denial of Service | Plan 01 · Long migration lock on first deploy | accept | New tables, `CREATE TABLE IF NOT EXISTS` is fast; small backfill | See Accepted Risks R-1 | closed |
| T-09-05 | Tampering | Plan 01 · Seed supplement overwrites Phase 6 keys | mitigate | JSONB `||` merge preserves existing keys; no wholesale SET | `burnlens_cloud/database.py:867,872` (both UPDATEs use `gated_features = gated_features || '{…}'::jsonb`) | closed |
| T-09-06 | Repudiation | Plan 01 · `created_by_user_id` orphan after user delete | accept | `ON DELETE SET NULL` preserves audit row; `created_by_user_id` becomes NULL | `burnlens_cloud/database.py:833`; Accepted Risks R-2 | closed |
| T-09-07 | Information Disclosure | Plan 02 · `ApiKeyCreateResponse.key` plaintext in logs | mitigate | Pydantic docstring flags plaintext-once invariant; Plan 04 handler logs id+name only | `burnlens_cloud/models.py:428-431`; `burnlens_cloud/api_keys_api.py:96` (logger.info excludes plaintext) | closed |
| T-09-08 | Tampering | Plan 02 · Template path-traversal via `threshold` | mitigate | `if threshold not in ("80", "100"): return False` before path join | `burnlens_cloud/email.py:174-179` | closed |
| T-09-09 | Information Disclosure | Plan 02 · Decrypted owner email in logs | accept | Logs use workspace_id; `exc_info=True` may include traceback — internal logs only | Accepted Risks R-3 | closed |
| T-09-10 | Denial of Service | Plan 02 · Template read per ingest | accept | ~1KB read inside fire-and-forget coroutine via `asyncio.to_thread` | Accepted Risks R-4 | closed |
| T-09-11 | Spoofing | Plan 02 · SendGrid from-email tampering | accept | `settings.sendgrid_from_email` is server env var; no caller input | Accepted Risks R-5 | closed |
| T-09-12 | Spoofing | Plan 03 · Forged `token.plan` bypass | mitigate | `require_feature` re-reads `resolve_limits(token.workspace_id)`; `token.plan` used only for display | `burnlens_cloud/auth.py:319-334` | closed |
| T-09-13 | Elevation of Privilege | Plan 03 · Revoked key continues to auth | mitigate | Dual-read gates on `ak.revoked_at IS NULL`; `invalidate_api_key_cache` evicts TTL cache on revoke | `burnlens_cloud/auth.py:554-556`; `burnlens_cloud/api_keys_api.py:152` | closed |
| T-09-14 | Information Disclosure | Plan 03 · 402 body leaks internal plan names | mitigate | `required_plan` sourced from `plan_limits.plan` (public names: free/cloud/teams) | `burnlens_cloud/auth.py:278-296` | closed |
| T-09-15 | Elevation of Privilege | Plan 03 · Timing attack on key_hash lookup | accept | `key_hash` sha256 hex; UNIQUE B-tree is constant-time | Accepted Risks R-6 | closed |
| T-09-16 | Denial of Service | Plan 03 · `_lowest_plan_with_feature` per-call cost | accept | Only runs on 402 error path; `plan_limits` ≤ 5 rows | Accepted Risks R-7 | closed |
| T-09-17 | Tampering | Plan 03 · Dual-read fallback hides compromised legacy row | accept | Legacy fallback retains hash-only + active-only gate; transition-window only | Accepted Risks R-8 | closed |
| T-09-18 | Information Disclosure | Plan 04 · Plaintext re-emitted on list/delete | mitigate | `key=plaintext` appears only in `create_api_key`; `ApiKey` model has no `key` field; DELETE returns `{ok,id}` | `burnlens_cloud/api_keys_api.py:103` (only occurrence), `burnlens_cloud/models.py:416-426` | closed |
| T-09-19 | Elevation of Privilege | Plan 04 · Cross-tenant DELETE | mitigate | `UPDATE … WHERE id=$1 AND workspace_id=$2 RETURNING id`; empty result → 404 | `burnlens_cloud/api_keys_api.py:134-145` | closed |
| T-09-20 | Elevation of Privilege | Plan 04 · Race-at-cap on concurrent POST | accept | COUNT→check→INSERT non-atomic; overcount by 1 benign under soft-enforcement | Accepted Risks R-9 | closed |
| T-09-21 | Information Disclosure | Plan 04 · `last4` brute-force | accept | 4 chars sufficient for UI disambiguation only; attacker still needs full hash collision | Accepted Risks R-10 | closed |
| T-09-22 | Tampering | Plan 04 · Over-long name DoS | mitigate | Pydantic `ApiKeyCreateRequest.name: Optional[str] = Field(None, max_length=64)` | `burnlens_cloud/models.py:413` | closed |
| T-09-23 | Information Disclosure | Plan 04 · Error-code oracle (402 vs 404) | mitigate | 402 uses COUNT only (no per-row probe); 404 on caller-supplied id only | `burnlens_cloud/api_keys_api.py:60-64, 134-145` | closed |
| T-09-24 | Repudiation | Plan 04 · Missing audit trail for key create | accept | `logger.info("api_key.created/revoked …")` is Phase-9 audit surface; structured events deferred | Accepted Risks R-11 | closed |
| T-09-25 | Tampering | Plan 05 · Concurrent threshold email race | mitigate | Atomic `UPDATE … WHERE notified_*_at IS NULL RETURNING id` — only winner enqueues email | `burnlens_cloud/ingest.py:141-151, 164-174` | closed |
| T-09-26 | Tampering | Plan 05 · Double-count via retried ingest batch | accept | No batch idempotency key; retries count twice; no gating consequence | Accepted Risks R-12 | closed |
| T-09-27 | Denial of Service | Plan 05 · Ingest flood via minimal batches | accept | Counter bumps by `len(records)` not per-call; per-record accounting | Accepted Risks R-13 | closed |
| T-09-28 | Information Disclosure | Plan 05 · workspace_id + exc_info in logs | accept | Internal logs; workspace_id is UUID not PII | Accepted Risks R-14 | closed |
| T-09-29 | Elevation of Privilege | Plan 05 · Forged plan string bypass | mitigate | `plan` from `get_workspace_by_api_key` reading `workspaces` table — server-authoritative | `burnlens_cloud/auth.py:542-567` | closed |
| T-09-30 | Denial of Service | Plan 05 · `resolve_limits` per-call overhead | accept | Single Postgres round-trip; Phase 6 D-06 deliberately no-cache | Accepted Risks R-15 | closed |
| T-09-31 | Information Disclosure | Plan 05 · cycle_end_date leaks calendar | accept | Shown to workspace owner only; same info already in Settings → Billing | Accepted Risks R-16 | closed |
| T-09-32 | Tampering | Plan 06 · Paddle redelivery duplicate cycles | mitigate | Outer `paddle_events` dedup + inner `ON CONFLICT (workspace_id, cycle_start) DO NOTHING` | `burnlens_cloud/billing.py:429, 490` | closed |
| T-09-33 | Data loss | Plan 06 · Mid-cycle plan change resets counter | mitigate | `DO NOTHING` (not `DO UPDATE`) — existing row preserved | `burnlens_cloud/billing.py:429, 490` | closed |
| T-09-34 | Denial of Service | Plan 06 · Seed failure kills webhook | mitigate | Inner try/except logs warning; webhook still 2xx's Paddle; Plan 05 ingest UPSERT lazy-creates fallback | `burnlens_cloud/billing.py` (try/except wrapper around each INSERT block in both handlers) | closed |
| T-09-35 | Elevation of Privilege | Plan 06 · Cross-tenant seed via spoofed webhook | accept | Blocked at Phase 7 signature verification | Accepted Risks R-17 | closed |
| T-09-36 | Repudiation | Plan 06 · No log on successful seed | accept | Phase 7 already logs outer event; cycle row's `updated_at` is audit trail | Accepted Risks R-18 | closed |
| T-09-37 | Elevation of Privilege | Plan 07 · UI-bypass team invite by Free/Cloud | mitigate | `require_feature("teams_view")` applied at dependency layer on `/team/invite` and all team endpoints | `burnlens_cloud/team_api.py:147,198,264,343,465` | closed |
| T-09-38 | Information Disclosure | Plan 07 · 402 leaks seat-count | mitigate | Body contains only public info (limit, current, required_plan, upgrade_url) | `burnlens_cloud/team_api.py:385-398` | closed |
| T-09-39 | Elevation of Privilege | Plan 07 · accept_invitation accidentally gated | mitigate | `accept_invitation` not present in `team_api.py`; no `require_feature` on it (lives elsewhere, ungated) | Grep of `team_api.py` for `accept_invitation`: 0 matches | closed |
| T-09-40 | Tampering | Plan 07 · Seat-count race | accept | Same class as T-09-20; COUNT-then-INSERT non-atomic; v1.1 soft-enforcement accepts | Accepted Risks R-19 | closed |
| T-09-41 | Information Disclosure | Plan 07 · Internal plan names leak | mitigate | `required_plan` from `plan_limits.plan` (public names) | `burnlens_cloud/team_api.py:129-138` | closed |
| T-09-42 | Denial of Service | Plan 07 · `require_feature` per-call DB cost | accept | One extra SELECT per gated request; gated paths low-QPS (not ingest) | Accepted Risks R-20 | closed |
| T-09-43a | Elevation of Privilege | Plan 07 · Free/Cloud reads per-customer attribution (`/usage/by-customer`, `/customers`) | mitigate | `require_feature("customers_view")` dependency on both decorators; inline gate inside `get_costs_by_tag` | `burnlens_cloud/dashboard_api.py:155-158, 197, 352` | closed |
| T-09-44a | Elevation of Privilege | Plan 07 · Free/Cloud reads per-team attribution (`/usage/by-team`) | mitigate | `require_feature("teams_view")` dependency on decorator; inline gate inside `get_costs_by_tag` | `burnlens_cloud/dashboard_api.py:157-158, 210` | closed |
| T-09-45a | Information Disclosure | Plan 07 · Over-gating breaks base dashboard | mitigate | `/usage/summary`, `/by-model`, `/by-tag`, `/by-feature`, `/timeseries`, `/requests`, `/waste-alerts`, `/budget` confirmed ungated | `burnlens_cloud/dashboard_api.py` grep: `require_feature` absent from base-dashboard decorators (only 3 gated routes) | closed |
| T-09-43b | Tampering | Plan 08 · Cross-tenant DELETE leak in prune | mitigate | `WHERE workspace_id = $1` present in both outer DELETE and IN-subquery | `burnlens_cloud/compliance/retention_prune.py:70, 74` | closed |
| T-09-44b | Elevation of Privilege | Plan 08 · `retention_days = 0` abuse | mitigate | `limit_overrides` JSONB is server-admin only (no self-serve API); documented in `plans.py:36` resolver docstring | `burnlens_cloud/plans.py:36`; no user-facing override endpoint exists | closed |
| T-09-45b | Denial of Service | Plan 08 · Long-held prune lock blocks ingest | mitigate | Batch size 10,000 rows; row-locks only; ingest INSERTs untouched rows | `burnlens_cloud/compliance/retention_prune.py:65-79` (`LIMIT $3` with `_BATCH_SIZE = 10_000`) | closed |
| T-09-46 | Denial of Service | Plan 08 · Scheduler restart thrash at 03:00 UTC | accept | `_seconds_until_next_03_utc` jumps to tomorrow if now ≥ 03:00; safety-nap prevents tight loop | Accepted Risks R-21 | closed |
| T-09-47 | Information Disclosure | Plan 08 · workspace_id in logs | accept | UUID not PII; standard log convention | Accepted Risks R-22 | closed |
| T-09-48 | Data loss | Plan 08 · Runaway prune | mitigate | `retention_days` admin-controlled only; DELETE bounded by `ts < NOW() - make_interval(days => $2)`; no cross-workspace impact | `burnlens_cloud/compliance/retention_prune.py:69-75` | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

**Note on threat ID collisions:** Plans 07 and 08 both used `T-09-43/44/45`. Per audit contract, disambiguated here with suffix `a` (Plan 07, dashboard_api.py feature gating) and `b` (Plan 08, retention prune). Plan 08's `T-09-46/47/48` are distinct and preserved without suffix.

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| R-1 | T-09-04 | New tables only — `CREATE TABLE IF NOT EXISTS` is sub-millisecond; backfill is set-based over the current small `workspaces` rowcount. No online-migration orchestration needed. | Phase 9 planner | 2026-04-22 |
| R-2 | T-09-06 | `ON DELETE SET NULL` on `api_keys.created_by_user_id` is deliberate — audit-trail rows must survive user deletion rather than cascading away compromised-key history. | Phase 9 planner | 2026-04-22 |
| R-3 | T-09-09 | `exc_info=True` may include decrypted owner email in tracebacks, but logs are internal (Railway). Matches invitation-email precedent. | Phase 9 planner | 2026-04-22 |
| R-4 | T-09-10 | Template read is ~1KB inside fire-and-forget coroutine via `asyncio.to_thread`; off the hot path. Optimize only if profiling shows contention. | Phase 9 planner | 2026-04-22 |
| R-5 | T-09-11 | `settings.sendgrid_from_email` is server-set env var; no caller input reaches the From field. | Phase 9 planner | 2026-04-22 |
| R-6 | T-09-15 | `key_hash` is sha256 hex; DB UNIQUE index lookup is constant-time B-tree. Application-level cache timing is bounded and does not reveal hash content. | Phase 9 planner | 2026-04-22 |
| R-7 | T-09-16 | `_lowest_plan_with_feature` runs only on 402 error path; `plan_limits` is ≤ 5 rows. Acceptable for clean 402 body. | Phase 9 planner | 2026-04-22 |
| R-8 | T-09-17 | Legacy `workspaces.api_key_hash` fallback retains the same hash-only + `active = true` gate as before. Transition-window concession per D-12; removal planned for v1.1.1+. WR-02 fix also NULLs the legacy column on revoke to close the window. | Phase 9 planner | 2026-04-22 |
| R-9 | T-09-20 | COUNT→check→INSERT is non-atomic. Overcount by 1 under concurrent POSTs is benign in v1.1 (soft-enforcement; user still billed correctly). v1.2 may add `SELECT … FOR UPDATE` if abuse observed. | Phase 9 planner | 2026-04-22 |
| R-10 | T-09-21 | `last4` is 4 chars — entropy sufficient for UI disambiguation; attacker still needs a hash collision on the last 4. Mirrors GitHub/Stripe UX. | Phase 9 planner | 2026-04-22 |
| R-11 | T-09-24 | `logger.info` with workspace_id / id / name is Phase-9 audit surface. Structured audit log deferred to v1.2; sufficient for current forensics given small user base. | Phase 9 planner | 2026-04-22 |
| R-12 | T-09-26 | No batch-idempotency key on `/v1/ingest` retries in v1.1; retries will count twice. Soft enforcement means overcount has no gating consequence, only email timing. v1.2 should add ingest batch dedup if metrics show drift. | Phase 9 planner | 2026-04-22 |
| R-13 | T-09-27 | Counter bumps by `len(records)` per call (per-record accounting), so a flood of 1-record batches still counts each record. No bypass. | Phase 9 planner | 2026-04-22 |
| R-14 | T-09-28 | `logger.warning` messages include workspace_id (UUID, not PII) and `exc_info=True`; logs are internal. Matches existing conventions. | Phase 9 planner | 2026-04-22 |
| R-15 | T-09-30 | `resolve_limits` is a single Postgres round-trip; Phase 6 D-06 deliberately chose no in-process cache. Revisit only if profiling shows hotspot. | Phase 9 planner | 2026-04-22 |
| R-16 | T-09-31 | `cycle_end_date` surfaces only to the workspace owner via email and is already visible in Settings → Billing. No third-party leak. | Phase 9 planner | 2026-04-22 |
| R-17 | T-09-35 | Cross-tenant seed is blocked at Phase 7's signature verification layer. If that layer fails, the seed INSERT is not the primary concern. | Phase 9 planner | 2026-04-22 |
| R-18 | T-09-36 | Phase 7 already logs outer event processing. Successful cycle-row seed produces no additional log line; `updated_at` on the row serves as audit trail. Reduces log volume. | Phase 9 planner | 2026-04-22 |
| R-19 | T-09-40 | Same race class as T-09-20/R-9 for seat-count: COUNT-then-INSERT non-atomic; permits overcount by 1 under concurrent invites. v1.1 soft-enforcement accepts; v1.2 may add `SELECT … FOR UPDATE`. | Phase 9 planner | 2026-04-22 |
| R-20 | T-09-42 | Phase 6 D-06 intentionally no-cache on `resolve_limits`. Gated routes (team management, customer-attribution) are low-QPS. Hot paths (ingest) are not gated. | Phase 9 planner | 2026-04-22 |
| R-21 | T-09-46 | Railway redeploys are rare; `_seconds_until_next_03_utc` jumps to tomorrow if now ≥ 03:00 and the 60s safety-nap prevents tight looping. Worst case: one missed prune day on redeploy, caught up on the next run. | Phase 9 planner | 2026-04-22 |
| R-22 | T-09-47 | `workspace_id` is UUID, not PII. Matches logging conventions across the codebase. | Phase 9 planner | 2026-04-22 |

*Accepted risks do not resurface in future audit runs.*

---

## Unregistered Threat Flags (from SUMMARY.md)

No SUMMARY file in this phase declared new attack surface outside the authoritative `<threat_model>` blocks:

- 09-01..09-03 SUMMARY: no "Threat Flags" section — treated as "None" per convention.
- 09-04 SUMMARY: "Threat Flags: None — every surface matches the plan threat model."
- 09-05 SUMMARY: "Threat Flags: None. No new network endpoints, no new auth paths, no schema changes."
- 09-06 SUMMARY: "Threat Flags: No new security-relevant surface introduced."
- 09-07 SUMMARY: "Threat Flags: No new security-relevant surface introduced beyond T-09-37..T-09-45."
- 09-08 SUMMARY: "Threat Flags: None — every surface matches the threat model in the plan."

---

## Code-Review-Fix Security Impact

The Phase 9 code-review cycle (`09-REVIEW.md` + `09-REVIEW-FIX.md`) surfaced and resolved two security-adjacent warnings beyond the original threat register:

- **WR-05** — `send_invitation_email` scheduled `_send_background` before definition, silently failing invite sends. Resolved `e673124`. Not a new threat surface (availability of invite email, not confidentiality/integrity).
- **WR-06** — `team_api` SELECTs referenced dropped plaintext `users.email` column post-Phase-1c. Resolved `70764a2`. The fix correctly switches to `u.email_encrypted` + per-row `decrypt_pii`, and uses deterministic `lookup_hash` for duplicate-member probe — preserves PII-encryption invariants rather than introducing plaintext read/write.

The additionally tracked `CR-02` fix (`invalidate_api_key_cache` on revoke) and `WR-02` fix (NULL legacy `workspaces.api_key_hash` on revoke) strengthen T-09-13 (revoked key continues to auth) beyond the plan's original mitigation — both verified present in `api_keys_api.py:152` and `:158-166`.

Five Info findings (IN-01..IN-05) remain open as non-security maintenance (dead parameter, constant duplication, magic-number sentinel, template field parity, `asyncpg.Record.get()` pre-Phase-9 bug). None affects any T-09-* threat disposition.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-04-22 | 51 | 51 | 0 | gsd-security-auditor (Claude Opus 4.7 1M) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-04-22
