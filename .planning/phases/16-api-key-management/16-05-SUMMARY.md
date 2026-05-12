---
phase: 16-api-key-management
plan: 05
status: complete
date: 2026-05-12
requirements: [APIKEY-01, APIKEY-02, APIKEY-03, APIKEY-04, APIKEY-05]
files_modified:
  - frontend/src/lib/format.ts              # NEW
  - frontend/src/components/Sidebar.tsx
  - frontend/src/components/ApiKeysCard.tsx
  - frontend/src/components/RevokeKeyModal.tsx       # NEW
  - frontend/src/components/EditKeyLabelInline.tsx   # NEW
  - frontend/src/components/ApiKeysTable.tsx         # NEW
  - frontend/src/app/api-keys/page.tsx               # NEW
---

# 16-05 — /api-keys UI Route + Components

## Outcome

Dedicated `/api-keys` route ships with full lifecycle UI (list, create-with-
copy-once, revoke-confirm, inline label edit). Settings card now deep-links
into it. Sidebar gains an "API Keys" entry with an inline-SVG key glyph
between Connections and Settings. No new external dependencies.

## File List

**Created**
- `frontend/src/lib/format.ts` — `formatDate` + `formatRelativeTime` (no date-fns)
- `frontend/src/components/RevokeKeyModal.tsx` — confirm modal, Escape/backdrop dismiss
- `frontend/src/components/EditKeyLabelInline.tsx` — autofocused input, Enter saves
- `frontend/src/components/ApiKeysTable.tsx` — 5-column table, revoked rows dimmed
- `frontend/src/app/api-keys/page.tsx` — page wiring fetch / create / patch / delete

**Modified**
- `frontend/src/components/Sidebar.tsx` — `KeyGlyph` + System-group entry + conditional render on `href === "/api-keys"` (no `SidebarItem` interface change per PATTERNS caveat #3)
- `frontend/src/components/ApiKeysCard.tsx` — `Manage all keys →` Link in section-header; `maxLength={128}` on create-modal name input

## UI-SPEC Verbatim Copy Check

| Surface | Copy used (verbatim from UI-SPEC) |
|---------|-----------------------------------|
| Page header | "API Keys" / "Workspace keys for syncing the BurnLens proxy and ingesting usage from your apps." |
| Table headers | Name / Last 4 / Last used / Created / Actions |
| Last-used cases | "Never used", "Just now", "N minute/hour/day/week(s) ago", absolute date ≥30d |
| Edit flow | "Save label" / "Discard changes" / "Label or note" |
| Revoke flow | "Revoke \"{name}\" (…{last4})?" / "This key will stop working immediately. Apps using it will get 401 errors until you create a new key." / "Keep key" / "Revoke key" |
| Settings link | "Manage all keys →" |
| Sidebar entry | "API Keys" |
| Empty state | "No API keys yet." / "Create your first key to start syncing to cloud." |
| Toasts | "Key revoked" / "Label updated" / "Failed to update label." / "Failed to revoke key. Please try again." / "Failed to create key." / "API key limit reached — upgrade your plan to add more." |

## canMutateRow Decision

Set to `() => true` on both owner and viewer. Rationale: the server-side
viewer-creator filter introduced in 16-03 already physically excludes other
users' keys from the GET response — the client never sees a row it cannot
mutate. A future refinement could surface `created_by_user_id` on the API
response so the table can differentiate even when the server is more
permissive (e.g., admin role with cross-user visibility). Noted for a future
plan if/when that requirement materializes.

## Plan-Cap Pre-emptive Disable

**Deferred.** This plan ships the page without the `useBilling` cap banner.
The 402 path is handled by the create handler (`PaymentRequiredError` →
"API key limit reached — upgrade your plan to add more." toast) so the user
gets immediate feedback. Re-using the cap banner from `ApiKeysCard.tsx` is a
trivial follow-up (one `useBilling` import + the same JSX block). Logged as
deferred so a v1.3.x polish phase can layer it without re-planning.

## Component Architecture

- `ApiKeysTable` is presentational; the page owns all data fetching and
  optimistic state updates.
- `RevokeKeyModal` accepts an async `onConfirm` so the page controls retry
  semantics (toast on failure, keep modal open).
- `EditKeyLabelInline` is self-contained; its `onSave` returns a Promise the
  parent awaits, allowing optimistic UI rollback on failure.
- `NewApiKeyModal` is reused unchanged — Phase 10 plaintext-once contract
  preserved (no new copies of the plaintext in localStorage or off-state).

## Verification

- `tsc --noEmit` exit 0.
- All grep gates from plan tasks 1/2/3 pass.
- No `lucide-react` / `date-fns` / `dayjs` imports anywhere in the new files
  or modified components.
- XSS hygiene: every key field rendered as a React text child (auto-escaped
  by React); no unsafe raw-HTML React props introduced.

## Self-Check: PASSED
