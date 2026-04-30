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

## Cross-Milestone Trends

| Milestone | Phases | Plans | Days | Files | LOC+ |
|-----------|--------|-------|------|-------|------|
| v1.0 | 5 | ~15 | 5 | — | — |
| v1.1 | 5 | 31 | 12 | 241 | +48,179 |

**Trend:** Plan count doubled v1.0→v1.1 due to Phase 8 granularity (12 plans vs 3/4 typical). Timeline stayed reasonable (12 days). Larger plan counts correlate with cleaner executor contexts and fewer mid-plan pivots.

**Recurring issue:** ROADMAP.md status staleness appeared in both v1.0 and v1.1. Needs a hook or checklist at plan-commit time.
