# TODOS

## Upgrade hero copy to team-visibility pitch

**What:** Update burnlens.app landing page hero to team-focused copy.
**Why:** Design doc validated team-visibility as the core value prop for tech leads managing multi-provider LLM spend. Solo-use copy is live now to avoid advertising features that don't exist yet (team invitations). Once Phase 11 ships team invitations, flip the copy.
**Pros:** Speaks directly to the paying ICP (3-10 person team, $500+/mo LLM spend). The concierge outreach pitch will reference team visibility — landing page should match.
**Cons:** One more PR to coordinate with Phase 11 launch.
**Context:** Use this copy:
```
h1: See your whole team's LLM spend in one dashboard
subline: Per-feature, per-provider, per-developer. Free for solo use. $29/mo for teams.
```
Also update layout.tsx OG/Twitter title and description to match.
**Depends on:** ~~Phase 11 team invitations live~~ — **Phase 11 shipped 2026-05-02, this is now unblocked.**

---

## Clean up team.html legacy auth (dead code)

**What:** Delete `frontend/public/team.html`. It uses old `bl_token` localStorage auth, redirects to `/signup` (which double-redirects to `/setup?intent=register`), and conflicts with the current HttpOnly-cookie auth model.
**Why:** Dead code that will confuse anyone landing on it and misrepresents the current auth model. The double-redirect chain is also sloppy.
**Pros:** Removes confusion, simplifies auth surface.
**Cons:** None — nobody should be landing on team.html in the current flow.
**Context:** The file is at `frontend/public/team.html`. Check `vercel.json` for any remaining rewrites referencing it before deleting.
**Depends on:** Nothing — standalone cleanup.

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
