# Changelog

All notable changes to this project will be documented in this file.

This file documents both the OSS PyPI package (`burnlens`) and the
internal cloud service (`burnlens-cloud`, deployed only). Each entry is
qualified with the package it covers.

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
