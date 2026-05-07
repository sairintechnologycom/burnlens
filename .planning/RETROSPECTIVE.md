# BurnLens — Retrospective

---

## Milestone: v1.1 — Billing & Quota

**Shipped:** 2026-04-30
**Phases:** 5 (6–10) | **Plans:** 31

### What Was Built

- Plan limits Postgres table (`plan_limits`) with `resolve_limits()` SQL function; Free/Cloud/Teams seeded with live Paddle IDs
- Full Paddle subscription lifecycle sync (created/updated/canceled/payment_failed) with dedup + `BillingContext` React provider
- Complete billing self-service loop in Settings: upgrade/downgrade/cancel/reactivate/invoices — 5 backend endpoints + 3 frontend modals
- Monthly usage quotas per workspace: soft enforcement (seat/API-key 402s), 80%/100% warning emails, daily retention pruning, plan entitlement middleware on gated routes
- Feature gating UI: `LockedPanel` with frosted-glass teaser + dynamic upgrade CTAs; `UsageMeter` in Sidebar with green/amber/red thresholds; daily breakdown in Settings → Usage; `ApiKeysCard` with plaintext-once reveal + typed-name revoke

### What Worked

- **Phase-by-phase VALIDATION.md files**: Writing Nyquist validation artifacts at the end of each phase caught gaps early and gave the milestone audit a clean pass. Having these retroactively applied (Phases 7+8) was slower but still worked.
- **31-plan granularity**: Breaking Phase 8 into 12 focused plans (one per endpoint/component) made each executor context small and clean. No plan bled into adjacent concerns.
- **Soft enforcement first**: Shipping 402s on seat/API-key caps without hard ingest 429 was the right call — gets enforcement live, collects usage data, avoids premature rate-limit tuning.
- **Paddle as authoritative source**: Wiring BillingContext to poll `/billing/summary` rather than derive state from checkout redirects eliminated an entire class of race conditions.
- **test_phase08_billing.py fix cycle**: 4 failures on first run, all fixed in the same session. The mock-row mismatch pattern is now documented in phase artifacts.

### What Was Inefficient

- **Phase 7 and 9 ROADMAP.md status stayed stale**: Plans showed `[ ]` / "Planned" even after completion. This caused confusion in subsequent sessions. Status should be updated atomically when plans complete.
- **Phase 9 VERIFICATION.md never written**: The milestone audit had to accept VALIDATION.md + tests as a procedural substitute. A `gsd-verify-work` run after Phase 9 would have closed this cleanly.
- **test_plan_limits.py dotenv isolation**: The pydantic-settings `extra_forbidden` shim issue was known in Phase 6 and never patched. 3-line fix deferred across 4 phases.
- **25 human-UAT items deferred**: Live Paddle sandbox tests required real browser/webhook infrastructure. These should be scheduled after milestone close, not perpetually deferred.

### Patterns Established

- **`require_feature(name)` dependency factory**: Reusable FastAPI gate pattern — any future gated route can use `Depends(require_feature("feature_name"))` without reimplementing entitlement logic.
- **BillingContext as single data source**: All billing-adjacent UI reads from one polling context. No component owns its own billing fetch.
- **Phase 10 CSS file ownership**: All Phase 10 CSS written to `globals.css` at Plan 02, owned by that file boundary. Subsequent plans explicitly do not touch CSS. Avoids merge conflicts across parallel plan execution.
- **`_load_billing_summary` mutation responses**: Phase 8 mutations return a fresh BillingSummary; Phase 10 extensions are picked up via re-poll within 60s. The "mutation response returns stale subobjects" pattern is accepted and documented.

### Key Lessons

- **Update ROADMAP.md at plan commit time**, not at phase close. Stale progress tables break milestone audits and confuse session resumption.
- **Write VERIFICATION.md before moving to the next phase**. It's much harder to write retroactively; the executor context is gone.
- **Patch known CI reliability gaps immediately**. The test_plan_limits.py shim was a 3-line fix that got deferred for 12 days. Small tech debt items compound into audit noise.
- **Human-UAT items need a concrete follow-up schedule**. "Open: 8 items in 08-HUMAN-UAT.md" is not the same as a planned test session. Offer to `/schedule` these after each phase with live Paddle credentials.

### Cost Observations

- Sessions: ~20 across 12 days
- Notable: Phase 8 (12 plans) was the most expensive phase; executor context per plan stayed manageable due to focused scope
- Phase 9 validation retroactively written (gsd-nyquist-auditor subagent) — cost-effective pattern for gap-filling

---

## Milestone: v1.2 — Account Security & Notifications

**Shipped:** 2026-05-06
**Phases:** 4 (11–14) | **Plans:** 22 | **Commits:** ~150

### What Was Built

- `auth_tokens` table + `email_verified_at` column; password-reset + verify-email flows with RETURNING-safe single-use token enforcement; `BillingStatusBanner` for soft-gate; grandfathering for pre-v1.2 users
- Typed `TemplateSpec` registry with 6 SendGrid transactional templates (welcome, verify, reset-request, reset-confirm, receipt, alert); `TemplateRegistry` extensible for all future notification types
- `alert_rules` + `alert_events` Postgres schema with idempotent 80%/100% seeding; hourly Railway cron with 24h dedup window; email dispatch + SSRF-guarded Slack webhook
- `/alerts` management UI with toggle/edit/threshold controls; viewer-role enforcement via `session.role`; IDOR-protected backend endpoints
- `decide_route()` in OSS proxy: 60s team-spend TTL cache, fail-open on all exceptions, provider downgrade map; `routed_model`+`downgrade_reason` DB columns; "Downgrades Today" dashboard KPI; `burnlens routing` CLI

### What Worked

- **TDD Wave 0 for Phase 13**: Writing 8 failing tests before any implementation kept the API contract honest and caught the IDOR gap before it was written. Red-first discipline paid off.
- **Worktree-based parallel execution (Phase 13)**: Backend (Plan 01) and frontend (Plan 02) ran in parallel worktrees — both merged cleanly with no conflicts. The pattern is repeatable for any phase with independent backend/frontend tracks.
- **Fail-open as a design axiom**: Codifying `decide_route()` never raises as an explicit contract (not just a hope) made the router testable and the proxy provably safe. Every error path is exercised in the 12-test suite.
- **Security review cycle**: Phase 12 SSRF guard and Phase 14 Phase 11 TOCTOU fixes (CR-01–03) were caught and patched within the same milestone. The code-review → review-fix cycle is working.
- **Stale audit problem solved**: The v1.2 milestone audit was run at Phase 11 completion (mid-milestone), not at close. Recognizing it as stale at close (rather than acting on it) saved a false-positive audit loop.

### What Was Inefficient

- **Milestone audit was stale at close**: Audit ran 2026-05-02 after Phase 11; Phases 12–14 were executed after. Resulted in a `gaps_found` status that was misleading at close. Audit should run at close, not mid-milestone.
- **REQUIREMENTS.md never kept up**: All AUTH/EMAIL checkboxes stayed `[ ]` throughout execution. Phase 14 requirements (ROUTE-01–07) were never added. Checkbox hygiene needs to happen at plan-commit time, not at milestone close.
- **ROADMAP.md Phase 14 showed as "OSS / Planned"**: Phase 14 was added to the milestone post-kickoff but the milestone header was never updated from Phases 11–13 to 11–14. One stale line caused confusion at progress checks throughout.
- **UAT Test 3 skipped**: The auto-downgrade live-fire test was skipped because it required a real API call with a budget-constrained workspace. This class of test (requires real money/credentials) should be scheduled as a dedicated manual test session, not left as a skipped UAT item.

### Patterns Established

- **`decide_route()` fail-open contract**: Any async function that can influence proxy behavior should be wrapped in a try/except that returns a safe passthrough default. Never let routing logic raise to the caller.
- **IDOR protection via `WHERE id=$N AND workspace_id=$N+1`**: Workspace ID always comes from the JWT (not the request body). Any PATCH/DELETE on a workspace-scoped resource must double-filter. Established in `alerts_api.py`.
- **`role` in JWT + `LoginResponse`**: Role encoded in JWT at login; `LoginResponse` returns it to frontend; `AuthSession` shape in `useAuth.ts` carries it. Any new role-gated UI reads `session.role`, never a separate fetch.
- **Worktree parallel execution**: For phases with independent backend + frontend plans, launch both in separate git worktrees, merge both on green. Documented in Phase 13 execution artifacts.

### Key Lessons

- **Run the milestone audit at close, not during execution.** Mid-milestone audits are useful for catching blockers but produce misleading `gaps_found` status for unstarted phases. The final audit should be the one that gates milestone completion.
- **Keep REQUIREMENTS.md checkboxes current at plan-commit time.** It's a 30-second edit; deferring it to close creates a false impression of incomplete work throughout the milestone.
- **Update the milestones list header when scope changes.** Adding Phase 14 mid-milestone without updating the Milestones section header created "Phases 11–13" staleness that persisted to close.
- **Schedule live-fire UAT tests with real credentials as a separate calendar event.** Don't leave them as skipped UAT items — they require a human with a funded sandbox account and can't be automated into the normal CI flow.

### Cost Observations

- Sessions: ~8 across 7 days (dense execution)
- Notable: Worktree parallel execution compressed Phase 13 to a single session; Phase 14 (7 plans) executed efficiently with narrow per-plan scope
- Phase 11 was the heaviest context phase (9 plans, review cycle, auth complexity)

---

## Cross-Milestone Trends

| Milestone | Phases | Plans | Days | Files | LOC+ |
|-----------|--------|-------|------|-------|------|
| v1.0 | 5 | ~15 | 5 | — | — |
| v1.1 | 5 | 31 | 12 | 241 | +48,179 |
| v1.2 | 4 | 22 | 7 | 181 | +23,628 |

**Trend:** v1.2 was the most time-efficient milestone — 4 phases in 7 days vs v1.1's 5 phases in 12 days. Narrower plan scope (avg 5.5 plans/phase vs 6.2) and parallel worktree execution both contributed. LOC delta is lower because v1.2 was more targeted (auth + alerting) vs v1.1's broad billing infrastructure.

**Recurring issue (3rd milestone):** ROADMAP.md and REQUIREMENTS.md status staleness appeared again in v1.2 (Phase 14 scope not added to milestones list, all AUTH/EMAIL checkboxes unchecked). This is a systemic gap — needs a post-plan-commit hook or a pre-progress-check lint step.
