# BurnLens current capability matrix

Baseline: `e970456d38bbe57081a05fba7f0bdd1ff8e899e7` (`main`, `v1.26.0-1-ge970456`).
Certified: 2026-09-04. Source-traced. Conversation history is not authority.

Classification key:

- **SHIPPED** — execution path exists, is reachable, and has tests.
- **PARTIAL** — core path exists but a surface is incomplete, stale, or contradictory.
- **DORMANT** — code exists but is not on the default user path.
- **CONTRADICTORY** — implementation and a public claim disagree.
- **MISSING** — no implementation found.

---

## Capability matrix

| Capability | Class | File / function | API / CLI | Table / model | Test | Public surface |
|---|---|---|---|---|---|---|
| AI request cost / pricing | SHIPPED | `burnlens/cost/` calculator + `pricing_data/*.json` | proxy insert; `burnlens pricing` | `requests.cost_usd`, `pricing_class` | `tests/test_custom_pricing.py`, pricing calculator tests | `/llm-pricing` |
| Proxy | SHIPPED | `burnlens/proxy/server.py`, `interceptor.py` | `burnlens start`; `:8420/proxy/*` | `requests` | `tests/test_proxy.py`, e2e proxy | `/docs/proxy` |
| Provider registry | SHIPPED | `burnlens/providers/__init__.py` registers 10 | `/proxy/{name}` | `provider_signatures` | `tests/test_providers_plugin.py`, `test_providers_openai_compatible.py` | homepage chips, README table |
| Scanners | SHIPPED | `burnlens/scan/{claude,cursor,codex,gemini_cli}.py` | `burnlens scan --provider` | `requests` (estimated) | `tests/test_scan_claude.py` and siblings | `/scan`, `/docs/scan` |
| Repo attribution | SHIPPED | scan + git context; `burnlens repos` | `burnlens repos` | request tags / repo | `tests/test_cli.py` | `/scan` next-step |
| Developer attribution | SHIPPED | CLI `devs` (CHANGELOG / CLI) | `burnlens devs` | request tags | CLI tests | README use-cases |
| PR attribution | PARTIAL | outcomes derive from `gh`; cost is per-repo not per-branch | `burnlens outcome derive` | `outcomes` | scan derive tests | `/cost-per-outcome`, README |
| Workflow attribution | SHIPPED | tags + `workflow_id` allocation | outcomes APIs | `outcomes`, request tags | `tests/test_outcomes_api.py` | `/outcomes` |
| Outcomes | SHIPPED | `burnlens/outcomes.py` | `burnlens outcome *`; `/api/v1/outcomes` | `outcomes` | outcomes tests | `/outcomes`, `/cost-per-outcome` |
| Outcome derivation (merged PR) | SHIPPED | `derive_pr_outcomes` in `burnlens/outcomes.py`; CLI `_run_scan_derive` | `burnlens scan` then `outcome derive` | `outcomes` | `tests/test_cli.py::test_scan_derives_outcomes_when_gh_is_present` | `/scan`, README |
| Outcome allocation | SHIPPED | 24h window, unattributed retained | `/api/v1/outcomes/summary` | `outcomes` | outcomes API tests | `/outcomes` copy |
| Cost per accepted outcome | SHIPPED | `burnlens/analysis/economics.py`; dashboard routes | `burnlens economics`; `/api/v1/economics` | derived | `tests/test_economics_overview.py` | dashboard, `/cost-per-outcome` |
| Outcome Coverage | SHIPPED | coverage API + `OutcomeCoverageView` | `/api/v1/outcomes/coverage` | derived | `frontend/tests/evidence-panels.test.ts` | dashboard |
| Cost Confidence | SHIPPED | confidence API + `CostConfidenceView` | `/api/v1/cost-confidence` | `pricing_class` | `tests/test_cost_confidence.py`, evidence-panels | dashboard, `/docs/evidence` |
| Provider reconciliation | SHIPPED | reconciliation API + billing keys | `/api/v1/reconciliation` | billing comparison | `frontend/tests/evidence-panels.test.ts` | dashboard badge, Settings |
| Waste detection | SHIPPED | `burnlens/analysis/waste.py` | `burnlens analyze`; `/waste` | `waste_findings` | waste tests | `/waste` |
| Recommendations | SHIPPED | `burnlens/analysis/recommender.py` | `burnlens recommend`; `/api/v1/recommendations` | derived | `tests/test_dashboard_api.py`, `frontend/tests/savings-recs.test.ts` | `/savings` |
| Projected savings | SHIPPED | recommender `projected_saving` + findings | savings rollup | derived | savings tests | `/savings`, EconomicsLoopPanel |
| Savings verification | SHIPPED | `burnlens/storage/findings.py` verdicts | `/api/v1/findings/savings` | findings | `tests/test_savings_verification.py` | `/savings` VerifiedSavingsPanel |
| Verified / Missed / Inconclusive | SHIPPED | findings verdict enum | savings rollup counts | findings | `tests/test_savings_verification.py`, `test_cloud_savings.py` | VerifiedSavingsPanel |
| Budget controls / alerts | SHIPPED | alerts + budget counters | `burnlens.yaml` alerts | `fired_alerts`, `budget_counters` | budget tests | `/docs/budgets`, `/alerts` |
| Hard caps | SHIPPED | interceptor 429 before upstream | per-key daily cap | `api_keys` | `docs/BUDGET_ENFORCEMENT.md` + tests | homepage, `/docs/budgets` |
| Model downgrade | SHIPPED | `burnlens/proxy/router.py`, `providers/downgrade.py` | `routing.budget_downgrade` | `requests.routed_model`, `downgrade_reason` | `tests/test_router.py` | homepage (opt-in), `/docs/budgets` |
| Budget-aware routing | SHIPPED | same router; **default off** | YAML / cloud `routing_overrides` | requests routing cols | `test_default_config_does_not_downgrade` | docs |
| Semantic cache | SHIPPED | `burnlens/cache/manager.py`; **default off** | `cache.enabled` | `semantic_cache` | `tests/test_semantic_cache.py` | `/cache`, homepage (claim incomplete) |
| Cloud sync | SHIPPED | `burnlens/cloud/sync.py` incl. `pricing_class` | `burnlens login` / sync | cloud ingest | `tests/test_cloud_sync.py` | Settings, `/security` |
| Dashboard (auth) | SHIPPED | `frontend/src/app/dashboard/page.tsx` + EconomicsNav | `/dashboard` `/outcomes` `/savings` `/waste` | cloud APIs | `frontend/tests/economics-ia.test.ts` | authenticated app |
| Local dashboard | SHIPPED | `burnlens/dashboard/` + `static/app.js` | `localhost:8420/ui` | local SQLite | dashboard tests | scan empty-state copy |
| Settings | SHIPPED | `frontend/src/app/settings/page.tsx` | settings + billing keys | workspace | e2e settings | `/settings` |
| Demo | CONTRADICTORY | `frontend/src/app/demo/page.tsx` | `/demo` | none (seeded fiction) | none for economics story | labeled LIVE DEMO; cost-tracker narrative |
| Marketing homepage | CONTRADICTORY | `frontend/src/app/page.tsx` | `/` | n/a | `landing-claims.test.ts` (dates only) | scan→`top`; MiniDashboard is spend-only |
| Documentation | SHIPPED | `/docs`, `/docs/scan`, `/docs/evidence`, `/docs/limitations`, `/docs/budgets` | docs routes | n/a | `frontend/tests/docs-routes.test.ts` | accurate scan funnel |
| Comparison pages | CONTRADICTORY | `/compare/burnlens-vs-*` | public | n/a | none vs registry | LiteLLM provider list stale; absolute passthrough |
| Security claims | CONTRADICTORY | `frontend/src/app/security/page.tsx` | `/security` | n/a | none vs policy | byte-for-byte / unmodified without policy exception |
| SEO / data pages | SHIPPED | `/llm-pricing`, `/cost-per-outcome`, `/scan` | public | pricing JSON / dogfood | `llm-pricing.test.ts`, `cost-per-outcome.test.ts` | original data, not thin SEO |
| Tests | SHIPPED | `tests/`, `frontend/tests/` | pytest, vitest, playwright | n/a | self | invariant tests exist for economics |
| CI/CD | SHIPPED | `.github/workflows/*`, `azure-pipelines.yml` | GitHub Actions + Azure | n/a | workflows | dual remote: Azure origin; GHA follows GitHub |

### Registered proxy providers (source of truth)

From `burnlens/providers/__init__.py`:

`openai`, `anthropic`, `google`, `groq`, `together`, `mistral`, `xai`, `deepseek`, `azure`, `bedrock` — **10**.

Scan-only sources (not proxy providers): `claude`, `cursor`, `codex`, `gemini`.

---

## Economic invariants

| ID | Verdict | Evidence |
|---|---|---|
| ECON-001 Unknown is not zero | PARTIAL | Unpriced renders `$ unknown` in `CostConfidenceView` and CLI `_warn_unpriced`. Guarded by `frontend/tests/evidence-panels.test.ts`. Request-row renderer on Overview still uses `(r.cost_usd ?? 0).toFixed(4)` and can print `$0.0000` for an unpriced row. |
| ECON-002 Evidence class | PASS | Classes `reconciled` / `calculated` / `estimated` / `unpriced` in OpenAPI snapshot and `frontend/src/lib/contracts.ts`. Synced via `pricing_class` (`8333308`). |
| ECON-003 Outcome coverage with cost-per-outcome | PASS | Dashboard renders `OutcomeCoveragePanel` beside economics. Outcomes page keeps unattributed visible. |
| ECON-004 Missing attribution visible | PASS | Outcomes KPI "Unattributed"; coverage tiers "Tagged, no outcome" and "No workflow tag". |
| ECON-005 Prediction ≠ verification | PASS | `VerifiedSavingsPanel` separates projected / verified / missed / still verifying. `EconomicsLoopPanel` shows both. |
| ECON-006 Regressions are not wins | PASS | `tests/test_savings_verification.py`: missed does not add to verified. |
| ECON-007 Traffic normalization | PASS | Verification uses cost-per-request (`test_cloud_savings.py`, `test_savings_verification.py` volume-drop case). |
| ECON-008 Provider cache semantics | PASS | `inclusive_prompt_token_providers()` derived from registry (`burnlens/providers/registry.py`). |
| ECON-009 Historical pricing honesty | PASS | CLI `_disclose_scan_pricing`; `/docs/scan` and `support-knowledge/limitations.md`; scanned rows classified estimated. |
| ECON-010 Waste overlap | PASS | `waste_estimate_clamped`; `tests/test_economics_overview.py` overlap + clamp tests. CLI prints overlap warning. |

No P0 invariant FAIL. ECON-001 is PARTIAL (request-row $0), not a presentation of unknown spend as known zero in the authoritative confidence panel.

---

## Policy defaults (source)

| Behavior | Default | File |
|---|---|---|
| `routing.budget_downgrade` | `false` | `burnlens/config.py` `RoutingConfig` |
| `cache.enabled` | `false` | `burnlens/config.py` `CacheConfig` |
| Hard cap 429 | only when a key cap is configured | interceptor + `docs/BUDGET_ENFORCEMENT.md` |
| Observation / cost calc / attribution | on | proxy + scan |

`tests/test_router.py::test_default_config_does_not_downgrade` locks the routing default.

---

## Public contradictions requiring BLU-100

1. **Homepage post-scan command is `burnlens top`.** Terminal animation and "Up in 3 commands" (`frontend/src/app/page.tsx`). CLI `_print_scan_next` and `/scan` / `/docs/scan` correctly say `burnlens repos`. `burnlens top` is a live proxy viewer, not the scan funnel.
2. **`/compare/burnlens-vs-litellm`** claims "None — transparent passthrough", "zero payload rewrites", and lists only OpenAI/Anthropic/Google as shipped with Azure/Bedrock/Groq/Mistral/Together on a v0.2/v0.3 roadmap. Registry has 10 providers. Downgrade can rewrite `model` when opted in.
3. **`/security`** FAQ and body claim byte-for-byte / unchanged body with no policy exception. `CONTRIBUTING.md` and `docs/BUDGET_ENFORCEMENT.md` already document the exception.
4. **FAQ** "automatically downgrades" for team/customer budgets without saying the flag is off by default (`frontend/support-knowledge/faq.md`).
5. **Homepage semantic cache card** describes serving from cache without saying `cache.enabled` defaults false.
6. **`/demo`** is a fictional Acme cost dashboard labeled "LIVE DEMO". Out of scope for BLU-100 claim cleanup; owned by BLU-300.

`tests/test_documented_cli_commands.py` only checks that named commands exist, and does not include the homepage. It would not catch scan→top.

---

## Economics IA (preview for BLU-200)

Authenticated economics is already four pages, one model (`EconomicsNav`): Overview, Outcomes, Savings, Waste.

Overview already loads confidence, coverage, economics, savings, recommendations. It does **not** yet use the five-question hero (AI Spend / Accepted / Cost per accepted / Confidence / Coverage / Verified). Labels still say "Total spend". Demo and homepage MiniDashboard remain spend-tracker narratives.
