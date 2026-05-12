# Phase 16: API Key Management — Pattern Map

**Mapped:** 2026-05-10
**Files analyzed:** 14 (7 backend, 6 frontend, 1 migration)
**Analogs found:** 14 / 14 (all in-tree)

> Downstream planner: every excerpt below is verbatim from the cited file/lines. Cite line ranges directly in PLAN.md actions; do not re-extract.

---

## File Classification

| New / Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---------------------|------|-----------|----------------|---------------|
| `burnlens_cloud/api_keys_api.py` (extend) | controller (FastAPI router) | request-response (CRUD) | self (Phase 10) — already the pattern | exact (in-place extension) |
| `burnlens_cloud/auth.py` — throttled `last_used_at` write | utility (auth path side-effect) | fire-and-forget background write | `burnlens_cloud/auth.py::get_workspace_by_api_key` (cache write) + Phase 9 `_record_usage_and_maybe_notify` | role-match |
| `burnlens_cloud/auth.py::resend_verification` rewrite | controller (auth route) | request-response (session-authed) | `burnlens_cloud/auth.py` lines 1087–1125 (current handler) + email-decrypt idiom from same file lines 1044–1049 | exact (in-place rewrite) |
| `burnlens_cloud/models.py` — `ApiKeyUpdateRequest`, extended `ApiKey`, bumped `name` | model (Pydantic) | n/a (DTO) | `burnlens_cloud/models.py::ApiKeyCreateRequest` lines 504–531 + `alerts_api.AlertRulePatch` lines 17–20 | exact |
| New migration: `api_keys.last_used_at TIMESTAMPTZ NULL` | migration (DDL in `init_db`) | n/a | `burnlens_cloud/database.py` line 931 (`ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at`) | exact |
| `frontend/src/app/api-keys/page.tsx` (new) | component (Next.js App Router page) | request-response (CRUD UI) | `frontend/src/app/alerts/page.tsx` (Shell wrapper + Content split + table + edit modal) | exact |
| `frontend/src/components/ApiKeysTable.tsx` (new — extracted from `ApiKeysCard`) | component (table) | render | `frontend/src/components/ApiKeysCard.tsx` lines 287–377 (existing table) | exact |
| `frontend/src/components/RevokeKeyModal.tsx` (new) | component (modal) | event-driven | `frontend/src/components/NewApiKeyModal.tsx` (modal scaffolding, dismiss-button focus) + ApiKeysCard inline modal lines 380–432 | role-match |
| `frontend/src/components/EditKeyLabelInline.tsx` (new) | component (inline form) | event-driven | `ApiKeysCard.tsx` lines 332–369 (inline revoke-confirm input pattern) | role-match |
| `frontend/src/lib/format.ts` (extend or create) — `formatRelativeTime(iso)` | utility | transform | `ApiKeysCard.tsx::formatDate` lines 46–56 (only date helper found) | partial (no relative-time helper exists yet) |
| `frontend/src/components/ApiKeysCard.tsx` (extend) | component | request-response | self — bump `maxLength` to 128, add `Manage all keys →` link in section-header (lines 210–222) | exact (in-place edit) |
| `frontend/src/components/NewApiKeyModal.tsx` (extend) | component (modal) | event-driven | self — Phase 10 carryover; only client-side `maxLength` bump | exact |
| `frontend/src/components/Sidebar.tsx` (extend) | component (nav) | render | self — append entry + co-locate `KeyGlyph` next to `LockGlyph` (lines 64–82) | exact |
| `frontend/src/components/BillingStatusBanner.tsx` (modify) | component | request-response | self — strip body + `localStorage.burnlens_owner_email` from line 39 | exact (in-place edit) |
| `frontend/src/lib/hooks/useAuth.ts` (light edit) | hook | render | self — keep `ownerEmail` for display; no required field for resend | exact |
| `frontend/src/app/setup/page.tsx` (light edit) | component (route) | request-response | self — keep `localStorage.setItem("burnlens_owner_email", …)` line 34 unchanged | exact |
| `tests/test_phase16_api_keys.py` (new) | test | request-response | `tests/test_phase13_alerts_api.py` lines 1–120 (httpx ASGI + dependency override pattern) | exact |
| `tests/test_keys.py` (extend) | test | n/a | self (existing) — note: this is the **local-proxy** key store test, not the cloud test. The cloud-side `last_used_at` assertions belong in the new `test_phase16_api_keys.py`, not here. (See "No analog" below.) | partial |

---

## Pattern Assignments

### `burnlens_cloud/api_keys_api.py` (controller, request-response — extend)

**Analog:** self. The Phase-10 file is already the canonical pattern. Plan extends with `_filter_for_role`, PATCH endpoint, and viewer-aware DELETE/GET/PATCH.

**Imports pattern** (lines 10–22, verbatim):
```python
from __future__ import annotations
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from .auth import verify_token, generate_api_key, hash_api_key, invalidate_api_key_cache
from .config import settings
from .database import execute_query
from .models import ApiKey, ApiKeyCreateRequest, ApiKeyCreateResponse, TokenPayload
from .plans import resolve_limits

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api-keys", tags=["api-keys"])
```

**Phase-16 import additions:** add `ApiKeyUpdateRequest` to the `from .models import …` line. No other imports change.

**Auth + role pattern** (Phase 13 reference — `alerts_api.py` lines 23–29 + `auth.py` lines 243–256):
```python
# Endpoint signature uses:
token: TokenPayload = Depends(verify_token),
# TokenPayload has fields: workspace_id (UUID), user_id (UUID), role (str: 'owner'|'admin'|'viewer')
```
Plan 16 does **not** call `require_role` (per D-04: viewers are allowed everywhere; cross-tenant/wrong-creator returns 404). Use `token.role` and `token.user_id` directly inside `_filter_for_role`.

**Existing GET pattern to extend** (`api_keys_api.py` lines 107–121, verbatim):
```python
@router.get("", response_model=list[ApiKey])
async def list_api_keys(
    token: TokenPayload = Depends(verify_token),
) -> list[ApiKey]:
    """List API keys for the caller's workspace. Never returns plaintext or hash."""
    rows = await execute_query(
        """
        SELECT id, name, last4, created_at, revoked_at
        FROM api_keys
        WHERE workspace_id = $1
        ORDER BY created_at DESC
        """,
        str(token.workspace_id),
    )
    return [ApiKey(**r) for r in rows]
```
**Phase 16 mutation:** SELECT must add `last_used_at`; WHERE clause must conditionally append `AND created_by_user_id = $2` for viewer role; ORDER BY stays.

**Helper to add (`_filter_for_role`)** — derive shape from the existing inline guard in `revoke_api_key` (lines 134–143):
```python
result = await execute_query(
    """
    UPDATE api_keys
    SET revoked_at = NOW()
    WHERE id = $1 AND workspace_id = $2 AND revoked_at IS NULL
    RETURNING id, key_hash
    """,
    str(key_id), str(token.workspace_id),
)
if not result:
    raise HTTPException(status_code=404, detail={"error": "api_key_not_found"})
```
Phase 16: extend the WHERE to `AND ($3::uuid IS NULL OR created_by_user_id = $3)` where `$3 = token.user_id if token.role == "viewer" else None`. The 404-not-403 indistinguishability rule (D-04) is preserved by reusing the existing `if not result: 404` pattern verbatim.

**PATCH endpoint pattern** (model on `alerts_api.py::patch_alert_rule` lines 47–98) — adapted shape Phase 16 must produce:
```python
@router.patch("/{key_id}", response_model=ApiKey)
async def update_api_key(
    key_id: UUID,
    body: ApiKeyUpdateRequest,
    token: TokenPayload = Depends(verify_token),
) -> ApiKey:
    # Build viewer filter (same idiom as DELETE)
    creator_filter = str(token.user_id) if token.role == "viewer" else None
    rows = await execute_query(
        """
        UPDATE api_keys
        SET name = $1
        WHERE id = $2
          AND workspace_id = $3
          AND ($4::uuid IS NULL OR created_by_user_id = $4)
        RETURNING id, name, last4, created_at, revoked_at, last_used_at
        """,
        body.name, str(key_id), str(token.workspace_id), creator_filter,
    )
    if not rows:
        raise HTTPException(status_code=404, detail={"error": "api_key_not_found"})
    logger.info("api_key.renamed workspace=%s id=%s", token.workspace_id, key_id)
    return ApiKey(**rows[0])
```
Per D-11: do NOT call `invalidate_api_key_cache` — hash is unchanged. Per D-09: name max_length 128 enforced by `ApiKeyUpdateRequest`.

**Error-handling pattern** (already in file, lines 144–145; reuse verbatim):
```python
if not result:
    raise HTTPException(status_code=404, detail={"error": "api_key_not_found"})
```

**402 plan-cap pattern (POST stays unchanged)** — verbatim from lines 66–77:
```python
if cap is not None and current >= cap:
    required = await _lowest_plan_with_api_key_count(current)
    raise HTTPException(
        status_code=402,
        detail={
            "error": "api_key_limit_reached",
            "limit": cap,
            "current": current,
            "required_plan": required,
            "upgrade_url": f"{settings.burnlens_frontend_url}/settings#billing",
        },
    )
```

---

### `burnlens_cloud/auth.py` — throttled `last_used_at` write (utility, fire-and-forget)

**Analog:** the cache-write idiom inside `get_workspace_by_api_key` (lines 528–579). Hook the throttled UPDATE into the success path right after the cache populate.

**Existing success-branch shape** (lines 553–579, verbatim):
```python
result = await execute_query(
    """
    SELECT w.id AS id, w.plan AS plan
    FROM api_keys ak
    JOIN workspaces w ON w.id = ak.workspace_id
    WHERE ak.key_hash = $1 AND ak.revoked_at IS NULL AND w.active = true
    LIMIT 1
    """,
    key_hash,
)
if not result:
    # Legacy fallback for keys created before the api_keys table landed.
    result = await execute_query(
        "SELECT id, plan FROM workspaces WHERE api_key_hash = $1 AND active = true",
        key_hash,
    )
if not result:
    return None
row = result[0]
workspace_id = str(row["id"])
plan = row["plan"]
_api_key_cache[key_hash] = (workspace_id, plan, time.time())
return (workspace_id, plan)
```

**Phase 16 mutation:** the primary SELECT must also `RETURN ak.id AS api_key_id`. Then immediately before `return (workspace_id, plan)`, schedule a fire-and-forget throttled UPDATE:
```python
# D-06/D-07: at-most-one write per key per minute, fire-and-forget.
# A stuck UPDATE must NEVER block ingest (CLAUDE.md fail-open posture).
api_key_id = row.get("api_key_id")
if api_key_id is not None:
    async def _touch_last_used():
        try:
            await execute_query(
                """
                UPDATE api_keys
                SET last_used_at = now()
                WHERE id = $1
                  AND (last_used_at IS NULL OR last_used_at < now() - interval '60 seconds')
                """,
                str(api_key_id),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("api_key.last_used_at update failed: %s", e)
    asyncio.create_task(_touch_last_used())
```
The `import asyncio` is already in scope at the top of `auth.py` (verify with grep before writing the plan). The cache hit path (line 540–543) also needs `api_key_id` — extend `_api_key_cache` tuple to `(workspace_id, plan, api_key_id, cached_at)` so the throttled write fires on cache hits too.

---

### `burnlens_cloud/auth.py::resend_verification` rewrite (controller, request-response)

**Analog:** existing handler (lines 1087–1125) plus the JWT-driven email-decrypt idiom in the same file (lines 1044–1049, used by `change_password`):
```python
user_email_row = await execute_query(
    "SELECT email_encrypted FROM users WHERE id = $1", user_id
)
if user_email_row and user_email_row[0].get("email_encrypted"):
    from .pii_crypto import decrypt_pii as _dec
    recipient = _dec(user_email_row[0]["email_encrypted"])
```

**Current code to be replaced verbatim** (lines 1087–1125):
```python
class ResendVerificationRequest(BaseModel):
    email: str

@router.post("/resend-verification", status_code=200)
async def resend_verification(request: ResendVerificationRequest):
    """Resend email verification link. Always returns 200."""
    from .pii_crypto import lookup_hash as _lh, decrypt_pii as _dec
    email_norm = request.email.strip().lower()
    rows = await execute_query(
        "SELECT id, email_encrypted, email_verified_at FROM users WHERE email_hash = $1",
        _lh(email_norm),
    )
    if not rows or rows[0].get("email_verified_at") is not None:
        return {"message": "If applicable, a verification email has been sent."}
    user_id = str(rows[0]["id"])
    recipient_email = _dec(rows[0]["email_encrypted"])
    # ... token invalidate + insert + send_verify_email (KEEP this tail unchanged) ...
```

**Phase 16 rewrite shape (D-12, D-14, D-15):**
- Drop `ResendVerificationRequest` class entirely (or keep but mark deprecated — check usages first).
- Endpoint signature becomes:
  ```python
  @router.post("/resend-verification", status_code=200)
  async def resend_verification(token: TokenPayload = Depends(verify_token)):
  ```
- Lookup by `id`, not by `email_hash`:
  ```python
  rows = await execute_query(
      "SELECT id, email_encrypted, email_verified_at FROM users WHERE id = $1",
      str(token.user_id),
  )
  ```
- All downstream logic (token invalidate, insert new auth_token, send_verify_email) stays verbatim from lines 1106–1124. Always-200 response shape preserved.

---

### `burnlens_cloud/models.py` — model extensions

**Analog:** lines 504–531 (verbatim, existing):
```python
class ApiKeyCreateRequest(BaseModel):
    """Request body for POST /api-keys.
    `name` is optional; defaults to "Primary" server-side if omitted.
    """
    name: Optional[str] = Field(None, max_length=64)

class ApiKey(BaseModel):
    id: UUID
    name: str
    last4: str
    created_at: datetime
    revoked_at: Optional[datetime] = None

class ApiKeyCreateResponse(ApiKey):
    key: str
```

**Phase 16 mutations (verbatim shape to add):**
```python
class ApiKeyCreateRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=128)  # D-09: 64 → 128

class ApiKey(BaseModel):
    id: UUID
    name: str
    last4: str
    created_at: datetime
    revoked_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None  # D-05

class ApiKeyUpdateRequest(BaseModel):
    """Request body for PATCH /api-keys/{key_id}.
    Single editable field — `name` (label or note). Max length matches
    ApiKeyCreateRequest (128).
    """
    name: str = Field(..., min_length=1, max_length=128)
```
Pydantic patch model precedent — `alerts_api.AlertRulePatch` (lines 17–20):
```python
class AlertRulePatch(BaseModel):
    enabled: Optional[bool] = None
    threshold_pct: Optional[int] = None
    extra_emails: Optional[List[str]] = None
```
Phase 16 differs: name is **required** (not optional) since this is a single-field PATCH; passing None is meaningless.

---

### Migration: `ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMPTZ`

**Analog:** `burnlens_cloud/database.py` line 930–932 (verbatim):
```python
# Phase 11: email verification timestamp on users.
# NULL = grandfathered-verified for pre-v1.2 users (no backfill needed).
await conn.execute("""
    ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ
""")
```

**Phase 16 addition** (place right after the existing partial index block at lines 894–897, BEFORE the Phase-11 backfill block):
```python
# Phase 16 (D-05): per-key last-used tracking.
# NULL = never used. Updated at most once per minute via throttled UPDATE
# in auth.get_workspace_by_api_key (D-06/D-07).
await conn.execute("""
    ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMPTZ
""")
```
Idempotency by `IF NOT EXISTS` — same pattern as line 931. No backfill required (NULL is the correct "never used" value).

---

### `frontend/src/app/api-keys/page.tsx` (new — full /api-keys page)

**Analog:** `frontend/src/app/alerts/page.tsx` (490 LOC) — the closest in-tree pattern for a Shell-wrapped CRUD list page with edit modal.

**Imports + shell wrapper pattern** (lines 1–9 + 484–489, verbatim):
```typescript
"use client";
import { useEffect, useState, useCallback } from "react";
import { BellIcon } from "lucide-react";
import Shell from "@/components/Shell";
import EmptyState from "@/components/EmptyState";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { useToast } from "@/lib/contexts/ToastContext";

// ... AlertsContent component ...

export default function AlertsPage() {
  return (
    <Shell>
      <AlertsContent />
    </Shell>
  );
}
```
**Phase 16 deviation:** UI-SPEC §"Icon library" forbids `lucide-react` for dashboard chrome — use inline SVG (see Sidebar `LockGlyph` lines 64–82 for the inline-SVG pattern). Replace `BellIcon` import with no icon import; key glyph is co-located in Sidebar only.

**Title pattern** (line 40–41, verbatim):
```typescript
useEffect(() => {
  document.title = "Alerts | BurnLens";
}, []);
```
Phase 16: `document.title = "API Keys | BurnLens"`.

**Fetch + auth-error pattern** (lines 43–56, verbatim):
```typescript
const fetchRules = useCallback(async () => {
  if (!session) return;
  setLoading(true);
  setError("");
  try {
    const data = await apiFetch("/api/v1/alert-rules", session.token);
    setRules(Array.isArray(data) ? data : []);
  } catch (err: any) {
    if (err instanceof AuthError) logout();
    else setError(err.message);
  } finally {
    setLoading(false);
  }
}, [session, logout]);
```
Phase 16: endpoint is `/api-keys` (no `/api/v1/` prefix — see `ApiKeysCard.tsx` line 106).

**Modal-on-Escape pattern** (lines 63–70, verbatim):
```typescript
useEffect(() => {
  if (!editingRule) return;
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape") setEditingRule(null);
  };
  window.addEventListener("keydown", onKeyDown);
  return () => window.removeEventListener("keydown", onKeyDown);
}, [editingRule]);
```
Phase 16: applies to `RevokeKeyModal` per UI-SPEC ("Backdrop click / Escape key — Close the modal (cancel)") — but NOT to `NewApiKeyModal` (blocking).

**Optimistic-update pattern** (lines 72–94, verbatim — useful for inline edit-label save):
```typescript
const handleToggle = async (rule: AlertRule) => {
  if (pendingId) return;
  const prev = rule.enabled;
  const ruleId = rule.id;
  setPendingId(ruleId);
  setRules((rs) => rs.map((r) => r.id === ruleId ? { ...r, enabled: !prev } : r));
  try {
    await apiFetch(`/api/v1/alert-rules/${ruleId}`, session!.token, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !prev }),
    });
    showToast("Alert rule updated", "success");
  } catch (err: any) {
    setRules((rs) => rs.map((r) => r.id === ruleId ? { ...r, enabled: prev } : r));
    if (err instanceof AuthError) logout();
    else showToast("Failed to update rule", "error");
  } finally {
    setPendingId(null);
  }
};
```
Phase 16: same shape for `handleSaveLabel` — optimistic update of `keys[].name`, revert on error, toast `Label updated` (success) / `Failed to update label.` (error). Endpoint: `PATCH /api-keys/{id}` with `{name}` body.

**Loading + error skeleton pattern** (lines 150–177, verbatim):
```typescript
if (loading) {
  return (
    <div style={{ padding: 16 }}>
      <div className="card">
        <div className="skeleton" style={{ height: 40, marginBottom: 8 }} />
        <div className="skeleton" style={{ height: 40 }} />
      </div>
    </div>
  );
}
if (error) {
  return (
    <div style={{ padding: 24 }}>
      <span className="error-inline" onClick={fetchRules} style={{ cursor: "pointer" }}>
        Couldn&apos;t load alert rules — retry &#x2197;
      </span>
    </div>
  );
}
```
Phase 16: copy exactly per UI-SPEC §"Page error state": `Failed to load keys.` + `Retry` link.

---

### `frontend/src/components/ApiKeysTable.tsx` (new — extracted)

**Analog:** `ApiKeysCard.tsx` lines 287–377 (verbatim — the existing table block).

**Table + status pattern** (lines 287–377):
```tsx
<table className="api-keys-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
  <thead>
    <tr style={{ textAlign: "left", color: "var(--muted)", fontSize: 12 }}>
      <th style={{ padding: "8px 12px", fontWeight: 500 }}>Name</th>
      <th style={{ padding: "8px 12px", fontWeight: 500 }}>Last 4</th>
      <th style={{ padding: "8px 12px", fontWeight: 500 }}>Created</th>
      <th style={{ padding: "8px 12px", fontWeight: 500 }}>Status</th>
      <th style={{ padding: "8px 12px", fontWeight: 500 }}>Actions</th>
    </tr>
  </thead>
  <tbody>
    {keys.map((k) => (
      <tr key={k.id} style={{ borderTop: "1px solid var(--border)" }}>
        <td style={{ padding: "10px 12px" }}>{k.name}</td>
        <td style={{ padding: "10px 12px" }}>
          <span className="api-keys-last4">····{k.last4}</span>
        </td>
        ...
```

**Phase 16 mutations:**
- Add new column: `Last used` between `Last 4` and `Created` (per UI-SPEC table-column order — five columns total: Name, Last 4, Last used, Created, Actions).
- Replace inline revoke-form with `RevokeKeyModal` open-state (D-19 modal vs. the current inline confirm).
- Add edit-pencil affordance (inline SVG, 14×14, `var(--muted)`) opening `EditKeyLabelInline`.
- Per UI-SPEC §"Status presentation": single list, active first then revoked at bottom (no tabs, no separate sections).
- Revoked rows: `opacity: 0.55`, Actions cell collapsed to `Revoked {MMM d, yyyy}` text.

**Date formatter to reuse** (lines 46–56, verbatim — extract to `lib/format.ts`):
```typescript
function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      year: "numeric", month: "short", day: "numeric",
    });
  } catch { return ""; }
}
```

---

### `frontend/src/components/RevokeKeyModal.tsx` (new)

**Analog:** `NewApiKeyModal.tsx` (entire file, 97 LOC) — modal scaffolding, `dismissBtnRef`, `aria-modal` wiring.

**Modal scaffold** (`NewApiKeyModal.tsx` lines 25–96, verbatim):
```tsx
interface NewApiKeyModalProps {
  open: boolean;
  plaintextKey: string;
  onDismiss: () => void;
}

export default function NewApiKeyModal({ open, plaintextKey, onDismiss }: NewApiKeyModalProps) {
  const dismissBtnRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (open) dismissBtnRef.current?.focus();
  }, [open]);
  if (!open) return null;
  return (
    <div className="api-key-modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="nak-title">
      <div className="api-key-modal-card">
        <h2 id="nak-title" className="api-key-modal-title">Your new key</h2>
        ...
        <div className="api-key-modal-actions">
          <button ref={dismissBtnRef} className="btn btn-cyan" onClick={onDismiss} type="button">
            {"I've saved it"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

**Phase 16 props (per UI-SPEC §"Revoke flow"):**
```tsx
interface RevokeKeyModalProps {
  open: boolean;
  keyName: string;
  last4: string;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}
```
- Title: `Revoke "{name}" (…{last4})?` — `name` in normal text, `(…{last4})` in `var(--font-mono)` `var(--muted)`.
- Body: `This key will stop working immediately. Apps using it will get 401 errors until you create a new key.`
- Cancel: `Keep key` (`.btn`, no color).
- Confirm: `Revoke key` (`.btn-red`).
- In-flight: button text → `Revoking…`, button disabled.
- **Differs from NewApiKeyModal:** Backdrop click and Escape DO close (UI-SPEC explicit). Add `onClick` handler on backdrop + Escape `useEffect` like alerts page lines 63–70.

**Backdrop-click pattern** (existing, ApiKeysCard lines 381–385, verbatim):
```tsx
<div
  className="api-key-modal-backdrop"
  onClick={(e) => {
    if (e.target === e.currentTarget) setShowCreate(false);
  }}
  role="dialog" aria-modal="true" aria-labelledby="ak-create-title"
>
```

---

### `frontend/src/components/EditKeyLabelInline.tsx` (new)

**Analog:** `ApiKeysCard.tsx` lines 332–369 (verbatim — the inline revoke-confirm form):
```tsx
<div className="api-keys-revoke-form">
  <input
    className="form-input api-keys-revoke-input"
    placeholder={`Type ${k.name} to confirm`}
    value={revokeConfirmText}
    onChange={(e) => setRevokeConfirmText(e.target.value)}
    onKeyDown={(e) => {
      if (e.key === "Enter" && revokeConfirmText === k.name) handleRevokeConfirm(k.id);
      if (e.key === "Escape") { setRevokingId(null); setRevokeConfirmText(""); }
    }}
    autoFocus
    aria-label="Type key name to confirm revocation"
  />
  <button className="btn btn-red" disabled={...} onClick={...} type="button">
    {revokingInFlight ? "Revoking…" : "Confirm"}
  </button>
  <button className="btn" onClick={...} type="button">Cancel</button>
</div>
```

**Phase 16 adaptation (per UI-SPEC §"Edit label flow"):**
- Replace name cell with `<input>` autofocused, `maxLength={128}`, placeholder `Label or note`, value pre-filled with current name.
- Save button cyan: `Save label` / `Saving…` (in-flight).
- Cancel button neutral: `Discard changes`.
- On Enter → save; on Escape → cancel (mirror lines 339–346 keydown handler).
- No-op save (same name) → still call PATCH (server returns 200 unchanged), flash green toast `Label updated`.

---

### `frontend/src/lib/format.ts` (extend or create) — `formatRelativeTime(iso)`

**Analog:** none — searched codebase, only `formatDate` exists (`ApiKeysCard.tsx` lines 46–56).

**Implementation contract from UI-SPEC §"Last-used column":**
```typescript
export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "Never used";
  const ms = Date.now() - new Date(iso).getTime();
  const s = Math.floor(ms / 1000);
  if (s < 60) return "Just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} minute${m === 1 ? "" : "s"} ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} hour${h === 1 ? "" : "s"} ago`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d} day${d === 1 ? "" : "s"} ago`;
  if (d < 30) {
    const w = Math.floor(d / 7);
    return `${w} week${w === 1 ? "" : "s"} ago`;
  }
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric", month: "short", day: "numeric",
  });
}
```
Co-locate `formatDate` (extracted from ApiKeysCard) in the same module. **Do not** import `date-fns` or `dayjs` (UI-SPEC §"Implementation note" forbids unbudgeted deps).

---

### `frontend/src/components/ApiKeysCard.tsx` (extend in-place)

**Analog:** self.

**Section-header link addition** (lines 210–222, verbatim — existing):
```tsx
<div className="section-header">
  <span className="section-header-title" style={{ fontWeight: 600 }}>
    API Keys
  </span>
  <button className="btn btn-cyan" onClick={() => setShowCreate(true)} disabled={atCap} type="button">
    Create key
  </button>
</div>
```

**Phase 16 mutation:** add `Manage all keys →` link inside `.section-header`, right of the Create button (or below it). Per UI-SPEC §"Settings page link":
```tsx
<a
  href="/api-keys"
  style={{ color: "var(--cyan)", fontSize: 13, fontWeight: 500 }}
>
  Manage all keys →
</a>
```
Use Next.js `<Link>` from `next/link` (already imported in BillingStatusBanner line 4 — same pattern). Per UI-SPEC: arrow is U+2192 literal, not SVG.

**Name input mutation** — find the create-modal input (lines 394–405) and bump to `maxLength={128}`. Currently no explicit maxLength is set; add it.

---

### `frontend/src/components/NewApiKeyModal.tsx` (extend)

**Analog:** self. Phase 16 is a one-line bump — the create-modal `<input>` lives in `ApiKeysCard.tsx` (lines 394–405), NOT in `NewApiKeyModal.tsx`. The NewApiKeyModal only displays plaintext and has no Name input. Confirm by re-reading `NewApiKeyModal.tsx` (97 LOC, verbatim above) — no `<input>` for name. **Recommendation:** the maxLength bump applies only to `ApiKeysCard.tsx` and the new `/api-keys` page's create flow, not to `NewApiKeyModal.tsx`. Plan author should reconcile this with UI-SPEC §"NewApiKeyModal copy" which says "raise client-side maxLength on the Name input from 64 to 128" — that input is in the parent (ApiKeysCard or new /api-keys page).

---

### `frontend/src/components/Sidebar.tsx` (extend)

**Analog:** self.

**Group entry pattern** (lines 56–61, verbatim):
```typescript
{
  label: "System",
  items: [
    { href: "/connections", label: "Connections" },
    { href: "/settings", label: "Settings" },
  ],
},
```

**Phase 16 mutation** — insert `{ href: "/api-keys", label: "API Keys" }` between Connections and Settings (UI-SPEC §"Sidebar entry": "placed between `Connections` and `Settings`").

**Inline-SVG glyph pattern** (lines 64–82 — `LockGlyph`, verbatim):
```tsx
function LockGlyph() {
  return (
    <svg
      className="sidebar-item-lock-glyph"
      width="12" height="12"
      viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="11" width="18" height="11" rx="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  );
}
```
**Phase 16 addition:** co-locate `KeyGlyph` next to `LockGlyph`. Per UI-SPEC §"Sidebar entry": 14×14, `stroke="currentColor"`, `strokeWidth="2"`, viewBox `0 0 24 24`, lucide "key" path inlined (do NOT import from `lucide-react`).

**SidebarItem optional icon field** — current interface (lines 10–18) does not have an icon field. Phase 16 may need to extend `SidebarItem` with an optional `icon?: React.ReactNode` to render the key glyph for this one entry; or render conditionally on `href === "/api-keys"`. UI-SPEC favors the latter for minimal interface drift.

---

### `frontend/src/components/BillingStatusBanner.tsx` (modify)

**Analog:** self — surgical removal of `localStorage.burnlens_owner_email` + body.

**Current handler** (lines 32–46, verbatim):
```typescript
async function handleResend() {
  if (resendStatus !== "idle") return;
  setResendStatus("sending");
  try {
    await fetch(`${API_BASE}/auth/resend-verification`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: session?.ownerEmail ?? "" }),
      credentials: "include",
    });
    setResendStatus("sent");
  } catch {
    setResendStatus("error");
  }
}
```

**Phase 16 mutation:**
```typescript
await fetch(`${API_BASE}/auth/resend-verification`, {
  method: "POST",
  credentials: "include",
});
```
- Drop `headers` (no body).
- Drop `body`.
- Drop the `session?.ownerEmail ?? ""` read.
- `credentials: "include"` is critical — server-side `verify_token` reads the `burnlens_session` HttpOnly cookie (auth.py line 223).

---

### `frontend/src/lib/hooks/useAuth.ts` (light edit)

**Analog:** self. The `ownerEmail` field stays in `AuthSession` and is still read from `localStorage` (lines 19, 66) for display purposes. Phase 16 changes are in **what consumes it**, not in this hook. No code change required unless the planner wants to mark `ownerEmail` optional (`ownerEmail?: string`) for clarity. Default behavior: leave as-is.

---

### `frontend/src/app/setup/page.tsx` (light edit)

**Analog:** self — line 34 (verbatim): `localStorage.setItem("burnlens_owner_email", data.workspace.owner_email);`. Per D-13 stays unchanged. Phase 16 makes no edit here. (Listed in scope for completeness; planner can drop it from the plan if no change is needed.)

---

### `tests/test_phase16_api_keys.py` (new)

**Analog:** `tests/test_phase13_alerts_api.py` (the closest cloud-API test pattern; lines 1–120 above are the verbatim shape).

**Imports + fixtures pattern** (lines 1–40, verbatim):
```python
import pytest
from unittest.mock import patch, AsyncMock
from uuid import uuid4
import time

from burnlens_cloud.models import TokenPayload
from burnlens_cloud.auth import verify_token as _verify_token

def _auth(app, token):
    """Override the verify_token FastAPI dependency for a single test."""
    app.dependency_overrides[_verify_token] = lambda: token

def _make_keys_app():
    from fastapi import FastAPI
    from burnlens_cloud.api_keys_api import router
    app = FastAPI()
    app.include_router(router)
    return app

@pytest.fixture
def owner_token():
    return TokenPayload(
        workspace_id=uuid4(), user_id=uuid4(),
        role="owner", plan="cloud",
        iat=int(time.time()), exp=int(time.time()) + 86400,
    )

@pytest.fixture
def viewer_token():
    return TokenPayload(
        workspace_id=uuid4(), user_id=uuid4(),
        role="viewer", plan="cloud",
        iat=int(time.time()), exp=int(time.time()) + 86400,
    )
```

**Test pattern** (lines 45–88, verbatim):
```python
@pytest.mark.asyncio
async def test_list_alert_rules_200(self, owner_token):
    from httpx import AsyncClient, ASGITransport
    app = _make_alerts_app()
    _auth(app, owner_token)
    mock_rows = [...]
    with patch("burnlens_cloud.alerts_api.execute_query", AsyncMock(return_value=mock_rows)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            response = await ac.get("/api/v1/alert-rules")
    assert response.status_code == 200
```

**Phase 16 test surface to cover (per CONTEXT D-15 + canonical_refs):**
- `test_list_keys_owner_returns_all` — owner gets full workspace list.
- `test_list_keys_viewer_returns_only_own` — viewer's GET WHERE clause includes `created_by_user_id`.
- `test_revoke_keys_viewer_404_on_other_creator` — 404 not 403 (D-04 indistinguishability).
- `test_patch_keys_renames_label` — `PATCH /api-keys/{id}` with `{name}` returns updated row.
- `test_patch_keys_max_length_128` — name=128 chars OK, name=129 rejected (422).
- `test_patch_keys_viewer_404_on_other_creator` — same 404 rule.
- `test_resend_verification_uses_jwt_not_body` — AUTH-08 regression (CONTEXT D-15): empty body + valid session JWT → 200, decrypts email_encrypted, sends. Mock `pii_crypto.decrypt_pii` and `email.send_verify_email`.
- `test_last_used_at_throttled_update` — second call within 60s does not produce a second UPDATE (mock `execute_query` and assert call count). Verify the SQL contains `last_used_at < now() - interval '60 seconds'`.

**No env-isolation header needed** — `test_phase13_alerts_api.py` does not have one (lines 1–10). Use the same minimal-imports pattern. (If pydantic-settings barfs at import time, copy the env-isolation block from `test_phase15_quota_hard.py` lines 23–48.)

---

## Shared Patterns

### 1. JWT role + indistinguishability 404
**Source:** `burnlens_cloud/api_keys_api.py` lines 134–145 (existing DELETE).
**Apply to:** new PATCH endpoint, modified GET endpoint.
**Rule:** When viewer attempts to read/edit/revoke a key they didn't create, the SQL UPDATE/SELECT returns 0 rows → endpoint raises `HTTPException(404, detail={"error": "api_key_not_found"})`. Never return 403.
**Verbatim:**
```python
if not result:
    raise HTTPException(status_code=404, detail={"error": "api_key_not_found"})
```

### 2. FastAPI auth dependency
**Source:** every existing controller (`api_keys_api.py`, `alerts_api.py`).
**Apply to:** PATCH endpoint, rewritten resend-verification.
**Verbatim:**
```python
token: TokenPayload = Depends(verify_token),
```
`TokenPayload` fields available: `workspace_id: UUID`, `user_id: UUID`, `role: str`, `plan: str`. Cookie + Bearer dual transport already wired (auth.py lines 215–236).

### 3. Fail-open / fire-and-forget
**Source:** `CLAUDE.md` §"Coding Standards": "log and continue, never crash the proxy". Phase 9 `_record_usage_and_maybe_notify` precedent (per CONTEXT §code_context).
**Apply to:** `last_used_at` UPDATE in `auth.get_workspace_by_api_key`.
**Pattern:**
```python
asyncio.create_task(_touch_last_used())  # never awaited; exceptions swallowed inside
```
Inside the task, wrap the UPDATE in `try/except Exception: logger.warning(...)`. The auth path returns immediately.

### 4. UI auth-error → logout
**Source:** `ApiKeysCard.tsx` lines 109–113, `alerts/page.tsx` lines 50–52.
**Apply to:** every fetch on the new `/api-keys` page + RevokeKeyModal/EditKeyLabelInline.
**Verbatim:**
```typescript
} catch (err: any) {
  if (err instanceof AuthError) logout();
  else setError(...);  // or showToast(...)
}
```

### 5. Toast feedback (Phase 13 ToastContext)
**Source:** `alerts/page.tsx` line 9, lines 84–90.
**Apply to:** revoke success/failure, label-edit success/failure.
**Verbatim:**
```typescript
import { useToast } from "@/lib/contexts/ToastContext";
const { showToast } = useToast();
showToast("Key revoked", "success");
showToast("Failed to revoke key. Please try again.", "error");
showToast("Label updated", "success");
showToast("Failed to update label.", "error");
```
Copy strings from UI-SPEC §"Revoke flow" and §"Edit label flow" verbatim.

### 6. Modal backdrop + escape
**Source:** `alerts/page.tsx` lines 63–70 (Escape) + `ApiKeysCard.tsx` lines 381–385 (backdrop click).
**Apply to:** `RevokeKeyModal` (D-19 says backdrop + Escape DO close it — non-destructive pre-confirmation).
**Note:** `NewApiKeyModal` is intentionally blocking — do NOT add backdrop/Escape there.

### 7. Plaintext-once invariant
**Source:** `NewApiKeyModal.tsx` (entire file) + `ApiKeysCard.tsx` lines 72–74, 134–135, 195–197.
**Apply to:** new `/api-keys` page must follow the same single-state-cell-with-dismiss pattern. The PATCH endpoint must NEVER return `key`. Only `ApiKeyCreateResponse` (POST) ever surfaces plaintext.
**Verbatim invariant from `NewApiKeyModal.tsx` file header:**
> "plaintext arrives as a prop reference and is rendered as a React text child inside the code element (auto-escaped). Never set via raw-HTML. No off-state stash; no global writes; no persistent storage."

### 8. Pre-emptive 402 / plan-cap UI
**Source:** `ApiKeysCard.tsx` lines 85–99 (cap derivation) + lines 224–242 (cap banner).
**Apply to:** new `/api-keys` page header. Reuse `useBilling()` + `nextPlanFor` exactly. Disabled-button tooltip copy: `Plan limit reached — upgrade to {required_plan} for more keys.` (UI-SPEC §"Plan-cap pre-emptive disable").

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `frontend/src/lib/format.ts::formatRelativeTime` | utility | transform | Codebase has only `formatDate` (absolute date). No relative-time formatter exists. UI-SPEC explicitly forbids `date-fns`/`dayjs` — must hand-write per the cascade in UI-SPEC §"Last-used column" (Just now / N minutes ago / N hours ago / N days ago / N weeks ago / absolute fallback at ≥30d). |
| `tests/test_keys.py` extension for `last_used_at` | test | n/a | `tests/test_keys.py` is the **local-proxy** key store test (`burnlens.keys`, sqlite, CLI `burnlens key`). It is NOT the cloud test. The cloud `last_used_at` column belongs to `burnlens_cloud.api_keys`, exercised via `tests/test_phase16_api_keys.py`. **Recommend the planner drop the "extend test_keys.py" item from the scope** — extending it would mix proxy and cloud concerns. CONTEXT §code_context lists this for completeness; researcher should confirm with planner. |

---

## Metadata

**Analog search scope:**
- Backend: `burnlens_cloud/{api_keys_api.py, alerts_api.py, auth.py, models.py, database.py, billing.py}`
- Frontend: `frontend/src/{components/{ApiKeysCard,NewApiKeyModal,Sidebar,BillingStatusBanner}.tsx, app/{alerts,setup}/page.tsx, lib/hooks/useAuth.ts}`
- Tests: `tests/{test_keys.py, test_phase13_alerts_api.py, test_phase15_quota_hard.py}`

**Files scanned:** 14
**Pattern extraction date:** 2026-05-10
