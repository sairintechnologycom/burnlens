# Changelog

All notable changes to this project will be documented in this file.

## [1.0.1] — 2026-04-15

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
