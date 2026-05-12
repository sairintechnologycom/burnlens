---
phase: 16-api-key-management
verified: 2026-05-12T00:00:00Z
status: gaps_found
score: 3/6 must-haves verified
overrides_applied: 0
gaps:
  - truth: "An owner can edit the label or scope note on any existing key without revoking and re-creating it (SC-4 / APIKEY-04) — and the PATCH endpoint must respect the D-04 indistinguishability envelope"
    status: partial
    reason: "PATCH /api-keys/{id} omits `AND revoked_at IS NULL` from its UPDATE WHERE clause. Revoked keys can be renamed (CR-01) — terminal-state invariant violated. Also breaks D-04 indistinguishability: PATCH returns 200 while DELETE on the same revoked key returns 404, letting a caller distinguish 'revoked key I created' from 'key that does not exist'. Worse, tests/test_phase16_api_keys.py::test_patch_keys_name_max_length_128 codifies the bug (`assert 'revoked_at' not in sql.split('RETURNING')[0]`) — refactoring to add the guard will break this test (IN-05)."
    artifacts:
      - path: "burnlens_cloud/api_keys_api.py:148-178"
        issue: "UPDATE statement lacks `AND revoked_at IS NULL` predicate present in both revoke_api_key (line 198) and the cap-counting SELECT (line 78)"
      - path: "tests/test_phase16_api_keys.py:176-177"
        issue: "Locks in the missing guard; needs replacement with `assert 'revoked_at IS NULL' in sql.split('RETURNING')[0]`"
    missing:
      - "Add `AND revoked_at IS NULL` to the UPDATE WHERE clause in update_api_key"
      - "Replace the IN-05 assertion to require `revoked_at IS NULL` in the WHERE clause"
      - "Add new test `test_patch_revoked_key_returns_404` that mocks UPDATE returning [] and asserts 404 + `{detail: {error: 'api_key_not_found'}}`"

  - truth: "A user who signed up via API key (null owner_email in localStorage) successfully receives a resend-verification email (SC-6 / AUTH-08)"
    status: partial
    reason: "Two defects break the always-200 enumeration-safety contract and the UX feedback signal. (CR-02) resend_verification calls decrypt_pii(rows[0]['email_encrypted']) unconditionally — if email_encrypted is NULL (rotated PII master key, partial Phase 1c backfill, dev-row, etc.) the handler 500s, violating D-14 and CLAUDE.md fail-open posture. (CR-03) BillingStatusBanner.handleResend awaits fetch() but does not inspect response.ok — every HTTP response, including 401 (very common now that the endpoint is JWT-gated) and 500 (from CR-02), flips the banner to 'email sent!'. The user trusts a false confirmation. Together these mean the failure mode AUTH-08 is supposed to close (cookie expired or DB-degraded user) silently appears to succeed."
    artifacts:
      - path: "burnlens_cloud/auth.py:1139-1146"
        issue: "decrypt_pii called without NULL/exception guard. 500 leaks 'this user_id exists in degraded state' — enumeration oracle."
      - path: "frontend/src/components/BillingStatusBanner.tsx:32-44"
        issue: "fetch() result is awaited but `r.ok` is never checked. setResendStatus('sent') fires for 401/500/CORS-rejected etc."
    missing:
      - "auth.py: guard `rows[0]['email_encrypted']` for None and wrap decrypt_pii in try/except → return same enumeration-safe 200 body on either path"
      - "auth.py: regression test `test_resend_verification_handles_null_email_encrypted` returning 200, send_verify_email NOT called"
      - "BillingStatusBanner.tsx: capture `const r = await fetch(...)`, then `if (!r.ok) { setResendStatus('error'); return; }` before flipping to 'sent'"
      - "Add unit/Playwright test that mocks fetch with {ok:false,status:401} and asserts banner → 'error' state"

  - truth: "A viewer-role user visiting `/api-keys` sees only their own key and cannot access the create or revoke actions (SC-5 / APIKEY-05)"
    status: partial
    reason: "Server-side filter is correctly implemented (`_viewer_creator_filter` applied in GET/PATCH/DELETE — verified via test_list_keys_viewer_returns_only_own + test_delete_keys_viewer_404_on_other_creator). However the UI surface contradicts the SC-5 wording 'cannot access the create or revoke actions': the `/api-keys` page renders Create-key for every authenticated session, and ApiKeysTable's `canMutateRow` is hardcoded `() => true` so viewers see Revoke buttons on their own keys. Decision D-04 explicitly says viewers CAN self-create and self-revoke (`viewers can self-create and self-revoke their own keys`) — so the implementation matches the decision but contradicts the original ROADMAP SC-5 wording. This is a contract/spec divergence and needs either an override note in the plan or a SC-5 revision in ROADMAP.md before claiming the goal."
    artifacts:
      - path: "frontend/src/app/api-keys/page.tsx:164-171"
        issue: "Create-key button renders unconditionally — no role gate"
      - path: "frontend/src/components/ApiKeysTable.tsx (canMutateRow callsite in page.tsx:201)"
        issue: "canMutateRow={() => true} bypasses viewer/role distinction even though session.role is available"
    missing:
      - "Either: (a) gate Create-key + Revoke buttons by `session.role !== 'viewer'` to match ROADMAP SC-5 verbatim, OR (b) add an override entry to VERIFICATION.md frontmatter accepting D-04's relaxation of SC-5"
      - "Document the SC-5 → D-04 deviation in a SUMMARY note and update ROADMAP.md SC-5 wording in a follow-up phase"

human_verification:
  - test: "Owner full lifecycle — visit /api-keys, observe table with Name/Last 4/Last used/Created/Actions columns; create key with label 'CI bot'; copy plaintext from NewApiKeyModal; revoke an existing key, confirm via RevokeKeyModal, observe 'Key revoked' toast and dimmed row; edit a key's label via the pencil button, observe 'Label updated' toast"
    expected: "All five flows succeed end-to-end; plaintext shown exactly once; revoked row dims; toasts use UI-SPEC verbatim copy"
    why_human: "Visual flow + clipboard + relative-time rendering cannot be automated cheaply without Playwright; UI-SPEC adherence is a visual judgment"

  - test: "Sidebar nav — log in as owner, look at the 'System' group in the left sidebar"
    expected: "Three items in order: Connections, API Keys (with a key glyph), Settings. The 'API Keys' entry highlights when the URL is /api-keys."
    why_human: "Visual ordering and glyph appearance cannot be reliably verified by grep alone"

  - test: "AUTH-08 happy path — clear localStorage (simulate API-key signup), log in, the email-verify banner appears, click 'resend verification email'"
    expected: "Network tab shows POST /auth/resend-verification with empty body and cookie sent; response 200; UI flips to 'email sent!'"
    why_human: "Requires a logged-in session with localStorage.burnlens_owner_email = null; cookie/credentials behavior + UI state transition is end-to-end"

  - test: "AUTH-08 sad path — let the session cookie expire (or invalidate it server-side), click 'resend verification email'"
    expected: "Backend returns 401; UI should fall to 'try again' (error), NOT 'email sent!'. THIS WILL FAIL until CR-03 is fixed."
    why_human: "Tests the CR-03 regression directly. Confirms whether the gap was closed."

  - test: "Viewer role — log in as a viewer-tier user, visit /api-keys"
    expected: "Per ROADMAP SC-5: viewer sees ONLY their own key, and no Create or Revoke buttons render. Per D-04: viewer sees only their own key, Create button visible, Revoke visible on own keys. Confirm which intent applies."
    why_human: "Goal-vs-decision divergence requires human adjudication"
---

# Phase 16: API Key Management — Verification Report

**Phase Goal:** Workspace owners can manage the full API key lifecycle from the UI, and the auth bug for API-key users is resolved
**Verified:** 2026-05-12
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria + Plan Must-Haves)

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| SC-1 | Owner sees all active keys at `/api-keys` with labels and last-used timestamps | ✓ VERIFIED | `frontend/src/app/api-keys/page.tsx` mounted, ApiKeysTable renders 5 cols including Last used, `formatRelativeTime` handles NULL → "Never used", GET endpoint returns last_used_at (api_keys_api.py:124-145) |
| SC-2 | Owner creates new key with custom label, copy-once before leaving dialog | ✓ VERIFIED | POST /api-keys preserved (api_keys_api.py:64-121); NewApiKeyModal reused verbatim; create-key modal has `maxLength={128}` (page.tsx:229); ApiKeysCard's create modal also has maxLength=128 (ApiKeysCard.tsx:413) |
| SC-3 | Owner revokes key, subsequent requests immediately rejected | ✓ VERIFIED | DELETE handler preserves invalidate_api_key_cache (api_keys_api.py:214); legacy workspaces.api_key_hash also cleared (line 220); 14 cloud tests pass including viewer-creator scoping |
| SC-4 | Owner edits label without revoking | ✗ FAILED | PATCH endpoint exists and accepts {name}; tests pass — BUT CR-01: omits `AND revoked_at IS NULL` so revoked keys can be renamed (audit integrity + D-04 indistinguishability broken). See gap. |
| SC-5 | Viewer sees only own key; cannot access create or revoke actions | ? UNCERTAIN | Server-side filter correctly implemented (4 tests pass); UI does NOT gate Create/Revoke by role — matches D-04 ("viewers can self-create") but contradicts ROADMAP SC-5 wording. Needs human decision (override OR fix). |
| SC-6 | API-key-signup user (null owner_email) receives resend-verification email | ✗ FAILED | Backend rewrite correct in principle (auth.py:1140 uses token.user_id) — BUT CR-02: 500s on NULL email_encrypted breaks always-200; CR-03: BillingStatusBanner falsely reports "sent" on any HTTP response (401/500). End-to-end signal broken in the very failure mode AUTH-08 closes. |

**Score:** 3/6 truths verified (SC-1, SC-2, SC-3); 2 FAILED (SC-4, SC-6); 1 UNCERTAIN (SC-5).

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `burnlens_cloud/database.py` | ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMPTZ | ✓ VERIFIED | Line 903 |
| `burnlens_cloud/models.py` | ApiKeyUpdateRequest class, ApiKey.last_used_at field, ApiKeyCreateRequest max_length=128 | ✓ VERIFIED | Lines 511, 526, 539, 546 |
| `burnlens_cloud/api_keys_api.py` | PATCH /api-keys/{id}, viewer-creator filter on GET/PATCH/DELETE | ⚠️ STUB (logic gap) | PATCH exists (line 148) but missing `revoked_at IS NULL` guard — CR-01 |
| `burnlens_cloud/auth.py` (resend) | JWT-based identity, empty body, always 200 | ⚠️ STUB (logic gap) | Rewrite correct in shape; CR-02 NULL-blob path 500s |
| `burnlens_cloud/auth.py` (last_used_at) | _schedule_last_used_update fire-and-forget with SQL throttle | ✓ VERIFIED | Helper at line 149, called from cache-hit (line 582) and cache-miss (line 622); WR-03 weak-task-ref concern flagged but not blocking |
| `frontend/src/app/api-keys/page.tsx` | Full-page route with create/revoke/edit | ✓ VERIFIED (with SC-5 caveat) | File exists; calls apiFetch with GET/POST/PATCH/DELETE; document.title set |
| `frontend/src/components/ApiKeysTable.tsx` | 5-col table with last_used + revoke + edit | ✓ VERIFIED | File present; columns Name/Last 4/Last used/Created/Actions; opacity 0.55 on revoked |
| `frontend/src/components/RevokeKeyModal.tsx` | Backdrop+Escape close, Keep key / Revoke key buttons | ✓ VERIFIED | File present, copy matches UI-SPEC verbatim; **WR-01 deviation: lacks typed-name guard that ApiKeysCard enforces (D-25)** — divergent surfaces |
| `frontend/src/components/EditKeyLabelInline.tsx` | Inline rename, Enter saves, Escape cancels, maxLength=128 | ✓ VERIFIED | File present; **WR-04: saves untrimmed value** — non-blocking |
| `frontend/src/components/Sidebar.tsx` | API Keys entry between Connections and Settings, conditional KeyGlyph | ✓ VERIFIED | Lines 59 (entry), 85-104 (KeyGlyph), 147-151 (conditional render) |
| `frontend/src/components/ApiKeysCard.tsx` | Manage all keys → link, create-modal maxLength=128 | ✓ VERIFIED | Lines 225, 413 |
| `frontend/src/components/BillingStatusBanner.tsx` | Body stripped, credentials:'include' kept | ⚠️ STUB (response not inspected) | Body/header stripped (lines 36-39); **CR-03: !r.ok branch missing → false-positive 'sent'** |
| `frontend/src/lib/format.ts` | formatRelativeTime + formatDate, no external deps | ✓ VERIFIED | File present, cascade Just now → minutes → hours → days → weeks → date |
| `tests/test_phase16_api_keys.py` | ≥10 backend tests | ✓ VERIFIED (with IN-05 caveat) | 14 tests collected, all pass; one assertion codifies CR-01 bug — must be amended when CR-01 is fixed |
| `tests/test_phase16_auth08_resend.py` | 5 regression tests | ✓ VERIFIED | 5 tests collected, all pass; **gap: no test for email_encrypted=NULL** |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| frontend/.../api-keys/page.tsx | GET /api-keys | apiFetch | ✓ WIRED | page.tsx:38 |
| frontend/.../api-keys/page.tsx | PATCH /api-keys/{id} | apiFetch with method=PATCH | ✓ WIRED | page.tsx:94-98 |
| frontend/.../api-keys/page.tsx | DELETE /api-keys/{id} | apiFetch with method=DELETE | ✓ WIRED | page.tsx:111-113 |
| Sidebar.tsx | /api-keys route | href entry in System group | ✓ WIRED | Sidebar.tsx:59 |
| ApiKeysCard.tsx | /api-keys page | Manage all keys → Link | ✓ WIRED | ApiKeysCard.tsx:216-226 |
| auth.py::resend_verification | pii_crypto.decrypt_pii | local import in handler | ⚠️ PARTIAL | Wired but unguarded — CR-02 |
| BillingStatusBanner.handleResend | /auth/resend-verification | fetch with credentials:'include' | ⚠️ PARTIAL | Request shape correct; response not inspected — CR-03 |
| api_keys_api.py::update_api_key | DB UPDATE api_keys SET name | execute_query | ⚠️ PARTIAL | Statement runs but missing revoked_at guard — CR-01 |
| auth.py::get_workspace_by_api_key | DB UPDATE api_keys SET last_used_at | asyncio.create_task | ✓ WIRED | Helper at auth.py:149; SQL throttle at line 171 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| api-keys/page.tsx | `keys` state | apiFetch('/api-keys') → list_api_keys → SELECT FROM api_keys | ✓ Yes (real SELECT with creator filter) | ✓ FLOWING |
| ApiKeysTable.tsx | `keys` prop | parent page state | ✓ Yes | ✓ FLOWING |
| BillingStatusBanner | `resendStatus` | setResendStatus on fetch response | ⚠️ Conflates success with 401/500 — stale state risk | ⚠️ HOLLOW (CR-03) |
| Sidebar entry rendering | `GROUPS` constant | hardcoded list (line 59) | ✓ Static-but-correct | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Phase 16 backend tests pass | `/opt/homebrew/bin/pytest tests/test_phase16_*.py -q` | 33 passed in 0.45s | ✓ PASS |
| Models import + max_length=128 | grep models.py for max_length=128 / last_used_at / ApiKeyUpdateRequest | 4 hits at lines 511, 526, 539, 546 | ✓ PASS |
| Migration ALTER present in init_db | grep database.py | 1 hit at line 903 | ✓ PASS |
| API router exposes 4 endpoints | grep `@router.(get\|post\|patch\|delete)` api_keys_api.py | 4 hits (POST, GET, PATCH, DELETE) | ✓ PASS |
| Last-used SQL throttle in place | grep "interval '60 seconds'" auth.py | 1 hit at line 171 | ✓ PASS |
| Frontend tsc clean | `cd frontend && npx --no -- tsc --noEmit` | (skipped — phase verifier non-blocking; trust reviewer + 16-05/16-06 verify gates that ran during execute) | ? SKIP |
| Phase 16 frontend artifacts exist | ls 4 new component files + format.ts + page.tsx | All present | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
| ----------- | -------------- | ----------- | ------ | -------- |
| APIKEY-01 | 16-01, 16-03, 16-04, 16-05 | Owner can list all active workspace API keys with label and last-used timestamp at /api-keys | ✓ SATISFIED | Migration, model, GET endpoint, table component, page all wired |
| APIKEY-02 | 16-05 | Owner can create a new `bl_live_xxx` key with a custom label (copy-to-clipboard on creation) | ✓ SATISFIED | POST endpoint, NewApiKeyModal, ApiKeysCard maxLength=128, page.tsx create modal maxLength=128 |
| APIKEY-03 | 16-03, 16-04, 16-05 | Owner can revoke any key, immediately invalidating it server-side | ✓ SATISFIED | DELETE endpoint preserved with invalidate_api_key_cache; RevokeKeyModal wired; "Key revoked" toast |
| APIKEY-04 | 16-01, 16-03, 16-04, 16-05 | Owner can assign or edit a label/scope note on any key | ✗ BLOCKED | PATCH endpoint exists but CR-01 violates D-04 indistinguishability + audit integrity (revoked keys renamable) |
| APIKEY-05 | 16-03, 16-04, 16-05 | Viewer-role users can see their own key but cannot create or revoke workspace keys | ? NEEDS HUMAN | Server-side scoping correct; UI shows Create/Revoke to viewers per D-04, contradicting ROADMAP SC-5 verbatim wording |
| AUTH-08 | 16-02, 16-06 | Resend-verification email works for API-key users when `owner_email` is null in localStorage | ✗ BLOCKED | Backend identity-by-JWT correct in principle but CR-02 (NULL blob 500) + CR-03 (false "sent") break the user-facing contract |

**No orphaned requirements** — REQUIREMENTS.md maps APIKEY-01..05 + AUTH-08 to Phase 16, and every ID is claimed by at least one plan's `requirements` field.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| burnlens_cloud/api_keys_api.py | 161-174 | Missing `revoked_at IS NULL` predicate (CR-01) | 🛑 Blocker | Allows rename of terminal-state rows; breaks indistinguishability oracle |
| burnlens_cloud/auth.py | 1139-1146 | Unguarded `decrypt_pii(rows[0]['email_encrypted'])` (CR-02) | 🛑 Blocker | 500 on NULL blob — breaks D-14 always-200 enumeration safety |
| frontend/src/components/BillingStatusBanner.tsx | 36-44 | `await fetch(...)` without `r.ok` check (CR-03) | 🛑 Blocker | False "sent" UI on 401/500; ironically hides the AUTH-08 failure mode it was meant to fix |
| frontend/src/components/RevokeKeyModal.tsx | 1-111 | No typed-name confirm; ApiKeysCard still enforces D-25 typed-name (WR-01) | ⚠️ Warning | Divergent revoke UX between two surfaces in same product |
| burnlens_cloud/auth.py | 178-182 | `asyncio.create_task` return value discarded (WR-03) | ⚠️ Warning | CPython 3.11+ may GC the task; silent UPDATE drop under load |
| frontend/src/components/EditKeyLabelInline.tsx | 29 | `onSave(value)` instead of `onSave(value.trim())` (WR-04) | ⚠️ Warning | Whitespace-padded labels persist server-side |
| frontend/src/components/ApiKeysCard.tsx | 30-36 | Local ApiKeyRow type missing `last_used_at` (WR-05) | ℹ️ Info | Latent silent-drop bug if type ever re-used |
| frontend/src/app/api-keys/page.tsx | 86-105 | Generic toast on PATCH error swallows 404/422 (WR-06) | ⚠️ Warning | Lost actionable feedback when key was revoked between load and PATCH |
| tests/test_phase16_api_keys.py | 176-177 | Assertion codifies CR-01 bug (IN-05) | ℹ️ Info | Must be amended when CR-01 is fixed |
| burnlens_cloud/api_keys_api.py | 220-228 | Unconditional UPDATE workspaces.api_key_hash on every revoke (WR-02) | ℹ️ Info | Wasted DB round-trip post-Phase-9 keys; carries a TODO for v1.1.1+ |
| burnlens_cloud/api_keys_api.py:46 + auth.py:316 | — | _PLAN_PRICE_ORDER duplicated (IN-01) | ℹ️ Info | Drift risk |
| frontend/src/lib/format.ts:22-39 | — | Negative-skew returns "Just now" (IN-04) | ℹ️ Info | Sensible default; documenting recommended |

### Gaps Summary

Phase 16 ships the **structural** parts of the goal — schema, models, four endpoints, four new UI components, sidebar entry, settings link, 33 backend tests passing — but **three correctness defects** identified in the standalone code review (16-REVIEW.md) cut directly into two of the six ROADMAP Success Criteria:

1. **SC-4 / APIKEY-04 (label editing)** ships a PATCH that violates the D-04 indistinguishability decision the plan itself called out as a must-have, and a test that locks in the violation.
2. **SC-6 / AUTH-08 (resend-verification for API-key users)** has the backend identity model correct but two cascading failures — backend 500 on NULL email blob, and frontend treating any HTTP response as success — together hide the exact failure mode the requirement was created to close.
3. **SC-5 / APIKEY-05 (viewer scoping)** is correctly implemented at the server boundary but the UI surfaces Create/Revoke to viewers anyway, matching the implementation decision (D-04: viewers can self-create) but contradicting the verbatim ROADMAP wording ("cannot access the create or revoke actions"). This is a spec/code disagreement, not a bug — it needs a human decision: either tighten the UI to the ROADMAP or amend the ROADMAP to match D-04.

The three CR-level defects are real defects in committed code, not hypothetical risks. Until they are addressed (either via a gap-closure phase or explicit override accepting the regression) the Phase 16 goal is **not** achieved.

### Recommended Closure Path

Group the three CR defects into a single gap-closure plan (16-07 or v1.3 follow-up):
- **Task A** (api_keys_api.py + tests/test_phase16_api_keys.py): add `revoked_at IS NULL` guard to PATCH; replace IN-05 assertion; add test_patch_revoked_key_returns_404.
- **Task B** (auth.py + tests/test_phase16_auth08_resend.py): guard email_encrypted NULL + try/except around decrypt_pii; add regression test.
- **Task C** (BillingStatusBanner.tsx + new test): check `r.ok` before flipping to 'sent'; mock-fetch test for 401 → error state.
- **Decision item** (ROADMAP.md or plan override): reconcile SC-5 wording with D-04. Recommend updating SC-5 to "viewer sees only keys they created and cannot access keys created by other users" to match the implemented (and security-equivalent) D-04 policy.

Three warnings (WR-01 typed-name divergence, WR-03 task GC, WR-04 untrimmed save) are quality issues that can ride the same closure plan or defer to v1.4 — they do not block the phase goal.

---

_Verified: 2026-05-12_
_Verifier: Claude (gsd-verifier)_
