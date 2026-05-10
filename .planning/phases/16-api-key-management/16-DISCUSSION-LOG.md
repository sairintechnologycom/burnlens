# Phase 16: API Key Management - Discussion Log

**Date:** 2026-05-10
**Mode:** discuss (default)

> Human-readable record of the discussion. NOT consumed by downstream agents — see `16-CONTEXT.md` for the canonical decisions list.

## Areas Discussed

### Area 1 — Viewer-role scoping (APIKEY-05)
**Question:** APIKEY-05 says a viewer sees "only their own key". Today keys are workspace-scoped and tagged with `created_by_user_id`, but viewers don't get a key auto-issued. Which scoping model do you want?

**Options presented:**
- Filter by `created_by_user_id` (Recommended)
- Personal-key auto-issue per viewer
- Read-only viewers (no create/revoke at all)

**User selected:** Filter by `created_by_user_id`.

**Rationale:** Reuses an existing column, no schema change, no invite-flow detour. Viewers retain self-service for their own keys.

---

### Area 2 — last_used_at tracking (APIKEY-01)
**Question:** APIKEY-01 requires a `last_used_at` per key. Auth happens on every ingest call (high QPS) — how do we track without slowing the hot path?

**Options presented:**
- Throttled UPDATE on auth (≥60s since last) (Recommended)
- Aggregate from `usage_records` table
- Background sweeper every N minutes

**User selected:** Throttled UPDATE on auth.

**Rationale:** Fresh data, ≤1 write per key per minute, no scheduler dependency, no schema additions to `usage_records`.

---

### Area 3 — Label vs scope note (APIKEY-04)
**Question:** APIKEY-04 says "label or scope note" — one field or two?

**Options presented:**
- One field — extend `name` (Recommended)
- Two fields — add `scope_note` column
- Tags array

**User selected:** One field — extend `name` (raise max_length to 128).

**Rationale:** Simplest schema impact, simplest UX, no consumer for richer fields exists in v1.3.

---

### Area 4 — AUTH-08 fix shape
**Question:** Today resend-verification takes `email` from request body; frontend pulls it from `localStorage.burnlens_owner_email` (null for API-key signups). How to close the bug?

**Options presented:**
- Drop `email` from the request, read from JWT (Recommended)
- Keep `email` optional, prefer JWT when present
- Frontend-only fix — fall back to `/auth/me`

**User selected:** Drop `email` from the request, read from JWT.

**Rationale:** Cleanest fix; eliminates the email-in-body API surface that caused the bug; forces auth on a flow that always required it logically.

---

### Area 5 — Page placement
**Question:** ROADMAP success-criterion #1 names `/api-keys`. ApiKeysCard currently lives on `/settings`. What's the placement?

**Options presented:**
- New `/api-keys` page; keep card on `/settings` (Recommended)
- New `/api-keys` page; remove card from `/settings`
- No new route — keep everything on `/settings`

**User selected:** New `/api-keys` page; keep card on `/settings`.

**Rationale:** Matches the success criterion verbatim; preserves muscle memory for users who've been managing keys from settings; keeps full lifecycle UI in one canonical place.

---

### Area 6 — Revoke confirmation UX (APIKEY-03)
**Question:** Revoke is permanent and immediate. What confirmation UX?

**Options presented:**
- Modal confirm with last4 + name shown (Recommended)
- Type-the-name to confirm
- Inline one-click + 5-second undo toast

**User selected:** Modal confirm with last4 + name shown.

**Rationale:** Matches the "no grace period" criterion (no restore endpoint needed); standard destructive-action pattern; prevents misclicks without typing friction.

---

## Deferred Ideas
- Per-key undo/restore endpoint
- `tags` array on api_keys
- Auto-issued personal key per viewer on invite acceptance
- `api_key_id` column on `usage_records` (potential Phase 18 enabler)
- Background sweeper for `last_used_at` (revisit only on contention)

## Claude's Discretion
- Sidebar icon for "API Keys" entry
- Relative-time helper choice (probably reuse existing project helper)
- Tab/section ordering on the `/api-keys` page (active vs revoked)
- PATCH no-op semantics (default: accept, return row unchanged)
