# Graph Report - .  (2026-04-11)

## Corpus Check
- Large corpus: 115 files · ~604,181 words. Semantic extraction will be expensive (many Claude tokens). Consider running on a subfolder, or use --no-semantic to run AST-only.

## Summary
- 2019 nodes · 4884 edges · 46 communities detected
- Extraction: 51% EXTRACTED · 49% INFERRED · 0% AMBIGUOUS · INFERRED: 2401 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## God Nodes (most connected - your core abstractions)
1. `AiAsset` - 359 edges
2. `DiscoveryEvent` - 320 edges
3. `BurnLensConfig` - 275 edges
4. `RequestRecord` - 180 edges
5. `AlertsConfig` - 134 edges
6. `ProviderSignature` - 120 edges
7. `DiscoveryAlert` - 104 edges
8. `SpendSpikeAlert` - 104 edges
9. `EmailConfig` - 89 edges
10. `EmailSender` - 83 edges

## Surprising Connections (you probably didn't know these)
- `tests/streaming/conftest.py  Fixtures and SSE factories grounded in the real int` --uses--> `BurnLensConfig`  [INFERRED]
  tests/streaming/conftest.py → burnlens/config.py
- `Return a path to a fresh temporary SQLite database.` --uses--> `BurnLensConfig`  [INFERRED]
  tests/conftest.py → burnlens/config.py
- `Initialize a fresh database and return its path.` --uses--> `BurnLensConfig`  [INFERRED]
  tests/conftest.py → burnlens/config.py
- `Return a BurnLensConfig wired to a temp DB.` --uses--> `BurnLensConfig`  [INFERRED]
  tests/conftest.py → burnlens/config.py
- `Tests for the FastAPI proxy app.` --uses--> `BurnLensConfig`  [INFERRED]
  tests/test_proxy.py → burnlens/config.py

## Hyperedges (group relationships)
- **Proxy Request Processing Pipeline** — claude_fastapi_proxy, readme_tag_attribution, claude_cost_engine, claude_sqlite_storage, readme_streaming_support [EXTRACTED 1.00]
- **Shadow AI Detection System** — discovery_shadow_ai, discovery_proxy_detection, discovery_billing_detection, discovery_shadow_classification, discovery_provider_signatures [EXTRACTED 1.00]
- **BurnLens x TokenLens Codebase Unification** — audit_overlap_analysis, audit_gap_analysis, audit_conflict_analysis, audit_unified_schema, audit_monorepo_structure, audit_build_sequence [EXTRACTED 1.00]
- **Four-Phase AI Governance Pipeline (Discovery -> Guardrails -> Compliance -> Platform)** — phase1_build_spec_shadow_ai_discovery, phase2_build_spec_policy_guardrails, phase3_build_spec_compliance_reporting, phase4_build_spec_governance_platform [EXTRACTED 1.00]
- **Compliance Evidence Data Flow (Assets + Violations + Approvals -> Audit Trail -> Evidence Package)** — phase1_build_spec_ai_asset_registry, phase2_build_spec_violation_audit_log, phase2_build_spec_approval_workflows, phase3_build_spec_audit_trail_export, phase3_build_spec_governance_evidence_package [EXTRACTED 0.95]
- **Progressive Monetization Strategy (Free -> $49-149 -> $149-399 -> $399-999)** — phase1_build_spec_free_tier_strategy, phase2_build_spec_pricing_tiers, phase3_build_spec_pricing_tiers, phase4_build_spec_pricing_tiers [EXTRACTED 0.90]
- **BurnLens Dark Icon Size Variants** — landing_burnlens_icon_512, landing_burnlens_icon_32, docs_burnlens_icon_512, docs_burnlens_icon_32, dashboard_burnlens_icon_32 [EXTRACTED 1.00]
- **BurnLens Logo Compositions** — landing_burnlens_logo_wide, docs_burnlens_logo_wide, docs_burnlens_logo_800 [EXTRACTED 1.00]
- **BurnLens Icon Theme Variants** — docs_burnlens_icon_512, docs_burnlens_icon_512_alt, docs_burnlens_icon_light_512 [EXTRACTED 1.00]
- **BurnLens Complete Brand Asset System** — burnlens_brand_identity, landing_burnlens_icon_512, landing_burnlens_icon_32, landing_burnlens_logo_wide, dashboard_burnlens_icon_32, docs_burnlens_logo_800, docs_burnlens_icon_512, docs_burnlens_icon_512_alt, docs_burnlens_icon_light_512, docs_burnlens_icon_32, docs_burnlens_logo_wide [INFERRED 0.90]
- **Dashboard KPI Summary Cards** — dashboard_total_spend_metric, dashboard_requests_metric, dashboard_avg_cost_metric, dashboard_budget_metric [EXTRACTED 1.00]
- **Dashboard Visualization Charts** — dashboard_cost_timeline_chart, dashboard_cost_by_model_chart, dashboard_cost_by_feature_chart [EXTRACTED 1.00]
- **Waste Detection and Alerts Section** — dashboard_waste_alerts_panel, dashboard_duplicate_requests_alert, dashboard_system_prompt_waste_alert [EXTRACTED 1.00]
- **Dashboard Demo Image Assets** — burnlens_landing_gif, burnlens_docs_gif, dashboard_png, burnlens_1_gif [EXTRACTED 1.00]
- **Dashboard Below-the-Fold Panels** — dashboard_team_budgets_panel, dashboard_recommendations_panel [EXTRACTED 1.00]

## Communities

### Community 0 - "Shadow AI Classifier"
Cohesion: 0.02
Nodes (265): classify_new_assets(), match_provider(), Provider signature matching and shadow asset classification.  This module is the, Classify shadow assets by re-running provider matching on their endpoint URLs., Update last_active_at (and updated_at) for an existing asset., Return the provider name for a given endpoint URL, or None if unknown.      Matc, Insert a new shadow asset or update last_active_at on re-detection.      Rules:, _update_last_active() (+257 more)

### Community 1 - "Provider Billing Integration"
Cohesion: 0.02
Nodes (170): _endpoint_url(), fetch_anthropic_usage(), fetch_google_usage(), fetch_openai_usage(), _paginate_usage(), Billing API parsers for OpenAI, Anthropic, and Google.  These parsers query prov, Fetch usage data from the Anthropic organization billing API.      Calls GET /v1, Google billing API detection stub.      Google Generative AI does not expose a b (+162 more)

### Community 2 - "Asset Management API"
Cohesion: 0.02
Nodes (213): approve_asset(), get_asset_detail(), get_summary(), list_assets(), list_shadow_assets(), patch_asset(), FastAPI router for asset management endpoints.  Provides CRUD-style endpoints fo, List shadow/unregistered AI endpoints requiring review.      Convenience endpoin (+205 more)

### Community 3 - "Cost Calculation Engine"
Cohesion: 0.03
Nodes (141): calculate_cost(), extract_usage_anthropic(), extract_usage_google(), extract_usage_openai(), Convert token usage from API responses into USD cost., Token counts extracted from an API response., Return total cost in USD for the given token usage.      Returns 0.0 if model is, Extract token counts from an OpenAI-format response body. (+133 more)

### Community 4 - "CLI Commands"
Cohesion: 0.03
Nodes (102): analyze(), budgets(), _build_top_table(), check_otel(), customers(), doctor(), export(), _fmt_cost() (+94 more)

### Community 5 - "Budget & Analysis Tests"
Cohesion: 0.04
Nodes (31): BudgetStatus, Current budget status and forecast., _make_config(), Tests for waste detectors and budget tracking., alerts.budget_limit_usd should map to monthly budget., _req(), TestBudgetTracker, TestComputeBudgetStatus (+23 more)

### Community 6 - "Proxy Tests"
Cohesion: 0.04
Nodes (20): _flush_tasks(), MockAsyncTransport, _openai_response(), Tests for the FastAPI proxy app., Captures the forwarded request and returns a canned JSON response., Yield control until background tasks finish., Forwarding works correctly even when there are no BurnLens headers., Proxy interceptor creates an ai_assets row for each forwarded request. (+12 more)

### Community 7 - "Test Fixtures"
Cohesion: 0.05
Nodes (50): build_google_stream(), build_openai_stream(), CapturingTransport, default_config(), drain(), drain_and_settle(), fetch_rows(), initialized_db() (+42 more)

### Community 8 - "Cost Calculation Tests"
Cohesion: 0.04
Nodes (4): Tests for cost calculation, pricing lookup, and usage extraction., TestCostCalculation, TestPricingLookup, TestUsageExtraction

### Community 9 - "Discovery API Tests"
Cohesion: 0.06
Nodes (32): discovery_app(), _insert_search_test_assets(), _insert_test_assets(), _make_asset(), _make_event(), Tests for Phase 3: API Layer — extended queries and Pydantic schema validation., Helper to create a test DiscoveryEvent with sensible defaults., Create a FastAPI test app with discovery and provider routers mounted. (+24 more)

### Community 10 - "Data Models & Queries"
Cohesion: 0.07
Nodes (46): AggregatedUsage, Dataclasses for BurnLens request records., Aggregated cost/usage stats for reporting., get_asset_by_id(), get_asset_spend_history(), get_asset_summary(), get_assets(), get_assets_count() (+38 more)

### Community 11 - "Doctor Health Checks"
Cohesion: 0.07
Nodes (46): check_anthropic(), check_database(), check_google(), check_openai(), check_proxy(), check_recent_activity(), check_token_extraction(), CheckResult (+38 more)

### Community 12 - "Codebase Audit"
Cohesion: 0.05
Nodes (46): 3-Phase Build Sequence for Unification, BurnLens Module Inventory, Config Approach Conflict (YAML vs Env Vars), Conflict Analysis (8 Incompatibilities), Fernet Encryption for API Keys at Rest, Gap Analysis (What Each Product Needs), Lemon Squeezy Billing Integration, Recommended Monorepo File Structure (+38 more)

### Community 13 - "Streaming Unit Tests"
Cohesion: 0.07
Nodes (39): anthropic_provider(), call_streaming(), openai_provider(), tests/streaming/test_streaming_unit.py  Unit tests for the streaming path — mock, test_all_content_chunks_yielded(), test_anthropic_chunks_forwarded_unmodified(), test_anthropic_stream_logged(), test_anthropic_stream_token_counts() (+31 more)

### Community 14 - "Detection Wrapper Tests"
Cohesion: 0.09
Nodes (34): FakeTransport, make_request(), Tests for burnlens.detection.wrapper — SDK transport interceptor.  Tests use moc, Transport passes HTTP status code info via the endpoint_url (or as metadata)., If upsert_asset_from_detection raises, transport still returns the response., wrap(client) mutates the client in place and returns the same object., wrap(client) without db_path uses ~/.burnlens/burnlens.db., Model is extracted from URL path using best-effort heuristics. (+26 more)

### Community 15 - "Cost Recommender"
Cohesion: 0.08
Nodes (35): analyse_model_fit(), _check_cache_opportunity(), _check_model_overkill(), _check_reasoning_overkill(), _get_pricing(), _match_overkill_model(), _match_reasoning_model(), ModelRecommendation (+27 more)

### Community 16 - "Discovery Alert Tests"
Cohesion: 0.1
Nodes (23): _make_asset(), _make_event(), _make_provider_alert(), _make_shadow_alert(), _make_spend_spike_alert(), test_check_new_provider_alerts_dispatches_correctly(), test_check_shadow_alerts_dispatches_new_events(), test_check_shadow_alerts_skips_already_fired() (+15 more)

### Community 17 - "Discovery Dashboard UI"
Cohesion: 0.13
Nodes (36): apiFetch(), buildDetailsText(), deleteView(), fetchAssets(), fetchAssetSummary(), fetchShadowAssets(), fetchTimeline(), fmtCost() (+28 more)

### Community 18 - "Report Tests"
Cohesion: 0.08
Nodes (31): _make_record(), Tests for weekly report generation., Report generation should not crash with an empty database., When email config is missing, send_report_email should raise, not silently fail., Cost by team should aggregate correctly., Cost by model should aggregate correctly., Insert sample requests and return the db path., Total cost and request count should match inserted data. (+23 more)

### Community 19 - "Phase 1 Build Spec"
Cohesion: 0.09
Nodes (32): AI Asset Registry (ai_assets table), BurnLens Cost Engine (Existing), Detection Engine (Agentless + Agent-Based), Discovery Event Log (discovery_events), Phase 1 Free Tier Pricing Strategy, Provider Signature Table (provider_signatures), Phase 1: Shadow AI Discovery & Inventory, Shadow AI Detection Logic (+24 more)

### Community 20 - "Dashboard API Routes"
Cohesion: 0.11
Nodes (29): budget(), _budget_limit(), costs_by_model(), costs_by_tag(), costs_timeline(), customers(), _db_path(), export_csv() (+21 more)

### Community 21 - "Streaming Extraction Tests"
Cohesion: 0.08
Nodes (8): Tests for SSE streaming usage extraction (burnlens/proxy/streaming.py)., Content chunks that don't match message_start/delta are skipped., Google sends cumulative totals — last chunk should be used., TestAnthropicStreamExtraction, TestGoogleStreamExtraction, TestOpenAIStreamExtraction, TestShouldBufferChunk, TestUnknownProvider

### Community 22 - "Dashboard Frontend App"
Cohesion: 0.29
Nodes (20): apiFetch(), currentPeriod(), fetchCustomers(), fetchFeatureChart(), fetchModelChart(), fetchRecommendations(), fetchRequests(), fetchSummary() (+12 more)

### Community 23 - "Alert Engine Tests"
Cohesion: 0.16
Nodes (15): _insert_asset(), _insert_event(), _insert_request(), sample_asset(), sample_event(), test_db(), test_excludes_deprecated_and_inactive_status(), test_excludes_old_requests_outside_period() (+7 more)

### Community 24 - "Dashboard Visual Assets"
Cohesion: 0.12
Nodes (19): BurnLens Dashboard Scrolled View GIF, BurnLens Dashboard Demo GIF (Docs), BurnLens Dashboard Demo GIF (Landing Page), Avg Cost Per Request KPI Card ($0.0081), Budget Usage KPI Card (No limit set), Cost By Feature Donut Chart (tagged with X-BurnLens-Tag-Feature), Cost By Model Horizontal Bar Chart, Cost Timeline Line Chart (7-day trend) (+11 more)

### Community 25 - "Patch Tests"
Cohesion: 0.12
Nodes (10): Tests for burnlens.patch — SDK monkey-patching., Tests for patch_google()., patch_google() should call genai.configure with the proxy endpoint., patch_google() should use BURNLENS_PROXY when set., An explicit proxy= argument takes precedence over env var., Tests for patch_all()., patch_all() should not raise even if google-generativeai is missing., patch_all() delegates to patch_google(). (+2 more)

### Community 26 - "Brand Identity Assets"
Cohesion: 0.25
Nodes (11): BurnLens Brand Identity, BurnLens Icon 32px (Dashboard), BurnLens Icon 32px (Docs), BurnLens Icon 512px (Docs), BurnLens Icon 512px Alt (Docs), BurnLens Icon Light 512px (Docs), BurnLens Logo 800px (Docs), BurnLens Wide Logo (Docs) (+3 more)

### Community 27 - "Phase 4 Validation Tests"
Cohesion: 0.44
Nodes (7): _make_asset(), _make_config(), _make_event(), test_exactly_200_percent_does_not_fire(), test_just_above_200_percent_fires(), test_new_provider_alert_sends_email(), test_spend_spike_alert_sends_email()

### Community 28 - "Email Digest Builder"
Cohesion: 0.27
Nodes (9): _build_digest_html(), _build_html_table(), Periodic digest email functions for BurnLens alert system.  Provides daily and w, Query AI assets inactive for more than 30 days and send a digest email.      No-, Build a simple HTML table with inline styles for email compatibility.      Args:, Build a complete HTML email body for a digest.      Args:         title:   Headi, Query model_changed events from the last 24 hours and send a digest email., send_daily_digest() (+1 more)

### Community 29 - "SDK Patching"
Cohesion: 0.4
Nodes (5): patch_all(), patch_google(), Monkey-patch SDK clients to route through the BurnLens proxy.  Usage::      impo, Configure ``google.generativeai`` to route through BurnLens.      Args:, Patch all supported SDKs to route through BurnLens.      Currently patches:

### Community 30 - "CSV Export"
Cohesion: 0.4
Nodes (5): export_to_csv(), CSV export for BurnLens request data., Convert a database row dict to a CSV-ready dict., Write rows to a CSV file with the standard BurnLens column order., _row_to_csv_dict()

### Community 31 - "Pricing Data Loader"
Cohesion: 0.4
Nodes (5): get_model_pricing(), _load_provider(), Load and look up model pricing from bundled JSON files., Load and cache pricing for a provider from its JSON file., Return pricing dict for a model, or None if not found.      Tries exact match fi

### Community 32 - "Test Data Seeder"
Cohesion: 0.83
Nodes (3): _cost(), _prompt_hash(), seed()

### Community 33 - "Package Init"
Cohesion: 1.0
Nodes (1): Detection engine package — discovers AI assets via billing APIs and proxy traffi

### Community 34 - "CLI Entry Point"
Cohesion: 1.0
Nodes (1): Entry point for `python -m burnlens`.

### Community 35 - "Report Generator"
Cohesion: 1.0
Nodes (1): Report generation for the CLI `burnlens report` command.

### Community 36 - "Discovery Docs"
Cohesion: 1.0
Nodes (2): Asset CRUD API (/api/v1/assets), Discovery Dashboard UI

### Community 37 - "Streaming Integration Edge Case A"
Cohesion: 1.0
Nodes (1): BurnLens headers must be stripped before the upstream call.

### Community 38 - "Streaming Integration Edge Case B"
Cohesion: 1.0
Nodes (1): Signal server shutdown while stream is in flight.         The finally block + cr

### Community 39 - "Project README"
Cohesion: 1.0
Nodes (1): BurnLens Project

### Community 40 - "Project Structure"
Cohesion: 1.0
Nodes (1): BurnLens Project File Structure

### Community 41 - "Roadmap README Rewrite"
Cohesion: 1.0
Nodes (1): Prompt I-3: README Quickstart + Demo GIF

### Community 42 - "Roadmap Weekly Report"
Cohesion: 1.0
Nodes (1): Prompt S-2: Weekly Cost Report Email

### Community 43 - "Discovery Dashboard Spec"
Cohesion: 1.0
Nodes (1): Discovery Dashboard

### Community 44 - "Scheduled Reports Spec"
Cohesion: 1.0
Nodes (1): Scheduled Reports (Celery Beat)

### Community 45 - "Pricing Tiers Spec"
Cohesion: 1.0
Nodes (1): Phase 4 Pricing Tiers (Enterprise $399/mo, Platform $999/mo)

## Knowledge Gaps
- **185 isolated node(s):** `Monkey-patch SDK clients to route through the BurnLens proxy.  Usage::      impo`, `Configure ``google.generativeai`` to route through BurnLens.      Args:`, `Patch all supported SDKs to route through BurnLens.      Currently patches:`, `YAML config loader with sensible defaults.`, `SMTP email configuration for sending reports.` (+180 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Package Init`** (2 nodes): `__init__.py`, `Detection engine package — discovers AI assets via billing APIs and proxy traffi`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `CLI Entry Point`** (2 nodes): `__main__.py`, `Entry point for `python -m burnlens`.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Report Generator`** (2 nodes): `reports.py`, `Report generation for the CLI `burnlens report` command.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Discovery Docs`** (2 nodes): `Asset CRUD API (/api/v1/assets)`, `Discovery Dashboard UI`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Streaming Integration Edge Case A`** (1 nodes): `BurnLens headers must be stripped before the upstream call.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Streaming Integration Edge Case B`** (1 nodes): `Signal server shutdown while stream is in flight.         The finally block + cr`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Project README`** (1 nodes): `BurnLens Project`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Project Structure`** (1 nodes): `BurnLens Project File Structure`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Roadmap README Rewrite`** (1 nodes): `Prompt I-3: README Quickstart + Demo GIF`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Roadmap Weekly Report`** (1 nodes): `Prompt S-2: Weekly Cost Report Email`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Discovery Dashboard Spec`** (1 nodes): `Discovery Dashboard`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Scheduled Reports Spec`** (1 nodes): `Scheduled Reports (Celery Beat)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Pricing Tiers Spec`** (1 nodes): `Phase 4 Pricing Tiers (Enterprise $399/mo, Platform $999/mo)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `BurnLensConfig` connect `Provider Billing Integration` to `Shadow AI Classifier`, `Cost Calculation Engine`, `CLI Commands`, `Budget & Analysis Tests`, `Proxy Tests`, `Test Fixtures`, `Discovery Alert Tests`?**
  _High betweenness centrality (0.296) - this node is a cross-community bridge._
- **Why does `RequestRecord` connect `Cost Calculation Engine` to `Provider Billing Integration`, `Asset Management API`, `CLI Commands`, `Budget & Analysis Tests`, `Data Models & Queries`, `Cost Recommender`, `Report Tests`?**
  _High betweenness centrality (0.205) - this node is a cross-community bridge._
- **Why does `AiAsset` connect `Shadow AI Classifier` to `Provider Billing Integration`, `Asset Management API`, `Discovery API Tests`, `Data Models & Queries`, `Discovery Alert Tests`?**
  _High betweenness centrality (0.153) - this node is a cross-community bridge._
- **Are the 357 inferred relationships involving `AiAsset` (e.g. with `SQLite database setup with WAL mode and async access via aiosqlite.` and `Create database directory, set WAL mode, and create tables.`) actually correct?**
  _`AiAsset` has 357 INFERRED edges - model-reasoned connections that need verification._
- **Are the 318 inferred relationships involving `DiscoveryEvent` (e.g. with `SQLite database setup with WAL mode and async access via aiosqlite.` and `Create database directory, set WAL mode, and create tables.`) actually correct?**
  _`DiscoveryEvent` has 318 INFERRED edges - model-reasoned connections that need verification._
- **Are the 272 inferred relationships involving `BurnLensConfig` (e.g. with `FastAPI application: proxy routes + dashboard serving.` and `Create the BurnLens ASGI app.      Accepts an optional *db_path* override so tes`) actually correct?**
  _`BurnLensConfig` has 272 INFERRED edges - model-reasoned connections that need verification._
- **Are the 178 inferred relationships involving `RequestRecord` (e.g. with `Request/response interception: tag extraction, forwarding, logging, cost.` and `Return cached spend for a customer, or None if cache miss/expired.`) actually correct?**
  _`RequestRecord` has 178 INFERRED edges - model-reasoned connections that need verification._