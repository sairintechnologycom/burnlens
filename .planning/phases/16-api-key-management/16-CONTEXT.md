# Phase 16: API Key Management - Context

**Gathered:** 2026-05-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Workspace owners get full lifecycle control over their `bl_live_xxx` API keys from a dedicated `/api-keys` page (list with last-used, create with custom label + copy-once, revoke with confirmation, edit label without revoke). Viewers see only keys they personally created. The AUTH-08 resend-verification bug — currently broken for users who signed up via API key (null `owner_email` in localStorage) — is fixed by reading the email from the server-side session instead of the request body.

**Requirements covered:** APIKEY-01, APIKEY-02, APIKEY-03, APIKEY-04, APIKEY-05, AUTH-08
**Depends on:** Phase 15 (hard quota enforcement live, so broader key creation is safe)

</domain>

<decisions>
## Implementation Decisions

### Viewer-role scoping (APIKEY-05)
- **D-01:** Filter by `created_by_user_id`. `GET /api-keys` returns the full workspace list when caller's role is `owner`; for `viewer`, the server adds `WHERE created_by_user_id = $current_user_id`. Viewers can self-create and self-revoke their own keys but cannot see or touch other users' keys.
- **D-02:** No new schema columns required — `api_keys.created_by_user_id` already exists from Phase 10.
- **D-03:** Role check happens in `api_keys_api.py` using `TokenPayload.role` from JWT (already populated by Phase 11). Add a small helper `_filter_for_role(token, base_query)` to keep the policy in one place.
- **D-04:** Same role policy applies to `POST` (allowed for both, but viewer's key is auto-tagged with their `user_id`), `DELETE` (404 if viewer tries to revoke a key they didn't create — not 403, preserving the indistinguishability rule from Phase 10), and the new `PATCH` (same 404 rule).

### last_used_at tracking (APIKEY-01)
- **D-05:** Add `last_used_at TIMESTAMPTZ NULL` column to `api_keys` via migration.
- **D-06:** Throttled UPDATE strategy — on every successful key validation in the auth path, fire `UPDATE api_keys SET last_used_at = now() WHERE id = $1 AND (last_used_at IS NULL OR last_used_at < now() - interval '60 seconds')`. At most one write per key per minute, regardless of QPS.
- **D-07:** Write is fire-and-forget (background task / unawaited). The auth path must not block on it. Failure is logged and swallowed so a stuck UPDATE never breaks ingest.
- **D-08:** UI displays last-used as relative time ("2 hours ago", "Just now"). When `last_used_at IS NULL`, show "Never used".

### Edit endpoint shape (APIKEY-04)
- **D-09:** One field — extend the existing `name` column. Raise `max_length` from 64 to 128 in `ApiKeyCreateRequest` and the new `ApiKeyUpdateRequest`. UI labels it "Label or note".
- **D-10:** New endpoint `PATCH /api-keys/{key_id}` accepting `{name: str}`. Returns the updated `ApiKey` row. 404 on cross-tenant or wrong-creator (same indistinguishability rule).
- **D-11:** Editing does NOT change `revoked_at`, `last_used_at`, or any cache state. No `invalidate_api_key_cache` call needed — the hash is unchanged.

### AUTH-08 fix (resend-verification)
- **D-12:** Drop the `email` field from `ResendVerificationRequest` entirely. Endpoint becomes `POST /auth/resend-verification` with empty body, requires session JWT (`Depends(verify_token)`), reads `user_id` from the token, looks up the `email_encrypted` row in `users`, decrypts via `pii_crypto.decrypt_pii`.
- **D-13:** Frontend changes: `BillingStatusBanner.tsx` stops sending a body and stops touching `localStorage.burnlens_owner_email`. `useAuth.ts` and `setup/page.tsx` continue to track owner_email locally for display purposes, but the resend call no longer depends on it.
- **D-14:** Always-200 response shape preserved (no enumeration leak). The endpoint already invalidates prior tokens and inserts a new one — that logic stays.
- **D-15:** Add a regression test: a user with `owner_email = null` in localStorage but a valid session JWT can successfully trigger resend-verification. (Phase 11 test infra already covers session-cookie auth.)

### Page placement
- **D-16:** Add a new top-level route `/api-keys` (Next.js App Router page under `frontend/src/app/api-keys/page.tsx`). Full-page list with create/edit/revoke affordances and the last-used column.
- **D-17:** Keep the existing `ApiKeysCard.tsx` mounted on `/settings` as a quick-access summary, but add a clear "Manage all keys" link that routes to `/api-keys`. Do not duplicate the edit/last-used UI on `/settings` — keep the card narrow (list + create) and push the deeper management to the dedicated page.
- **D-18:** Add a sidebar entry "API Keys" (icon TBD by UI-SPEC). Place it in the same group as "Settings" in `Sidebar.tsx`.

### Revoke confirmation UX (APIKEY-03)
- **D-19:** Modal confirm dialog. Body shows the key's `name` and `last4` formatted as `Revoke "Primary" (…a8f2)?` with a destructive-styled red confirm button and a cancel button. No type-to-confirm.
- **D-20:** Server-side rejection remains immediate (no grace period) — the existing `invalidate_api_key_cache(revoked_hash)` call from Phase 10 stays, ensuring subsequent requests using the revoked key fail within the same request as the revoke.
- **D-21:** Show a success toast after revoke ("Key revoked"). Do NOT add an undo affordance — that would require a restore endpoint and contradicts the immediate-rejection criterion.

### Claude's Discretion
- Sidebar icon choice (UI-SPEC will resolve).
- Exact relative-time library/formatting helper for last-used (likely reuse whatever `UsageCard` and `ApiKeysCard` already use — researcher to confirm).
- Tab ordering on the new page (e.g., active vs revoked keys), or single list with revoked items dimmed at the bottom — UI-SPEC decides.
- Whether the new `PATCH` endpoint also accepts a no-op (same name) or rejects it. Default: accept and return the row unchanged.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Roadmap & requirements
- `.planning/ROADMAP.md` §"Phase 16: API Key Management" — goal, depends-on, 6 success criteria
- `.planning/REQUIREMENTS.md` — APIKEY-01..05 lines 21–25, AUTH-08 line 29
- `.planning/STATE.md` — current milestone v1.3 status

### Existing code that this phase extends
- `burnlens_cloud/api_keys_api.py` — current POST/GET/DELETE handlers (Phase 10). Extend with PATCH; add role filter and last_used_at logic.
- `burnlens_cloud/auth.py` — `verify_token`, `generate_api_key`, `hash_api_key`, `invalidate_api_key_cache`. The throttled `last_used_at` UPDATE belongs in the success branch of the API-key auth lookup (look for `get_workspace_by_api_key` or its callers).
- `burnlens_cloud/auth.py` lines 1087–1125 — current `resend_verification` handler that must be rewritten per D-12.
- `burnlens_cloud/models.py` — `ApiKey`, `ApiKeyCreateRequest`, `ApiKeyCreateResponse` (lines 504–531). Add `ApiKeyUpdateRequest`; extend `ApiKey` with `last_used_at: Optional[datetime] = None`.
- `burnlens_cloud/plans.py` — `resolve_limits()` returns `api_key_count` cap, already wired into POST.
- `frontend/src/components/ApiKeysCard.tsx` — existing 445-LOC card on /settings; reuse modal/toast patterns.
- `frontend/src/components/NewApiKeyModal.tsx` — existing create modal; reuse for the new page.
- `frontend/src/components/BillingStatusBanner.tsx` — current resend-verification caller (line 36); update per D-13.
- `frontend/src/app/setup/page.tsx` — current `localStorage.burnlens_owner_email` writer.
- `frontend/src/lib/hooks/useAuth.ts` — owner_email tracking; resend flow no longer reads it.
- `frontend/src/components/Sidebar.tsx` — add "API Keys" entry.

### Phase-10 / Phase-11 artifacts (carry-forward decisions)
- `.planning/phases/10-feature-gating-usage-visibility-ui/10-CONTEXT.md` — keys-on-settings origin
- `.planning/phases/11-auth-essentials/11-01-SUMMARY.md`..`11-05b-SUMMARY.md` — JWT shape (role claim), session cookie, email verification flow

### Codebase intelligence
- `.planning/codebase/ARCHITECTURE.md` — three-zone model (Railway backend is where this phase's API work lands)
- `.planning/codebase/CONVENTIONS.md` — async/await, fire-open logging, no buffering rules
- `.planning/codebase/TESTING.md` — pytest-asyncio + Playwright patterns

### Project standards
- `CLAUDE.md` §"Coding Standards" + §"Important Notes" — fail-open, never-crash-the-proxy posture (applies to fire-and-forget last_used_at write)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ApiKeysCard.tsx`: Existing list/create/revoke component on /settings — its modal interaction patterns, toast usage, and copy-to-clipboard logic are reusable on the new /api-keys page.
- `NewApiKeyModal.tsx`: Drop-in for the create flow; just needs the `name` `max_length` bumped to 128 in any client-side validation.
- `LockedPanel.tsx` and `UsageMeter.tsx` (Phase 10): Use `LockedPanel` if a viewer hits a forbidden affordance (though we'll prefer 404 via API filter rather than UI lockout).
- `Sidebar.tsx`: established nav pattern with grouped entries (Phase 13 already added "Alerts" — follow the same shape for "API Keys").
- `pii_crypto.decrypt_pii` / `lookup_hash`: already used by `resend_verification` for email lookup; the AUTH-08 rewrite reuses both.
- `verify_token` dependency injection: provides `TokenPayload` with `workspace_id`, `user_id`, `role` — the role-filter helper consumes this directly.

### Established Patterns
- **Indistinguishability**: cross-tenant access returns 404, not 403 (Phase 10 D-29-style policy). The new PATCH and the viewer-role filter both follow this.
- **Plaintext-once**: never re-emit. Edit endpoint must NOT return `key`; only `ApiKeyCreateResponse` does.
- **Fire-and-forget side effects in hot paths**: pattern from Phase 9 (`_record_usage_and_maybe_notify`) — apply to the throttled `last_used_at` UPDATE.
- **402 with structured detail body for plan-cap violations**: existing pattern in POST handler — keep unchanged.
- **JWT role claim consumed via `TokenPayload.role`**: Phase 11 wired this; Phase 13 used it for alert-rule access. Reuse the same idiom here.
- **Always-200 on email-enumeration-prone endpoints**: existing `resend_verification` already does this; preserved post-rewrite.

### Integration Points
- **Auth path → last_used_at**: hook into `get_workspace_by_api_key` (or wherever the cache hit/miss resolves a key id). The throttled UPDATE fires after a successful resolution, before the request handler returns.
- **Sidebar → new route**: `Sidebar.tsx` gets one entry; the `/api-keys` route component lives at `frontend/src/app/api-keys/page.tsx` and is auth-gated like `/settings`.
- **Settings card → new page**: ApiKeysCard gets a "Manage all keys →" link to `/api-keys`. Don't duplicate edit UI on the card.
- **Schema migration**: one new column (`api_keys.last_used_at`). Add to deployment migration scripts (look at how Phase 15 added columns — follow that ordering with respect to TestGate gating).
- **Viewer test surface**: Phase 11 test infra already creates owner+viewer JWTs — extend `tests/test_keys.py` and add a new `tests/test_phase16_api_keys.py` covering the role filter, the 404 rule, the PATCH endpoint, the throttled UPDATE, and the AUTH-08 regression.

</code_context>

<specifics>
## Specific Ideas

- Last-used display: relative time with "Never used" empty state (D-08).
- Revoke confirmation: modal showing `name` and `…last4` (D-19).
- Edit field labelled "Label or note" in UI (D-09).
- Sidebar entry titled "API Keys" placed near "Settings" (D-18).

</specifics>

<deferred>
## Deferred Ideas

- **Per-key restore (undo revoke)**: would need a new endpoint and contradicts the "no grace period" criterion. Out of scope.
- **Tags array on api_keys**: rejected in D-09 in favor of single `name` field. Revisit if v1.4 introduces filtering by team/environment.
- **Auto-issued personal key per viewer on invite**: rejected in D-01 in favor of self-create. Revisit if onboarding friction is observed.
- **`api_key_id` column on `usage_records`**: would enable "compute last_used from MAX(ts)" approach, also useful for per-key spend analytics later. Not needed for this phase. Could land in Phase 18 (Usage Dashboard Improvements) if per-key breakdowns are wanted.
- **Background sweeper for last_used_at**: rejected for now (D-06). Revisit only if the throttled-UPDATE pattern shows write contention in production.

</deferred>

---

*Phase: 16-api-key-management*
*Context gathered: 2026-05-10*
