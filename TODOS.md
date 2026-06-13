# TODOS

~~## Upgrade hero copy to team-visibility pitch~~

~~**What:** Update burnlens.app landing page hero to team-focused copy.~~
~~**Context:** Used this copy:~~
```
h1: See your whole team's LLM spend in one dashboard
subline: Per-feature, per-provider, per-developer. Free for solo use. $29/mo for teams.
```
~~Also update layout.tsx OG/Twitter title and description to match.~~

---

~~## Clean up team.html legacy auth (dead code)~~

~~**What:** Delete `frontend/public/team.html`. It uses old `bl_token` localStorage auth, redirects to `/signup` (which double-redirects to `/setup?intent=register`), and conflicts with the current HttpOnly-cookie auth model.~~

---

## Pre-existing test failure — GET /api/v1/assets returns 404

**What:** `tests/test_api.py::TestAssetAPI::test_list_assets_returns_paginated_response` fails with 404 instead of 200.
**Why:** The `/api/v1/assets` route appears unregistered or the test is targeting a route that no longer exists. Not caused by this branch — pre-dates fix/dead-static-signup-pages.
**Priority:** P0 — known broken test in the test suite.
**File:** `tests/test_api.py:450`, cross-check `burnlens/proxy/server.py` for the asset route registration.
**Noticed on:** fix/dead-static-signup-pages during /ship (2026-05-04)

---

## Coverage gap — PUT /settings/slack-webhook (Phase 12)

**What:** Add 4 missing test cases for the Slack webhook settings endpoint.
**Why:** The endpoint exists and works but has no unit tests: valid URL set, null clear, invalid URL 422, non-owner 403.
**Priority:** P2 — not blocking, alert engine paths are tested.
**File:** `burnlens_cloud/settings_api.py`, add to `tests/test_phase12_alerts.py`.
