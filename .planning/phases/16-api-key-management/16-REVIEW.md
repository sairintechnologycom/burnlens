---
phase: 16-api-key-management
reviewed: 2026-05-12T00:00:00Z
depth: standard
files_reviewed: 17
files_reviewed_list:
  - burnlens_cloud/api_keys_api.py
  - burnlens_cloud/auth.py
  - burnlens_cloud/database.py
  - burnlens_cloud/models.py
  - frontend/src/app/api-keys/page.tsx
  - frontend/src/components/ApiKeysCard.tsx
  - frontend/src/components/ApiKeysTable.tsx
  - frontend/src/components/BillingStatusBanner.tsx
  - frontend/src/components/EditKeyLabelInline.tsx
  - frontend/src/components/RevokeKeyModal.tsx
  - frontend/src/components/Sidebar.tsx
  - frontend/src/lib/format.ts
  - tests/test_phase09_quota.py
  - tests/test_phase11_auth.py
  - tests/test_phase16_api_keys.py
  - tests/test_phase16_auth08_resend.py
  - tests/test_phase16_models.py
findings:
  critical: 3
  warning: 6
  info: 5
  total: 14
status: issues_found
---

# Phase 16: Code Review Report

**Reviewed:** 2026-05-12
**Depth:** standard
**Files Reviewed:** 17
**Status:** issues_found

## Summary

Phase 16 adds API-key labels (PATCH rename), per-key `last_used_at` tracking,
viewer-creator scoping, a dedicated `/api-keys` page (full lifecycle UI), a
sidebar nav entry, and the AUTH-08 fix that re-bases `resend-verification` on
the session JWT.

Most of the work is correct and well-tested, but three correctness defects
escape the test suite:

1. The new PATCH `/api-keys/{id}` endpoint forgets the `revoked_at IS NULL`
   guard that every other write path enforces, so revoked keys can be
   renamed — and a viewer's "indistinguishability" envelope is broken
   because a revoked key still answers PATCH while DELETE on the same key
   returns 404.
2. `resend_verification` reads `email_encrypted` from the DB and unconditionally
   calls `decrypt_pii(...)` on it. If the column is NULL (rotated PII master
   key, partial backfill, hand-edited row) the handler 500s, breaking the
   enumeration-safe "always 200" contract that AUTH-08/D-14 explicitly relies
   on.
3. `BillingStatusBanner.handleResend` treats *every* HTTP response as success
   because `fetch()` does not throw on non-2xx. A 401 or 500 from the API
   silently flips the banner to "email sent!" — a misleading UX/security
   regression that also lets an unauthenticated user (cookie expired) appear
   to receive a verification mail when none was sent.

Secondary issues: the new full-page revoke flow (`/api-keys/page.tsx` +
`RevokeKeyModal.tsx`) no longer requires typed-name confirmation that
`ApiKeysCard.tsx` still enforces (D-25 contract), creating two divergent
revoke UX surfaces in the same product. There are also a handful of smaller
quality issues called out below.

## Critical Issues

### CR-01: PATCH /api-keys/{id} can rename revoked keys (breaks D-04 indistinguishability + integrity)

**File:** `burnlens_cloud/api_keys_api.py:148-178`
**Issue:** The `update_api_key` UPDATE statement omits the `revoked_at IS NULL`
predicate that the matching `revoke_api_key` (line 198) and the cap-counting
`SELECT COUNT(*)` (line 78) both enforce. Consequences:

1. A revoked API key (which the audit trail says is dead) can still be
   relabelled via PATCH. The "Revoked" state is supposed to be terminal —
   mutating its `name` retroactively rewrites audit history surfaced via
   GET `/api-keys`.
2. The D-04 "indistinguishability" envelope leaks: for a key that was
   revoked AFTER the viewer created it, PATCH returns 200 + the renamed row
   while DELETE on the same id returns 404 (`revoked_at IS NOT NULL` ⇒ no
   match). A caller can therefore distinguish "revoked key I created" from
   "key that doesn't exist" by combining PATCH + DELETE responses — defeating
   the whole point of the indistinguishability decision.
3. `test_phase16_api_keys.py::test_patch_keys_name_max_length_128` even
   asserts `"revoked_at" not in sql.split("RETURNING")[0]` — codifying the
   missing guard rather than catching it.

**Fix:**
```python
rows = await execute_query(
    """
    UPDATE api_keys
    SET name = $1
    WHERE id = $2
      AND workspace_id = $3
      AND revoked_at IS NULL
      AND ($4::uuid IS NULL OR created_by_user_id = $4)
    RETURNING id, name, last4, created_at, revoked_at, last_used_at
    """,
    body.name,
    str(key_id),
    str(token.workspace_id),
    creator_filter,
)
```

Update `test_patch_keys_name_max_length_128` to drop the
`"revoked_at" not in sql.split("RETURNING")[0]` assertion and add a new test
`test_patch_revoked_key_returns_404` to lock the guard in.

---

### CR-02: resend_verification 500s when email_encrypted is NULL — breaks "always 200" enumeration-safety contract

**File:** `burnlens_cloud/auth.py:1138-1180`
**Issue:** The handler executes:

```python
rows = await execute_query(
    "SELECT id, email_encrypted, email_verified_at FROM users WHERE id = $1",
    str(token.user_id),
)
if not rows or rows[0].get("email_verified_at") is not None:
    return {"message": "If applicable, a verification email has been sent."}

user_id = str(rows[0]["id"])
recipient_email = _dec(rows[0]["email_encrypted"])   # <-- explodes if NULL
```

`decrypt_pii(None)` raises (Phase 1c `PIICryptoError`-style), so any
unverified user whose `email_encrypted` column is NULL gets a 500. That
state is reachable when:

- A user row predates Phase 1c backfill and the backfill aborted (see the
  `logger.error("PII Phase 1c ABORTED")` branch in database.py:480).
- An operator rotated `PII_MASTER_KEY` and a row got truncated.
- A test/dev row was created with an unencrypted email (the email-hash
  index does not require email_encrypted to be NOT NULL).

The docstring explicitly promises:
> Always returns 200 (D-14 — enumeration-safe). Already-verified users
> receive the same response with no email sent.

A 500 leaks "this user_id exists and is in a degraded state," violating
D-14. CLAUDE.md "fail-open" posture also requires this to not throw.

**Fix:**
```python
user_id = str(rows[0]["id"])
encrypted = rows[0].get("email_encrypted")
if not encrypted:
    # No deliverable address — silently return the same 200 body.
    return {"message": "If applicable, a verification email has been sent."}
try:
    recipient_email = _dec(encrypted)
except Exception:
    logger.warning("resend_verification: decrypt failed for user_id=%s", user_id)
    return {"message": "If applicable, a verification email has been sent."}
```

Add a regression test covering `email_encrypted=None` → 200 (mirroring the
existing `test_resend_verification_returns_200_for_missing_user`).

---

### CR-03: BillingStatusBanner.handleResend reports "sent" on every HTTP response, including 401/500

**File:** `frontend/src/components/BillingStatusBanner.tsx:32-44`
**Issue:**
```typescript
async function handleResend() {
  if (resendStatus !== "idle") return;
  setResendStatus("sending");
  try {
    await fetch(`${API_BASE}/auth/resend-verification`, {
      method: "POST",
      credentials: "include",
    });
    setResendStatus("sent");   // <-- runs even for 401/500/CORS-rejected etc.
  } catch {
    setResendStatus("error");
  }
}
```

`fetch()` resolves successfully for *every* HTTP status; it only rejects on
network failure. Concrete impact:

1. Cookie expired (very common since `resend-verification` is now
   session-protected per AUTH-08 / D-12): backend returns 401, banner shows
   "email sent!" — the user trusts the false confirmation and never tries
   again.
2. SendGrid mis-config / 500: same misleading "sent" state.
3. Forms the only public-facing signal the user gets — there's no toast or
   secondary path.

Because Phase 16 #16-02 explicitly removed the request body and re-rooted
this endpoint on the session JWT, the 401 case becomes far more likely than
under Phase 11's email-in-body version.

**Fix:**
```typescript
async function handleResend() {
  if (resendStatus !== "idle") return;
  setResendStatus("sending");
  try {
    const r = await fetch(`${API_BASE}/auth/resend-verification`, {
      method: "POST",
      credentials: "include",
    });
    if (!r.ok) {
      setResendStatus("error");
      return;
    }
    setResendStatus("sent");
  } catch {
    setResendStatus("error");
  }
}
```

Add a Playwright/unit test that mocks fetch with `{ ok: false, status: 401 }`
and asserts the banner falls into the `error` state.

## Warnings

### WR-01: New `/api-keys` page revoke flow drops typed-name confirmation — divergent from ApiKeysCard

**File:** `frontend/src/components/RevokeKeyModal.tsx:1-111`, `frontend/src/app/api-keys/page.tsx:274-280`
**Issue:** `ApiKeysCard.tsx` enforces typed-name revocation (header comment
labels this "D-25: exact, case-sensitive equality between the input and the
key name — no trim, no lowercase"). The new dedicated `/api-keys` page
swaps that out for a plain confirm-dialog (`RevokeKeyModal.tsx`) that only
asks the user to click "Revoke key" — no typed-name guard. Two routes now
have different revocation friction.

If D-25 was intentionally relaxed for the full-page surface, this should
land with a planning-doc note and the `ApiKeysCard` flow should match (so
they don't drift). Otherwise the new page is a security/UX regression vs.
the card.

**Fix:** Either (a) add a typed-name confirm input to `RevokeKeyModal.tsx`
matching `ApiKeysCard`, or (b) drop the typed-name pattern from
`ApiKeysCard` and update the D-25 ledger to reflect the relaxation.

---

### WR-02: revoke_api_key always clears workspaces.api_key_hash, even for non-legacy keys

**File:** `burnlens_cloud/api_keys_api.py:220-228`
**Issue:** The legacy-cleanup UPDATE runs unconditionally on every revoke:
```python
await execute_query(
    """
    UPDATE workspaces
    SET api_key_hash = NULL, api_key_last4 = NULL
    WHERE id = $1 AND api_key_hash = $2
    """,
    str(token.workspace_id),
    revoked_hash,
)
```

For a key that was *never* present in `workspaces.api_key_hash` (i.e., any
key created post-Phase-9), the predicate `api_key_hash = $2` never matches
and the UPDATE is a no-op. That's safe, but it's also a per-revoke wasted
DB round-trip. More importantly: if a workspace later signs up via a CLI
flow that still reads `workspaces.api_key_hash` as the canonical primary
key, nullifying it here might surprise that path. The comment claims
fallback removal "in v1.1.1+", but the column is still read in
`auth.get_workspace_by_api_key` (line 605-608) until then.

**Fix:** Skip the UPDATE when the dual-read fallback already isn't being
used for this hash. Cheapest version: gate it behind a SELECT that confirms
the row exists, or only run it when `key_hash` came from the legacy table
(which we know at this point because we ran the api_keys UPDATE first).
Pragmatic: leave as-is and add a `# TODO(v1.1.1): drop with legacy fallback`
comment so it's not forgotten.

---

### WR-03: Fire-and-forget `asyncio.create_task` may be garbage-collected before completion

**File:** `burnlens_cloud/auth.py:178-182`
**Issue:** Python's `asyncio.create_task` returns a Task that the runtime
only weakly references. Best practice (and a known footgun documented in
CPython 3.11+ release notes) is to keep a strong reference until the task
finishes or the task may be GC'd mid-await. `_schedule_last_used_update`
discards the returned task immediately.

In production, the task usually survives because the event loop holds a
reference until the next yield, but under load (lots of cache-hit auth
calls with concurrent GC pressure) the UPDATE can be silently dropped.
Affects observability of `last_used_at` more than correctness, but
silently-dropped writes are exactly the kind of bug that's hard to detect.

**Fix:**
```python
_BACKGROUND_TASKS: set[asyncio.Task] = set()

def _schedule_last_used_update(api_key_id: Optional[str]) -> None:
    if api_key_id is None:
        return
    ...
    try:
        task = asyncio.create_task(_touch_last_used())
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
    except RuntimeError as e:
        logger.debug("api_key.last_used_at scheduler skipped: %s", e)
```

---

### WR-04: EditKeyLabelInline saves untrimmed value even though guard rejects empty

**File:** `frontend/src/components/EditKeyLabelInline.tsx:24-33`
**Issue:** The save guard rejects `value.trim().length === 0` but then
calls `onSave(value)` with the *untrimmed* original. A user who types
"  primary  " (with surrounding whitespace) saves a name with the spaces
preserved. Server `max_length=128` won't catch it. UI then renders with
visible leading/trailing whitespace.

**Fix:**
```typescript
const handleSave = async () => {
  if (saving) return;
  const trimmed = value.trim();
  if (trimmed.length === 0) return;
  setSaving(true);
  try {
    await onSave(trimmed);   // <-- pass trimmed, not raw value
  } finally {
    setSaving(false);
  }
};
```

---

### WR-05: ApiKeysCard local `ApiKeyRow` type omits `last_used_at` field added in this phase

**File:** `frontend/src/components/ApiKeysCard.tsx:30-36`
**Issue:** The new backend `ApiKey` model gained `last_used_at`. The
dedicated `/api-keys` page and `ApiKeysTable` consume it. The legacy
Settings → API Keys card (`ApiKeysCard.tsx`) still declares
`interface ApiKeyRow { id; name; last4; created_at; revoked_at?: ... }`
with no `last_used_at`. Doesn't render incorrectly today (the field is just
ignored by TS), but if a future change reuses this type it will silently
discard the new column.

**Fix:** Either add `last_used_at: string | null` to the local interface,
or hoist `ApiKeyRow` from `ApiKeysTable.tsx` (which already has the field)
and re-import it in `ApiKeysCard.tsx`.

---

### WR-06: api-keys/page.tsx swallows server validation errors silently on label save

**File:** `frontend/src/app/api-keys/page.tsx:86-105`
**Issue:** `handleSaveLabel` does optimistic UI then `apiFetch(PATCH)`. On
ANY non-Auth error it rolls back and shows `"Failed to update label."` —
losing the actual error reason. The backend can return:

- 422 (empty name, name > 128 chars) — caller saw `maxLength={128}` so the
  long case is preempted, but rapid clipboard paste/IME workflows can still
  produce 129+.
- 404 (key was revoked between table load and PATCH — see CR-01) — should
  trigger a refresh, not a generic toast.

Generic toast hides the failure mode and the row appears unchanged with
no actionable feedback.

**Fix:** Inspect `err.status` / `err.data` on `apiFetch` errors and surface
more specific copy ("Label too long", "Key was revoked" + refresh) when
available.

## Info

### IN-01: `_PLAN_PRICE_ORDER` duplicated between auth.py and api_keys_api.py

**File:** `burnlens_cloud/api_keys_api.py:46`, `burnlens_cloud/auth.py:316`
**Issue:** Same constant tuple defined in two modules with identical
contents and identical comments-of-intent. Drift risk when a fourth plan is
added (e.g., "enterprise").
**Fix:** Move `_PLAN_PRICE_ORDER` to `plans.py` and import it from both
call sites.

---

### IN-02: Two `_lowest_plan_with_*` helpers with near-identical shape

**File:** `burnlens_cloud/api_keys_api.py:49-61`, `burnlens_cloud/auth.py:319-337`
**Issue:** `_lowest_plan_with_api_key_count(current)` and
`_lowest_plan_with_feature(name)` share the iteration/lookup pattern and
both depend on `_PLAN_PRICE_ORDER`. Worth folding into a single
`lowest_plan_satisfying(predicate_sql, *args)` helper next time someone
adds another "next-tier resolver".
**Fix:** Optional refactor; not blocking.

---

### IN-03: ApiKeysCard.tsx imports `Link` but old typed-name flow remains in same card

**File:** `frontend/src/components/ApiKeysCard.tsx`
**Issue:** Now that the dedicated `/api-keys` page exists and is linked
from the card header ("Manage all keys →"), the in-card table + revoke
flow is largely duplicate UI. Keeping both forever is fine; just be aware
that future changes need to touch two surfaces.
**Fix:** Plan a v1.3 follow-up to remove the in-card table once the
dedicated page is the primary UX surface, leaving the card as a summary
widget only.

---

### IN-04: `formatRelativeTime` returns "Just now" for clock-skew negatives

**File:** `frontend/src/lib/format.ts:22-39`
**Issue:** `const ms = Date.now() - new Date(iso).getTime();` is negative
if the server clock is ahead of the client (or vice versa) — common at
midnight UTC rollover or in browsers with skewed clocks. The negative
`ms` floors to a negative `s`, which is `< 60`, so the function returns
"Just now". That's actually a sensible default, but it silently hides
genuine "future timestamps" caused by data corruption.
**Fix:** Optional — clamp negatives explicitly:
```typescript
if (ms < 0) return "Just now";
```
to document the intent.

---

### IN-05: `tests/test_phase16_api_keys.py::test_patch_keys_name_max_length_128` codifies the CR-01 bug

**File:** `tests/test_phase16_api_keys.py:176-177`
**Issue:**
```python
# PATCH must NOT touch revoked_at — only the RETURNING tail references it
assert "revoked_at" not in sql.split("RETURNING")[0]
```

This locks in the absence of the `revoked_at IS NULL` filter and will fail
the moment CR-01 is fixed properly. Misnamed assertion — the intent is "do
not write to revoked_at", which is correctly satisfied by `SET name = $1`.
Should be replaced with `"SET name = $1" in sql` and `"revoked_at = " not
in sql` to express the actual invariant.
**Fix:**
```python
# PATCH must not mutate revoked_at; reading it in WHERE / RETURNING is fine.
assert "SET name = $1" in sql
assert "revoked_at = " not in sql
# and the WHERE clause MUST guard against revoked keys (see CR-01).
assert "revoked_at IS NULL" in sql.split("RETURNING")[0]
```

---

_Reviewed: 2026-05-12_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
