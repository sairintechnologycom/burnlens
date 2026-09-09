# BurnLens AI economics positioning and product gap review

Initial review completed 2026-09-08 against local commit `e95b924` and the public website. This remains an implementation outline, not a release certification; the working tree now contains the tracked product and evidence changes below. Source paths refer to this checkout.

## Decision

Adopt **AI Economics Control Plane** as the category vision and **Measure, explain and control the cost of AI agents and LLM applications** as the immediately understandable description. Use **Measure. Control. Prove.** to organize the story.

The existing product is much closer to this direction than a greenfield roadmap implies. The largest gap is evidence strength: current savings verification establishes a reduction in cost per request, not that the intervention preserved successful outcomes or generated an independently attributable financial saving.

Coding-agent economics should remain the acquisition wedge. Do not expand the company definition into a generic observability or gateway feature contest. Do not claim that cost per outcome is exclusive to BurnLens: the differentiation must be the completeness and credibility of the economic workflow.

## What already exists

| Area | Current implementation | Remaining distinction |
|---|---|---|
| Local acquisition | Claude Code, Cursor, Codex and Gemini scanners; repo/dev tags; CLI; idempotent imports | Reliable organization-wide identity and complete outcome collection |
| Outcomes | Local and cloud APIs, accepted/rejected/failed records, GitHub PR derivation, workflow economics | Explicit run-to-outcome links, outcome corrections, comparable outcome units |
| Economic overview | Spend, accepted outcomes, unit cost, confidence, coverage, reconciliation and savings hero; Overview/Outcomes/Savings/Waste navigation | Metric semantics and complete evidence drill-down |
| Spend controls | Proxy budgets, daily caps, policy reservation, alerts, optional routing and cache | Enforcement guarantees, visibility into policy application and failure |
| Optimization | Waste findings, recommendations, resolve/baseline lifecycle, before/after verdicts and savings rollup | Intervention evidence, quality constraints, non-overlapping verified savings |
| Organization foundations | Workspace sync, attribution tags, team/customer views, roles, audit, custom pricing and OTEL code | Governed business dimensions, enterprise identity and financial reporting |
| Reconciliation | OpenAI and Anthropic daily cost comparison | Correct period coverage and additional billing sources when demanded |

Evidence: `burnlens/scan/`, `burnlens/outcomes.py`, `burnlens/storage/database.py`, `burnlens_cloud/outcomes_api.py`, `frontend/src/app/dashboard/EconomicsHero.tsx`, `frontend/src/components/EconomicsNav.tsx`, `burnlens/storage/findings.py`, `burnlens_cloud/findings.py`.

The September 4 capability matrix is stale in places: the economics hero now exists, the demo now tells an economics story, and overview/request-table rows use `formatRequestCostUsd`. Do not reopen those as missing features. Refresh that matrix after the work below.

## Progress tracker

Update this table as implementation lands. Status means the gap itself, not whether a related capability exists.

| ID | Status | Landed | Next concrete step |
|---|---|---|---|
| BL-ECON-01 | **Partial** | Dashboard, savings page, findings verdicts and product contract explain observed cost/request reduction; workflow acceptance degradation now prevents a verified verdict, while missing evidence remains unavailable. Added before/after acceptance-rate fields, a `quality_qualified` flag, persisted cohort/intervention IDs, optional change references, change type/URL evidence, explicit cohort scope for `workflow:<id>` or `model:<id>`, a visible `same_subject_equal_windows` comparison rule, and best-effort local Git commit capture when no change reference is supplied. | Ingest deployment/configuration systems as evidence and define comparability rules for cohorts that span multiple subjects. |
| BL-ECON-02 | **Partial** | Overlap risk documented; repeated local and cloud resolutions now retain prior verification evidence in `verification_history` before starting a new intervention baseline. | Prevent duplicate savings credit across findings. |
| BL-ECON-03 | **Open** | Existing outcome and coverage surfaces documented. | Separate comparable outcome types and show included/excluded spend. |
| BL-ECON-04 | **Open** | Existing reconciliation limitation documented. | Scope reconciliation evidence to provider and reporting dates. |
| BL-ECON-05 | **Open** | Existing enforcement ceilings documented. | Add explicit control scope/health and tighten ceiling semantics if required. |
| BL-ECON-06 | **Complete (copy pass)** | Homepage, README, demo metadata, scan copy, FAQ, contract, evidence docs, Open Graph copy, comparison pages and support index aligned to AI economics positioning. | Revisit copy only when product evidence or competitor facts change. |
| BL-ECON-07 | **Open** | Current GitHub derivation limits documented. | Stable repository identity and complete, date-bounded PR imports. |
| BL-ECON-08 | **Open** | Current idempotent outcome behavior documented. | Add auditable corrections/supersession for changed outcomes. |
| BL-ECON-09 | **Open** | Recommendations, actions and verification paths mapped. | Link applied changes to cohorts, configuration evidence and quality checks. |
| BL-ECON-10 | **Open** | Existing organization foundations documented. | Add only customer-requested cost-center, chargeback, currency and federation work. |

Last updated: 2026-09-09. This tracker is intentionally kept beside the gap review so implementation status and the evidence behind each recommendation change together.

## Priority backlog

Priority here means implementation order: **P0 = economic trust and public claims; P1 = dependable acquisition/outcomes; P2 = stronger proof; P3 = expansion.** Existing enterprise security and isolation requirements remain release gates, regardless of roadmap priority.

### BL-ECON-01 — P0: qualify savings verification and its units

**Observed:** `classify_savings` requires at least 30 after-window requests and any positive cost-per-request delta. The baseline need only have nonzero requests. Verifiers compare seven-day windows by default and extrapolate the measured delta to a 30-day rate. The UI calls that rate “Verified”; it is not accumulated cash saved in the selected reporting period.

**Risk:** Shorter/easier requests, changed workload mix, worse acceptance, price changes, or a tiny baseline can produce the verdict without proving an economically beneficial intervention. A model-scoped finding continues querying the old model after a switch, so a complete migration can become `no_traffic` instead of measuring the replacement workflow.

**Implement:** Immediately label the current result **Observed cost reduction · estimated monthly rate** and disclose its window and denominator. Preserve projected opportunity, observed period reduction, monthly extrapolation and eventual quality-qualified verification as separate quantities. For new intervention measurements, scope the comparison to the workflow/cohort across old and new models. Require adequate baseline and follow-up evidence; missing evidence is inconclusive.

The current comparison rule is deliberately narrow: `same_subject_equal_windows` compares the finding's subject over equal before/after windows. The optional `cohort_key` is persisted and displayed for auditability; it does not silently change the query scope until an explicit cohort mapping exists.

**Acceptance:** A model switch remains measurable; one baseline request cannot substantiate verification; a seven-day observation never appears as 30 days of realized savings; lower request cost with worse outcome economics does not receive the future economic-verification badge.

**Sources:** `burnlens/analysis/economics.py:136`, `burnlens/storage/findings.py:343`, `burnlens_cloud/findings.py:402`, `frontend/src/app/savings/VerifiedSavingsView.tsx`, `frontend/src/app/dashboard/EconomicsHero.tsx`.

### BL-ECON-02 — P0: prevent duplicate savings credit

**Observed:** Both savings rollups sum positive verdicts by finding fingerprint. A model finding and a workflow finding can cover the same requests. There is no allocation of savings credit across overlapping interventions. The waste overview clamps overlapping estimates, but that does not deduplicate savings.

**Implement:** Give a measured change one intervention identity and one reporting cohort/window. Until overlapping changes can be separated, mark the combined effect as shared/inconclusive instead of adding each finding’s full delta. Present gross reductions, measured regressions and net change separately; current “Missed” is a failed prediction, not the measured dollar regression.

**Acceptance:** Two detectors observing one change cannot double the portfolio savings; regressions remain visible; re-resolving a finding preserves the earlier measurement evidence.

**Sources:** `burnlens/storage/findings.py:495`, `burnlens_cloud/findings.py:792`, the baseline overwrite in both `set_finding_status` functions. Overlap is a source-derived correctness risk, not an observed production incident.

### BL-ECON-03 — P0: define valid cost-per-outcome cohorts

**Observed:** Local and cloud overview calculations sum accepted counts across workflows. Nothing distinguishes a PR from a ticket or document. The numerator includes workflow-tagged spend; headline AI spend also includes untagged spend. Outcome allocation assigns a request to the next outcome in that workflow within 24 hours, not an explicit run.

**Implement:** Define outcome type/unit and acceptance semantics. Show unit cost within comparable workflows/types; suppress a blended PR/ticket/document unit cost. Explain included spend, untagged spend, time window and attribution method next to the number. Retain time-window allocation as labeled inferred attribution and add optional explicit run/outcome links for instrumented workloads.

**Acceptance:** A workspace containing PRs and support tickets shows separate unit costs; the numerator reconciles to displayed included/excluded spend; two concurrent runs cannot claim exact attribution from temporal proximity alone; incomplete pricing qualifies the unit cost as a lower-bound estimate.

**Sources:** `burnlens/analysis/economics.py:345`, `burnlens_cloud/findings.py:710`, `burnlens/storage/database.py:1020`, `burnlens_cloud/outcomes_api.py:157`, `burnlens_cloud/models.py:187`.

### BL-ECON-04 — P0: scope reconciliation evidence to the period

**Observed:** Cost-confidence aggregation groups the selected reporting window, but uses the latest reconciliation status per provider to promote priced rows to `reconciled`. A successful day can therefore confer that label on other days. The displayed confidence percentage is priced-request coverage, not a statistical confidence interval or billing accuracy percentage.

**Implement:** Match reconciliation by provider, billing scope and covered dates; preserve original estimated/calculated provenance. Unmatched or stale periods remain unreconciled. Label the current percentage **Pricing coverage** and show evidence classes separately. Label local scan values as estimated usage cost at bundled rates, which can differ from subscription charges or historic invoices.

**Acceptance:** One reconciled day does not certify an entire month; estimated scan rows retain their provenance; 100% priced requests is not described as 100% invoice accuracy.

**Sources:** `burnlens_cloud/reconciliation.py:324`, `:414`, `:543`; `burnlens/cli.py:1338`. Only OpenAI and Anthropic have wired reconciliation clients.

### BL-ECON-05 — P0: align control promises with enforcement

**Observed:** Daily key caps check already-recorded spend without reserving the next request’s cost. Concurrent requests can overshoot. Policy reservations use estimates and a process-local lock. Budget check errors can fail open; active streams complete. Observation-only scans cannot stop calls.

**Implement:** Make those boundaries visible wherever users choose a control. Distinguish alert, recorded-spend cap and reserved-budget policy. Surface policy scope, enforcement health, bypass/failure events and last applied configuration. If selling a strict ceiling, first implement shared atomic reservations, bounded maximum call liability and an explicit failure policy; do not imply that a pre-call check alone guarantees it.

**Acceptance:** A user can identify exactly which traffic is controlled; configured failure behavior and concurrency guarantees have tests; public copy does not promise an absolute $50 ceiling for the current daily-cap mechanism.

**Sources:** `docs/BUDGET_ENFORCEMENT.md`, `burnlens/key_budget.py`, `burnlens/budget_engine.py`, `burnlens/proxy/interceptor.py`. This is a documented implementation limitation, not a newly discovered outage.

### BL-ECON-06 — P0: standardize public positioning and evidence

**Observed:** The homepage leads with economic results, but its next sections still promote many parallel capabilities. README calls BurnLens a FinOps proxy. Demo body says seeded fixture while demo Open Graph metadata says “real data.” The scan page says it never calls an API, despite automatic `gh` outcome derivation. Comparison pages retain the older enforcement-first framing.

**Implement:** Update the existing product contract, README, homepage, scan copy, demo metadata, support content and comparison copy together. Keep search terms such as AI FinOps and LLM cost management as discovery language. Source dated competitor claims; replace unsupported absolutes with precise integration/scope comparisons. Call the public walkthrough **Sample economics demo**.

**Acceptance:** Every first-touch surface uses the same category and plain-language explanation; fixture metadata never claims real telemetry; scan copy separates local log reading from optional GitHub access; evidence limitations survive copy edits.

**Sources:** `README.md:1`, `frontend/src/lib/product-contract.json`, `frontend/src/app/page.tsx:265`, `frontend/src/app/demo/layout.tsx:4`, `frontend/src/app/scan/page.tsx`, `frontend/src/app/compare/`.

### BL-ECON-07 — P1: finish the coding-agent acquisition loop

**Observed:** Automatic derivation runs for `repo_path="."`; the default import is the latest 200 closed PRs. Spend workflows use local repository basenames. Different repositories with the same folder name can collide; renamed checkouts can fragment identity. Developer attribution uses local git configuration or OS user, not authenticated workforce identity. No organization GitHub App/webhook ingestion path was found.

**Implement:** Introduce stable repository identity while preserving display names and migration mappings. Discover outcomes for scanned repositories with explicit scope/completeness reporting and date-bounded pagination. Keep `gh` for the local path; add a GitHub App only when unattended team collection is needed. Surface missing authentication, unsupported logs, pricing gaps and absent outcomes as actionable scan results. Map developer identities explicitly before cross-machine comparisons.

**Acceptance:** Two `api` directories from different owners remain separate; 201+ closed PRs are not silently truncated; repeated scans deduplicate; running outside a checkout explains how to derive outcomes; the same shared repository joins consistently across developers.

**Sources:** `burnlens/scan/_common.py:21`, `burnlens/git_context.py:67`, `burnlens/outcomes.py:120`, `burnlens/cli.py:1448`.

### BL-ECON-08 — P1: support outcome lifecycle and explainability

**Observed:** Outcome identity is idempotent, but duplicate writes are ignored. A PR first imported closed-unmerged can later reopen and merge while retaining its earlier rejected record. Generic API events also cannot correct their earlier status through the insert path.

**Implement:** Define an auditable correction/supersession mechanism, accepted-outcome policy, and evidence detail view. Separate observed merges from claims of defect-free or economically valuable code. Support explicit run links before building a visual graph; ordinary relational joins are sufficient.

**Acceptance:** Reopened-then-merged PR becomes one accepted outcome with history; corrected ticket outcomes do not double-count; each reported result links to source/status, allocation method and excluded spend.

**Sources:** `burnlens/outcomes.py:147`, `burnlens/storage/database.py:983`, `burnlens_cloud/outcomes_api.py` outcome insert path.

### BL-ECON-09 — P2: complete recommendation → action → evidence

**Observed:** Recommendations, finding resolution and operational actions exist, but the inspected records do not form a durable intervention with owner, intended cohort, old/new configuration, actual effective time, acceptance criteria and linked verification. Resolving a finding is currently the baseline trigger; it is not proof the change was applied.

**Implement:** Extend the existing finding/action flow with an intervention record and configuration/deployment evidence. Start with a manually recorded change linked to a commit/config revision. Add accepted outcomes, acceptance rate and workflow-normalized cost before/after. Consume external acceptance/evaluation signals rather than building a general evaluation platform. Display uncertainty and confounders; define quality tolerance in advance. Strong claims require suitable sample sizes and experimental evidence, not merely failure to find a significant difference.

**Acceptance:** A recommendation has one traceable applied change and measurement report; quality degradation blocks economic verification; insufficient evidence remains inconclusive; owner can export the calculation and inspect its inputs. Monthly extrapolation stays distinct from observed-period counterfactual savings and invoice-level changes.

**Sources:** `burnlens/analysis/recommender.py`, `burnlens_cloud/actions_api.py`, both findings stores, `frontend/src/app/savings/`.

### BL-ECON-10 — P3: expand from tags to organization economics

**Existing:** Teams, customers, features, workflows, workspace access, audit and telemetry already provide foundations.

**Implement when demanded:** Controlled dimension identities and ownership; cost-centre/business-unit mappings; shared-cost allocation with an unallocated bucket; exportable showback/chargeback; revenue imports and currency-safe margin reporting. `business_value` and `currency` fields are only primitives: current aggregation sums values without grouping currency, so do not use it for financial ROI reporting without currency validation/conversion semantics. Add enterprise SAML/OIDC federation/SCIM when procurement requires it; Google/GitHub social login code is not enterprise federation.

**Acceptance:** Allocations reconcile to the ledger, changes retain history, mixed currencies cannot be summed, reported margins declare excluded costs, and organization permissions apply to every relevant query/export.

## Website structure and copy

Recommended order: **economic problem → cost per accepted outcome → Measure/Control/Prove → evidence → coding-agent quick start → team expansion → supporting capabilities → pricing**.

Keep the existing headline. Add:

> BurnLens is the economic control plane for AI.
>
> Measure, explain and control the cost of AI agents and LLM applications. Connect spend to repositories, teams, customers and outcomes. Find waste, configure budgets, and measure what changes after an optimization.
>
> Start with your coding agents in one command. No prompt or source-code upload to BurnLens Cloud required.

CTAs: **Scan my AI usage** and **See a sample economics demo**. Secondary team CTA: **Review team economics**. Move cache/routing/anomaly internals below the economic story. Keep scan-derived PR economics explicitly repository-level and estimated.

Use “Prove” as the direction, with the current limits explained. Upgrade the commercial promise to unqualified “Prove savings” only when the evidence workflow supports it. Do not adopt the proposed “no statistically material degradation” statement without defining both the statistical method and acceptable quality loss.

The dated dogfood result is useful outcome evidence; it is not yet an external customer savings case study. Next proof asset: one real workflow with a documented intervention, same-scope before/after data, accepted outcomes, uncertainty and reproducible savings calculation. Keep the demo unmistakably synthetic.

## Delivery sequence

1. **Trust and positioning release:** BL-ECON-01–06. Qualify existing claims immediately; fix financial aggregation and evidence scope before broad promotion.
2. **Coding-agent wedge release:** BL-ECON-07–08. Stable identity, complete imports, corrections, and a dependable scan-to-repo-to-outcome journey.
3. **Proof release:** BL-ECON-09 plus the stronger verification work from 01–02. One workflow produces an auditable, quality-qualified result.
4. **Customer-led expansion:** BL-ECON-10. Add only dimensions and enterprise controls needed by actual deployments.

Track acquisition success (scan → usable repository economics), pricing and outcome coverage, connected-team activation, repeated economic review, interventions reaching an evidence-backed verdict, and retained paying workspaces. Do not optimize the roadmap for provider count or number of dashboards.

## Verification and limits

- Focused backend run: **139 passed, 2 skipped, 1 failed to import** because the available global Python environment lacks `pyotp`. The project `.venv` lacks pytest. The failing test was `test_outcomes_endpoint_is_csrf_exempt`; this run does not establish a product CSRF failure.
- Focused frontend run: **23 passed across 4 files** (`product-contract`, `demo-economics`, `economics-ia`, `evidence-panels`).
- The tests validate existing behavior, not the proposed stronger guarantees. New changes require checks matching the acceptance criteria above.
- Reviewed public rendered text and current source. Did not exercise a logged-in production workspace, real provider billing credentials, visual/mobile interactions, or a full clean-install scanner matrix. The web reader could not retrieve `/docs/limitations`; that alone is not evidence the page is broken.
- Passing contract tests do not mean all metadata or economic claims are correct: demo metadata and verification semantics illustrate gaps beyond those assertions.

Public sources checked: [homepage](https://burnlens.app/), [scan](https://burnlens.app/scan), [demo](https://burnlens.app/demo), [BurnLens comparison](https://burnlens.app/compare/burnlens-vs-langfuse). Current competitor context: [Langfuse cost tracking](https://langfuse.com/docs/observability/features/token-and-cost-tracking) and [Portkey buyer guide](https://portkey.ai/buyers-guide/ai-agent-observability-platform). These establish adjacent positioning, not a claim of exclusive BurnLens capabilities.
