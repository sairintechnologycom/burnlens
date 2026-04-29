# Backlog: Frontend API gaps (stubbed 2026-04-19)

Discovered via live console on burnlens.app. Frontend ships UI for features whose
backends don't exist. `burnlens_cloud/stubs_api.py` returns empty-shape responses
so the UI stops 404-ing and crashing on `.slice` / `.filter`. Each item below
must replace its stub before the feature is truthfully "live."

## Items

### 1. Connections (`/api/v1/connections`)
- **Frontend:** `frontend/src/app/connections/page.tsx` (list, create, delete).
- **Stub:** returns `[]` on GET; 501 on POST/DELETE.
- **Real work:** design `connections` table (workspace_id, provider, credentials,
  status, created_at), CRUD router, encrypt credentials via `encryption.py`.
- **Blocks:** Connections page on burnlens.app being functional.

### 2. Recommendations (`/api/v1/recommendations`)
- **Frontend:** `/savings` and `/waste` pages.
- **Stub:** returns `[]`.
- **Real work:** recommendation engine — scan `request_records` for duplicate
  prompts, over-sized models, prompt bloat; write to a `recommendations` table
  or compute on the fly. Mirror the local `burnlens/analysis/waste.py` logic.

### 2b. Waste alerts (`/api/v1/waste-alerts`)
- **Frontend:** `RightPanel` (home) and `/waste` page — both expect an array.
- **Stub:** returns `[]` (was `{findings: [...]}`, which crashed the client
  with `t.slice is not a function`).
- **Real work:** same detector engine as #2, but alert-shaped records.

### 3. Sync trigger (`POST /api/v1/sync/trigger`)
- **Frontend:** Settings → "Sync now" button.
- **Stub:** returns `{status: "ok"}` — a no-op ack.
- **Real work:** decide semantics. Sync is push-based from the user's proxy;
  the cloud cannot "pull" by design. Options: (a) remove the button,
  (b) repurpose as "re-run aggregations on latest data," (c) turn into a
  signal the proxy polls for.

### 4. Team budgets (`GET /api/team-budgets`)
- **Frontend:** `/budgets` page.
- **Stub:** returns `[]`.
- **Real work:** team budgets live in `burnlens.yaml` on the user's machine and
  don't exist in the cloud schema yet. Either (a) upload the config during
  sync, or (b) add cloud-side team budget CRUD.

### 5. Budget alias (`GET /api/budget`)
- **Frontend:** `/budgets` page.
- **Stub:** returns zeroed budget status.
- **Real work:** either update the frontend to call `/api/v1/budget` (already
  implemented in `dashboard_api.py:321`) or wire this alias to the same logic.
  Preferred: fix the frontend path.

## Non-bugs (intentional)

- **"Upgrade to Cloud" button disabled** — `settings/page.tsx:382-390` hardcodes
  `disabled` with tooltip "Coming soon — checkout ships in Phase 8."
  `/billing/checkout` exists in `billing.py:148` and can be wired when Phase 8
  starts.
- **Cloud Sync status pill reads "Enabled" on Free tier** — hardcoded string
  in `settings/page.tsx:157`, not driven by real state.

## Related console errors

`t.slice is not a function` / `n.filter is not a function` in the minified JS
are downstream of 404s returning error JSON where the client expected arrays.
Stubs eliminate these; defensive array-shape guards on the client would be
belt-and-braces.
