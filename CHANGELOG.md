# Changelog

All notable changes to this project will be documented in this file.

This file documents both the OSS PyPI package (`burnlens`) and the
internal cloud service (`burnlens-cloud`, deployed only). Each entry is
qualified with the package it covers.

## [OSS `burnlens` v1.9.1] — 2026-07-19

### Changed
- **Semantic cache no longer caches sampled requests.** Requests with an
  explicit `temperature > 0` are neither served from nor written to the
  response cache, so sampled (non-deterministic) outputs stay varied. Requests
  that omit `temperature` (relying on the provider default) are unaffected.

### Added
- **Cache-savings visibility.** `/api/summary` now returns `cache_saved_usd`
  and `cache_hits`, and the local dashboard shows a "Cache Saved" KPI card, so
  the value the response cache already tracked is now surfaced.

## [OSS `burnlens` v1.9.0] — 2026-07-18

### Added
- **AWS Bedrock provider (Claude).** Proxy Anthropic Claude models on Amazon
  Bedrock through BurnLens. Auth is a Bedrock API key forwarded as
  `Authorization: Bearer` (SigV4 is unsupported by design — the proxy replaces
  the `host` header when forwarding, which invalidates any forwarded signature).
  The per-region endpoint is resolved from `BURNLENS_BEDROCK_REGION` at request
  time. Model is read from the `/model/{modelId}/…` path; the geo prefix
  (`us.`/`eu.`/`apac.`/`global.`) and version suffix are preserved for routing.
- **Bedrock pricing (`bedrock.json`).** Global cross-region inference rates for
  10 modern Claude models (Sonnet 5, Fable 5, Opus 4.8/4.7/4.6/4.5, Sonnet
  4.6/4.5/4, Haiku 4.5), which equal Anthropic first-party pricing — including
  cache tiers and Sonnet 5's 2026-09-01 scheduled price change. All geo
  inference profiles bill at the global rate: `calculate_cost` strips the geo
  prefix before lookup, so a new/unknown geo prefix still prices correctly
  instead of silently costing $0. Per-geo/regional (+~10%) rates are not
  modeled. Bedrock is now the 8th supported provider.

## [OSS `burnlens` v1.8.3] — 2026-07-17

### Fixed
- **The proxy bypassed most of the `Provider` interface.** An audit prompted by
  the v1.8.2 Azure bug found that six of the plugin's hooks were implemented and
  unit-tested but never actually called by `handle_request` — the interceptor
  inlined equivalent logic or re-resolved the provider from the registry by name.
  For the bundled providers the inlined behaviour matched, so there was no live
  mispricing (unlike v1.8.2), but any future provider overriding these hooks
  would have been silently ignored. Now wired to the provider instance in hand:
  - `resolve_upstream_url()` — was `f"{provider.upstream_base}{path}"`.
  - `is_streaming()` — new hook; streaming detection had Google's
    `:streamGenerateContent` hardcoded in a module helper.
  - `should_buffer_chunk()` — the streaming usage gate matched a hardcoded
    `USAGE_EVENT_INDICATORS` tuple; `split_sse_events()` now consults the
    provider, with that tuple as the no-provider fallback.
  - `headers_to_strip()` — unioned onto the `x-burnlens-*` prefix rule (the
    prefix rule stays authoritative, so git-context tags never leak upstream).
  - `extract_usage()` and `extract_usage_from_stream()` — used the provider
    instance instead of re-looking-it-up by name.

  The duplicate module-level `should_buffer_chunk()` in `streaming.py` (never
  called by the proxy) is deleted.

### Tests
- `test_provider_hooks_wired.py` drives `handle_request` with a recording
  provider and asserts each hook is actually reached, plus a meta-test that fails
  if a new `Provider` hook is added without coverage here. Verified to fail when
  a hook is un-wired. This is the class of bug that caused v1.6.1, v1.8.2, and
  this release; the guard exists so it stops recurring.

## [OSS `burnlens` v1.8.2] — 2026-07-17

### Fixed
- **Azure deployments priced at $0 through the proxy.** The interceptor never
  called `Provider.extract_model()` — it used a private helper whose path
  extraction was hardcoded to Google, so `providers/azure.py`'s deployment-name
  mapping was dead code on the proxy path. Azure's dotless `gpt-35-turbo`
  spelling and any deployment mapped via `BURNLENS_AZURE_DEPLOYMENTS` (e.g.
  `prod-gpt4o=gpt-4o`) reached the pricing lookup unmapped and cost **$0.00**
  per request instead of $0.50 and $2.50/MTok respectively. The provider-level
  unit tests passed throughout because they called the provider object directly
  and never routed through the interceptor.

  These two behaviours were previously documented as known ceilings of the Azure
  provider. They were not ceilings — the code to handle them shipped in v1.6.1
  and was simply never wired up.

  The interceptor now calls `provider.extract_model(...)`, so each provider owns
  its own extraction (body, path, or alias map) as the plugin interface always
  intended. `_extract_model` and `_extract_model_from_path` are deleted.
  Regression tests drive `handle_request` end-to-end and assert exact costs.

  Same class of bug as the v1.6.1 `pricing_key` fix: an abstraction existed, the
  interceptor bypassed it, and it worked by accident for the providers where the
  model sits in the request body.

## [OSS `burnlens` v1.8.1] — 2026-07-17

### Added
- **Date-scheduled pricing.** A model entry can carry a `scheduled` list of dated
  rate changes (`{"effective": "YYYY-MM-DD", ...}`); the resolver applies the
  active tier against the current date automatically — no code edit or release
  needed when the date arrives. Used for **Claude Sonnet 5**, which now switches
  from its introductory $2/$10 to the $3/$15 sticker rate on 2026-09-01 on its
  own (previously a manual follow-up that would silently under-report ~33% if
  forgotten). Scans of old logs price at the current tier (the wheel carries one
  live rate anyway).

## [OSS `burnlens` v1.8.0] — 2026-07-17

### Added
- **`burnlens pricing` command.** Shows the bundled model pricing table
  ($/1M tokens) for all providers, or exports it: `--csv` writes CSV to stdout,
  `--output/-o FILE` writes to a file. Backed by a new `cost.pricing.all_pricing()`
  helper so the table and CSV share one source.

## [OSS `burnlens` v1.7.5] — 2026-07-17

### Added
- **Current GA realtime-audio models.** `gpt-realtime-2.1` (text $4/$24, audio
  $32/$64, cached $0.40) and `gpt-realtime-2.1-mini` (text $0.60/$2.40, audio
  $10/$20, cached $0.30), verified against OpenAI's live pricing page. These
  replaced the `*-audio-preview` / `gpt-4o-realtime-preview` entries on OpenAI's
  side and previously matched no pricing entry — i.e. all `gpt-realtime-2.1*`
  traffic was silently tracked at $0. Legacy preview entries are retained for
  historical scan data.

## [OSS `burnlens` v1.7.4] — 2026-07-17

### Fixed
- **Codex scan double-billed reasoning tokens** (same class of bug as v1.7.3, in
  the `codex` scanner). Verified against real `~/.codex` sessions that Codex
  mirrors the OpenAI Responses API — `output_tokens` is *inclusive* of
  `reasoning_output_tokens` (`total_tokens == input + output`). The scanner set
  `output_tokens` to the inclusive value and also billed reasoning separately, so
  every scanned Codex turn with reasoning over-charged. The reader now stores
  `output` disjoint from `reasoning` (`output = output − reasoning`). Verified on
  live sessions (e.g. raw output 237 / reasoning 81 → stored 156 + 81).

## [OSS `burnlens` v1.7.3] — 2026-07-17

### Fixed
- **Reasoning tokens double-billed on OpenAI.** OpenAI reports `completion_tokens`
  *inclusive* of `reasoning_tokens`, but the proxy extractors set
  `output_tokens = completion_tokens` while also billing `reasoning_tokens`
  separately — so reasoning was charged twice (e.g. an o1 call with 200 of 1000
  output tokens as reasoning cost `$0.072` instead of `$0.060`). Extractors now
  keep `output_tokens` disjoint from `reasoning_tokens` (matching the Gemini/Codex
  scanners and the storage schema, where the two sum to the total). Fixed on the
  non-streaming, streaming, and stream-chunk paths.

## [OSS `burnlens` v1.7.2] — 2026-07-17

### Added
- **Non-token billing.** The cost calculator now prices multiple line items per
  request beyond plain text tokens:
  - **Audio-modality tokens** are repriced at a dedicated `audio_input_per_million`
    / `audio_output_per_million` rate instead of the text rate (they're a subset of
    the reported input/output tokens). Wired end-to-end through the OpenAI
    extractor and both streaming paths; added `gpt-4o-audio-preview`,
    `gpt-4o-mini-audio-preview`, and `gpt-4o-realtime-preview` with audio rates.
    Fixes ~16× under-reporting of audio traffic on those models.
  - **Flat per-unit fees** via an optional `unit_prices` map on any model entry
    (USD-per-unit) paired with `TokenUsage.units` — e.g. per web-search / tool
    call, per image, per audio-second. Prices any non-token line item a caller
    populates. Models with no audio/unit rates are unchanged (audio falls back to
    the text rate; no `units` → no extra cost).

## [OSS `burnlens` v1.7.1] — 2026-07-17

### Added
- **Current text/chat model pricing.** Added OpenAI GPT-5.4 through GPT-5.6,
  Gemini 3.5 Flash, Claude Mythos 5, Mistral Medium 3.5 and Small 4, and the
  current Together chat catalog.

### Fixed
- **Provider aliases and rates.** Refreshed Mistral `-latest` aliases, Groq
  GPT-OSS 20B, and Together Llama 3.3 70B pricing against provider catalogs.

## [OSS `burnlens` v1.7.0] — 2026-07-17

### Added
- **Current model pricing.** Added GPT-5.2, Gemini 3.1 Flash-Lite, Groq Qwen,
  Mistral Large 3, and Together GPT-OSS pricing; Sonnet 5 uses its $2/$10
  introductory rate through August 31, 2026.

### Changed
- **Recommendations and downgrade routing** now use the bundled pricing tables
  and current model targets, preventing recommendations to retired Claude 3 Haiku.

## [OSS `burnlens` v1.6.2] — 2026-07-14

### Added
- **Azure OpenAI deployment mapping.** Resolve custom/arbitrary Azure deployment names
  to OpenAI models for accurate pricing using the `BURNLENS_AZURE_DEPLOYMENTS` environment
  variable (e.g. `prod-gpt4o=gpt-4o,cheap=gpt-4o-mini`).
- **Azure OpenAI aliases.** Automatically map Azure's dotless `gpt-35-turbo` deployment name family
  to canonical `gpt-3.5-turbo` pricing keys in `openai.json`.

## [OSS `burnlens` v1.6.1] — 2026-07-14

### Fixed
- **Azure requests no longer cost $0.** Pricing lookups (`get_model_pricing`,
  `get_pricing_version`) received `provider.name`, but pricing files are keyed
  by `pricing_key`. For the six providers where those match it worked by
  accident; Azure (name `azure`, pricing_key `openai`) had no `azure.json`, so
  every Azure request/record cost $0. The pricing layer now resolves
  name→pricing_key via the provider registry, with pass-through for scan
  providers (`cursor`, etc.) that aren't registered.

## [OSS `burnlens` v1.6.0] — 2026-07-14

### Added
- **Azure OpenAI proxy provider (beta).** Azure serves the OpenAI models
  over the same chat-completions wire format, so it reuses the OpenAI
  parser via `/proxy/azure`. Point the `AzureOpenAI` client's
  `azure_endpoint` at the proxy path (`burnlens start` exports
  `AZURE_OPENAI_ENDPOINT`) and set `BURNLENS_AZURE_ENDPOINT` to your real
  resource URL (`https://<resource>.openai.azure.com`). The request's
  deployment name is used as the model; pricing reuses `openai.json`, so
  a deployment named after its model (e.g. `gpt-4o`) resolves cost —
  arbitrarily-named deployments price at $0 until a name→model map lands.

## [OSS `burnlens` v1.5.0] — 2026-07-14

### Added
- **Groq, Together, and Mistral proxy providers (beta).** All three speak
  the OpenAI wire format, so they reuse the OpenAI parser with their own
  proxy paths (`/proxy/groq`, `/proxy/together`, `/proxy/mistral`),
  upstream URLs, and pricing tables. `burnlens start` now also exports
  `GROQ_BASE_URL`; Together and Mistral clients point their `base_url`
  at the proxy path.

## [OSS `burnlens` v1.4.3] — 2026-07-14

### Fixed
- **Anthropic pricing corrected.** All Claude Opus 4.x entries carried
  Claude-3-Opus-era rates ($15/$75 per MTok) instead of the actual
  $5/$25 — Opus 4.x requests were over-costed 3×. Claude Haiku 4.5
  corrected from $0.80/$4 to $1/$5.
- **Missing models no longer cost $0.** Added `claude-fable-5`,
  `claude-opus-4-8`, `claude-sonnet-5`, the gpt-5 family
  (`gpt-5` / `gpt-5-mini` / `gpt-5-nano`), the gpt-4.1 family, and
  `o3-pro`. Previously these resolved to no pricing entry and every
  request/scan record for them showed $0.
- `o3` updated to its post-cut $2/$8 rates; `gemini-2.5-flash` corrected
  to $0.30/$2.50; added `gemini-2.5-flash-lite`.

### Changed
- README and landing-page roadmap wording no longer references
  long-obsolete "v0.2 / v0.3" milestones.

## [OSS `burnlens` v1.4.2] — 2026-07-13

### Fixed
- **Cloud sync never reached the backend.** The default (and documented)
  ingest endpoint was `https://api.burnlens.app/api/v1/ingest` — a path
  that has never existed on the backend, so every sync batch 404'd
  (silently, by fail-open design). The default is now the real route
  (`/v1/ingest`), and `push_batch` rewrites the stale `/api/v1/ingest`
  suffix from existing user configs.
- Sync requests now send `X-Requested-With`, so they pass backends
  running the CSRF middleware without the machine-endpoint exemption.

### Cloud (`burnlens-cloud`, deployed only)
- **CSRF middleware no longer blocks machine-to-machine endpoints.**
  The hardening middleware 403'd any POST without `X-Requested-With`,
  which broke `/v1/ingest` (OSS sync), `/cron/evaluate-alerts` (the
  hourly GitHub Actions cron failed with 403 for days), and would have
  broken `/billing/webhook` (Paddle). Those paths carry their own
  credential and are never cookie-authenticated, so CSRF does not apply.
- **`api_keys.paused_at` schema drift repaired.** Production tables
  created before `paused_at` joined the CREATE statement lacked the
  column, making every API-key lookup raise `UndefinedColumnError` —
  ingest returned 500 for all keys. Startup migration now adds the
  column idempotently.

## [OSS `burnlens` v1.4.1] — 2026-07-13

### Changed
- **Accurate provider claims on PyPI.** The published package description
  said Azure OpenAI, AWS Bedrock, and Groq appear "in one unified view";
  those providers are on the roadmap, not shipped. The description now
  matches the provider support table: OpenAI, Anthropic, and Google are
  the supported providers today.
- **Added `CONTRIBUTING.md`** (the README already linked to it) covering
  dev setup, the fail-open / streaming-passthrough ground rules, and the
  provider plugin guide.
- Repo hygiene: internal planning and handoff documents are no longer
  tracked in the public repository.

## [OSS `burnlens` v1.4.0] — 2026-05-27

### Added
- **Saved Views on the discovery dashboard.** Name and persist a set of
  filters (provider, status, risk, team, date, search, sort) to `localStorage`,
  then reload or delete them from the toolbar.

### Fixed
- **The discovery dashboard (`/ui/discovery`) shipped five panels that never
  rendered.** The HTML/CSS for the Provider Breakdown chart, Shadow AI Alerts,
  the Discovery Timeline, the team filter, and the Unassigned KPI were present,
  but `discovery.js` drove none of them — they sat on "Loading…" or blank
  indefinitely. All are now wired to existing endpoints: the provider doughnut
  from `/api/v1/assets/summary`, shadow cards from
  `/api/v1/assets?status=shadow` (with per-card approve / assign-team), the
  timeline from `/api/v1/discovery/events`, and the team list + Unassigned count
  derived client-side from the asset list. A guarded 30s auto-refresh honors the
  header's refresh indicator without clobbering in-progress edits. (No backend
  change, so the frontend↔API contract snapshot is unaffected.)

## [OSS `burnlens` v1.3.1] — 2026-05-27

### Fixed
- **`/ui/discovery` returned 404 on FastAPI 0.115.x.** The route's
  `-> FileResponse` return annotation (a string under
  `from __future__ import annotations`) was resolved against module globals,
  but `FileResponse` was only imported locally inside `get_app()`. On the pinned
  FastAPI 0.115.0, `get_type_hints()` raised `NameError`, which the surrounding
  `try/except` swallowed — silently dropping the discovery UI route and its
  static mount. Now imported at module level. (Surfaced by running the test
  suite under prod-pinned deps; masked locally by a newer FastAPI.)
- **Asset API responses dropped the `tags` field.** `_asset_to_dict` omitted
  `tags`, so the persisted per-asset tags never reached the list / get / patch /
  discovery endpoints. Now serialized.
- **Spend-spike alert fired at exactly 200% of the 30-day average.** The guard
  used `< 2.0`, but the intent (and docstring) is to fire only *above* 200%.
  Changed to `<= 2.0` so exactly 200% no longer alerts.

## [Frontend `burnlens.app`] — 2026-05-26

### Fixed
- **Every authenticated page crashed for any workspace that had usage data**
  (found by `/investigate` on 2026-05-26). The dashboard read `total_cost` /
  `api_calls` / `cost` / `latency_ms`, but the cloud API serializes
  `total_cost_usd` / `request_count` / `cost_usd` / `duration_ms` (and `tags`
  as an object). The wrong field names resolved to `undefined`, and the
  unguarded `.toFixed()` / `.toLocaleString()` calls threw a `TypeError`.
  Because the throw happened in `RightPanel` (shared dashboard chrome), it took
  down `/dashboard`, `/api-keys`, and every Shell-wrapped page — but only for
  workspaces with data, so empty QA accounts never surfaced it. Aligned all six
  consumers (RightPanel, Overview, By model, By feature, By customer, By team)
  to the real API field names and added `?? 0` guards so malformed data
  degrades to `$0` instead of a white screen.

## [Cloud `burnlens-cloud` v1.2.1] — 2026-05-25

### Fixed
- **Cloud ingest accepted nothing the OSS proxy sent — the product's core data
  path was 100% broken** (found by live QA on 2026-05-25). Three stacked bugs
  meant every sync batch from the `burnlens` package was silently dropped:
  - **Wire-format mismatch (was HTTP 422).** The OSS proxy sends the API key in
    the `X-API-Key` header and posts `{"records":[...]}`, but `/v1/ingest`
    required `api_key` inside the JSON body. `ingest()` now reads the key from
    the `X-API-Key` header or the body (body wins), and 401s only when neither is
    present. `IngestRequest.api_key` is now optional. This recovers every
    already-installed proxy (1.0–1.3) in place, no client upgrade required.
  - **JSONB encoding 500 on every non-empty batch.** asyncpg has no built-in
    encoder for Python `dict` ↔ `JSONB`, so the bulk insert of `tags` raised and
    failed the whole batch. The connection pool now registers a `jsonb` codec
    (`json.dumps`/`json.loads`) via `init=`.
  - **Attribution tags silently dropped.** The proxy flattens tags to
    `tag_feature` / `tag_team` / `tag_customer` at the top level; Pydantic
    discarded them, erasing per-feature/team/customer cost attribution. A
    `model_validator` re-nests the flat keys into `tags` (an explicit `tags`
    object still wins).

### Tests
- `tests/test_ingest_wire_format.py`: 8 regression tests pinning the exact OSS
  proxy wire shape (header auth, body auth, 401-not-422, flat-tag lifting,
  explicit-tags-win, JSONB codec wiring).
- Updated `tests/test_cloud_sync.py`, `tests/test_cloud_sync_e2e.py` to assert
  the current wire format (API key in `X-API-Key` header; `status_code` is
  intentional operational metadata, `request_path` remains stripped for privacy).
- Fixed a stale `tests/test_keys.py` CLI test that hung the suite on an empty
  hidden-prompt under the test runner.

## [PyPI `burnlens` 1.3.0] — 2026-05-25

### Fixed
- **Google model downgrade now rewrites the URL path** (ROUTE-08). When
  `decide_route()` selects a downgrade model for a Google Generative Language API
  request, the outbound request URL path is rewritten to reflect the downgrade
  model name (in addition to the existing body-field rewrite from v1.2). Closes
  the known v1.2 limitation where Google requests still hit the original-model
  endpoint despite body rewriting. OpenAI and Anthropic are unaffected — their
  model identifier already lives in the body, not the URL.

### Added
- **`Provider.rewrite_path_for_routing()` hook** — polymorphic, opt-in path
  rewriter on the Provider plugin base class. Default is a no-op; the Google
  provider implements it. Future providers can add path rewriting without core
  changes.
- **`DOWNGRADE_MAP` suffix normalization** — Google model keys like
  `models/gemini-1.5-flash` are normalized to suffix form so URL-path matching
  is single-source-of-truth.

## [OSS `burnlens` — bugfix] — 2026-05-04

### Fixed
- **Asset API routing** — `/api/v1/assets` router was double-prefixed (absolute paths
  in router + prefix on include), causing all asset endpoints to return 404. Fixed by
  using relative paths; added missing `GET /{id}`, `PATCH /{id}`, and
  `POST /{id}/approve` endpoints, renamed `"assets"` response key to `"items"` to
  match the API contract, and wired `date_since` filter through to the query layer.
- **date_since validation** — `GET /api/v1/assets?date_since=` now rejects non-ISO
  date strings with a 422 rather than silently returning wrong results.

---

## [PyPI `burnlens` 1.1.0] — 2026-05-03

### Added
- **Offline session scanners** — four new `burnlens scan <provider>` commands import
  coding-agent session costs from disk without replaying any traffic. Re-runs are
  idempotent (partial unique index on `source` + `request_id`). Scanned rows appear
  alongside live-proxy traffic in the dashboard, `burnlens top`, and exports.
  - `burnlens scan claude` — reads Claude Code JSONL session files from
    `~/.claude/projects/` and attributes cost by project, session, and model.
  - `burnlens scan cursor` — reads the Cursor IDE SQLite bubble database from
    `~/.cursor/` and maps composer/chat turns to cost records.
  - `burnlens scan codex` — reads OpenAI Codex JSONL session files from
    `~/.codex/sessions/` (703 sessions, 88k events in testing).
  - `burnlens scan gemini` — reads Gemini CLI JSON/JSONL chat files from
    `~/.gemini/tmp/<project>/chats/` (64 sessions, 5806 turns in testing).
- **Pricing: gpt-5-codex** — `$1.25 / $10.00` per million in/out tokens.
- **Pricing: gemini-3-flash-preview** — `$0.50 / $3.00` per million in/out tokens.
- **Pricing: gemini-3.1-pro-preview** — `$2.00 / $12.00` per million in/out tokens.

---

## [Cloud `burnlens-cloud` v1.2.0] — 2026-05-02

### Added
- **Phase 11 — Auth Essentials**: Full email-verified auth flow for the cloud dashboard.
  - `auth_tokens` table for password-reset and email-verification tokens; `email_verified_at`
    column on `users` tracks first confirmation.
  - 4 new auth endpoints: `POST /auth/reset-password`, `POST /auth/reset-password/confirm`,
    `POST /auth/verify-email`, `POST /auth/resend-verification`.
  - `email_verified` claim in every JWT; login and signup responses surface the flag.
  - Rate-limit rules for reset-password (3/900s) and resend-verification (3/900s).
  - 6 transactional email templates (welcome, verify-email, reset-password, password-changed,
    invitation, payment-receipt) wired to SendGrid via a typed `TEMPLATE_REGISTRY`.
  - `send_invitation_email` migrated from inline HTML to the file-based template system.
- **Phase 11 — Frontend Auth Pages**: Zero-JavaScript-dependency auth UX shipped into the Next.js app.
  - `/verify-email` page — calls the backend on mount, sets `emailVerified` in localStorage on success.
  - `/reset-password` page — token-based password reset form with full validation.
  - Forgot-password flow integrated into `/setup` tab switcher.
  - `emailVerified` surfaced in `useAuth` + `AuthSession` for downstream gating.
  - `BillingStatusBanner` shows a persistent email-verification nudge with a "Resend" button
    for users who have not confirmed their address.
- **Phase 12 — Cloud Alert Engine**: Hourly spend-alert evaluation for non-free workspaces.
  - `alert_rules` and `alert_events` tables with default 80% monthly-cap rule seeded on workspace creation.
  - `alert_engine.py`: evaluates all active rules, dispatches via email and/or Slack, records outcome
    in `alert_events`, and deduplicates within a 24-hour window per rule.
  - SSRF-safe Slack dispatch: validates `hooks.slack.com` hostname via `urlparse` (not `startswith`).
  - `POST /cron/evaluate-alerts`: bearer-auth cron endpoint with HMAC-wrapped constant-time secret
    comparison; fail-open — always returns `{"evaluated": N, "fired": M}`.
  - `PUT /settings/slack-webhook`: owner-only endpoint to configure per-workspace Slack alerts;
    sets `channel = 'both'` when a URL is provided, reverts to `'email'` when cleared.
  - GitHub Actions workflow triggers the cron endpoint hourly from Railway.

### Fixed
- **Frontend**: Removed dead `public/signup.html` and `public/dashboard.html` static auth pages.
- **Frontend**: Mobile hamburger nav with `lp-` CSS-prefixed classes to avoid dashboard collision.
- **Frontend**: Register form disables submit until name/email filled and password ≥ 8 chars.
- **Frontend**: Branded `/not-found` 404 page; `/login` and `/pricing` redirect correctly.
- **Frontend**: OG/Twitter descriptions tightened for solo-use positioning.
- **Cloud**: `/billing/summary` 500 for fresh workspaces — fixed pool-import binding.
- **Cloud**: CORS headers now emitted on unhandled 500s; preflight `max_age` capped at 60s.
- **Security**: HTML-escape all user-supplied variables in `send_welcome_email` and
  `send_payment_receipt_email` (XSS fix — matched existing pattern in `send_invitation_email`).
- **Security**: Slack webhook URL no longer stored in `alert_events.recipient` audit column.
- **bcrypt**: Bumped from 4.1.3 → 5.0.0 to match `uv.lock`.

### Tests
- `tests/test_phase11_auth.py`: 729-line suite covering all 7 new auth endpoints and JWT claims.
- `tests/test_phase12_alerts.py`: 13 tests covering alert engine, cron auth, and Slack SSRF guard.
- `tests/test_cors_preflight.py` and `tests/test_cors_on_500.py`: regression tests for CORS hardening.
- `tests/test_plans_pool_binding.py`: regression test for the billing-summary pool-import fix.
- `frontend/tests/e2e/phase11_auth.spec.ts`: Playwright E2E for signup, login, forgot-password,
  and email-verification flows.

## [Unreleased — PyPI `burnlens`] — milestone 0.2.0

### Added
- **CODE-2**: Per-API-key daily hard cap — stop a leaked or runaway
  API key before it burns the month's budget:
    - New `api_keys` table stores SHA-256-hashed keys with a human label
      and optional `daily_cap_usd`. Keys are never stored in plaintext.
    - `burnlens key register|list|remove` CLI manages labels and caps;
      the proxy interceptor resolves the inbound `Authorization:` key to
      its label and stamps `tag_key_label` on every logged request.
    - TZ-aware daily reset (UTC midnight by default, configurable via
      `api_key_budgets.reset_tz` in `burnlens.yaml`). Per-key spend is
      cached in-process and invalidated on each new log write.
    - 50 % / 80 % / 100 % alerts fire to terminal (and Slack if
      configured) with one alert per key per threshold per day.
    - At 100 %, the proxy returns HTTP 429 with a JSON
      `{"error": "burnlens_daily_cap_exceeded", ...}` body until the
      next reset — fail-closed for spend, fail-open for everything else.
    - New `GET /api/keys-today` endpoint + dashboard panel "API keys
      today" shows today's spend and cap status per key.
    - New `burnlens keys` CLI prints today's per-key roll-up.
    - End-to-end demo: `bash docs/demo_killswitch.sh` registers a key,
      sets a 1-cent cap, makes a real request, and demonstrates the
      kill-switch tripping.

### Tests
- 91 new tests across 8 files cover key store, CLI, label
  interceptor, label migration, daily-cap enforcement, alerts,
  `/api/keys-today` endpoint, and the demo script. Combined with
  CODE-1's 30 tests, the v0.2.0 milestone adds 121 passing tests.

## [PyPI `burnlens` 1.0.1] — 2026-04-28

### Fixed
- **CRITICAL**: 1.0.0 published a broken wheel that omitted
  `burnlens/cost/`, `burnlens/proxy/`, `burnlens/cli.py`, and
  `burnlens/__main__.py` — every install was non-functional and any
  `burnlens` console-script invocation failed with `ModuleNotFoundError`.
  1.0.1 ships the complete OSS package: proxy server, request
  interceptor, SSE streaming handler, cost calculator, pricing data,
  CLI, dashboard static assets, telemetry, and reports.
- **I-1**: Google and Anthropic streaming responses no longer log
  `0 tokens / $0.00`. Root causes addressed: `_is_streaming()` now
  detects Google's `:streamGenerateContent` URL scheme; `accept-encoding`
  is stripped from forwarded requests so SSE bytes aren't gzipped;
  Google `_extract_google_stream` parses both SSE `data: {…}` lines and
  raw NDJSON; SSE buffer is reassembled on `\n\n` boundaries before
  extraction so TCP-fragmented usage events aren't dropped.

### Added
- **I-2**: `burnlens export` CSV command gains `--repo / --dev / --pr`
  filters and matching `repo / dev / pr / branch` columns. Cost cells
  now format as `f"{cost:.8f}"` instead of scientific notation
  (e.g. `0.00005120` instead of `5.12e-05`).
- **CODE-1**: Git-aware auto-tagging — every proxied request can now
  be attributed to a PR / repo / dev / branch with zero manual headers:
    - `burnlens run -- <cmd>` wraps any command, reading
      `read_git_context(cwd)` and exposing `BURNLENS_TAG_REPO/DEV/PR/BRANCH`
      env vars + `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` to the child.
    - The proxy's `_extract_tags` falls back to those env vars
      per-request when the corresponding `X-BurnLens-Tag-*` header is
      absent.
    - Schema migration adds `tag_repo / tag_dev / tag_pr / tag_branch`
      columns + `idx_requests_tag_{repo,dev,pr}` indices to the
      `requests` table (idempotent via `PRAGMA table_info`).
    - New CLI groupers: `burnlens prs --days N --repo X`,
      `burnlens devs`, `burnlens repos` — top-20 cost tables.
    - New JSON endpoint `GET /api/cost-by-pr?days=7&repo=X`.
    - New dashboard panel "Top PRs by cost" with click-to-filter
      Recent Requests via the indexed `tag_pr` column.

### Tests
- 197 OSS tests pass on this release: streaming (39), cost (44),
  storage (44), export (9), git_context (16), cli_wrapper (6),
  proxy_env_fallback (5), and integration suites.

## [burnlens-cloud 1.0.1] — 2026-04-15

### Fixed
- Alert deduplication now persists across restarts (was in-memory only)
- Discovery events archival job added — 90-day retention, runs nightly at 2 AM UTC
- Asset table now sorts server-side — sort is global across all pages, not per-page
- Monthly spend KPI now aggregates all assets, not just the current page
- Google billing API integration — Vertex AI and Gemini assets now detected via billing API

### Tech Debt Resolved
- FIX-01: DB-backed fired_alerts table replaces in-memory sets
- FIX-02: discovery_events_archive table with nightly migration job
- FIX-03: sort_by and sort_dir params on GET /api/v1/assets
- FIX-04: get_total_spend_all_assets() query bypasses pagination for KPI
- FIX-05: GoogleBillingParser implements Cloud Billing v1 REST API

## [1.0.0] — 2026-04-15

- Initial release
