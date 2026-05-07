# Phase 13: Alert Management UI — Pattern Map

**Mapped:** 2026-05-05
**Files analyzed:** 5 (2 new, 3 modified)
**Analogs found:** 5 / 5

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `burnlens_cloud/alerts_api.py` | router/controller | request-response (CRUD read + partial update) | `burnlens_cloud/settings_api.py` | exact |
| `burnlens_cloud/main.py` | config/wiring | — | `burnlens_cloud/main.py` lines 12–22, 179–190 | exact (self) |
| `frontend/src/app/alerts/page.tsx` | component/page | request-response (fetch + optimistic mutation) | `frontend/src/app/budgets/page.tsx` | exact |
| `frontend/src/components/Sidebar.tsx` | component | — | `frontend/src/components/Sidebar.tsx` (self) | exact (self) |
| `tests/test_phase13_alerts_api.py` | test | — | `tests/test_settings_api.py` | exact |

---

## Pattern Assignments

### `burnlens_cloud/alerts_api.py` (router, request-response CRUD)

**Analog:** `burnlens_cloud/settings_api.py`

**Imports pattern** (settings_api.py lines 1–23):
```python
"""Alert rules API endpoints — list and patch workspace alert rules."""

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import verify_token, require_role
from .database import execute_query, execute_insert
from .models import TokenPayload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["alert-rules"])
```

Note: `settings_api.py` uses `prefix="/settings"`. For `alerts_api.py` the prefix is `/api/v1` (matching the dashboard_api.py pattern verified in RESEARCH.md). Tags should be `["alert-rules"]`.

**Auth/role pattern** (settings_api.py lines 34–43, 101–102, 292–305):
```python
# GET — viewer minimum
@router.get("/alert-rules")
async def list_alert_rules(
    token: TokenPayload = Depends(verify_token),
) -> List[dict]:
    await require_role("viewer", token)
    ...

# PATCH — owner only
@router.patch("/alert-rules/{rule_id}")
async def patch_alert_rule(
    rule_id: str,
    body: AlertRulePatch,
    token: TokenPayload = Depends(verify_token),
) -> dict:
    await require_role("owner", token)
    ...
```

**Core GET pattern** (settings_api.py lines 96–137 — execute_query + dict(r)):
```python
rows = await execute_query(
    """
    SELECT id, threshold_pct, channel, enabled,
           slack_webhook_url IS NOT NULL AS has_slack,
           extra_emails, created_at, updated_at
    FROM alert_rules
    WHERE workspace_id = $1
    ORDER BY threshold_pct
    """,
    token.workspace_id,
)
return [dict(r) for r in rows]
```
Critical: do NOT return `slack_webhook_url` plaintext. Return `has_slack: bool` only.

**Pydantic request model pattern** (settings_api.py lines 288–290):
```python
class AlertRulePatch(BaseModel):
    enabled: Optional[bool] = None
    threshold_pct: Optional[int] = None   # must be 80 or 100 if provided
    extra_emails: Optional[List[str]] = None  # full-replace semantics
```

**Dynamic SET clause + execute_insert + zero-row 404 pattern** (settings_api.py lines 317–341):
```python
# Build dynamic SET — never include None fields
fields: list[str] = []
params: list = []
idx = 1

if body.enabled is not None:
    fields.append(f"enabled = ${idx}")
    params.append(body.enabled)
    idx += 1
if body.threshold_pct is not None:
    if body.threshold_pct not in (80, 100):
        raise HTTPException(status_code=422, detail="threshold_pct must be 80 or 100")
    fields.append(f"threshold_pct = ${idx}")
    params.append(body.threshold_pct)
    idx += 1
if body.extra_emails is not None:
    fields.append(f"extra_emails = ${idx}")
    params.append(body.extra_emails)   # asyncpg accepts list[str] for TEXT[]
    idx += 1

if not fields:
    raise HTTPException(status_code=422, detail="no fields to update")

fields.append("updated_at = NOW()")
sql = f"""
    UPDATE alert_rules
    SET {', '.join(fields)}
    WHERE id = ${idx} AND workspace_id = ${idx + 1}
"""
params.extend([rule_id, str(token.workspace_id)])

# execute_insert — correct helper for UPDATE (not execute_query)
result = await execute_insert(sql, *params)
# Parse status string "UPDATE N" — verified pattern from settings_api.py line 341
count = int(result.split()[-1]) if result else 0
if count == 0:
    raise HTTPException(status_code=404, detail="rule_not_found")
```

**Error handling pattern** (settings_api.py lines 60–87):
```python
# HTTPException for business rule violations (raise directly — FastAPI handles)
raise HTTPException(status_code=422, detail="threshold_pct must be 80 or 100")
raise HTTPException(status_code=404, detail="rule_not_found")

# Exception for unexpected DB errors (log + re-raise as 500)
except Exception as e:
    logger.error(f"Failed to ...: {e}")
    raise HTTPException(status_code=500, detail="...")
```

---

### `burnlens_cloud/main.py` (config, router registration)

**Analog:** `burnlens_cloud/main.py` (self — adding one import + one include_router)

**Import block to follow** (main.py lines 12–22):
```python
from .auth import router as auth_router
from .ingest import router as ingest_router
from .dashboard_api import router as dashboard_router
from .billing import router as billing_router
from .team_api import router as team_router
from .api_keys_api import router as api_keys_router
from .settings_api import router as settings_router
from .compliance.audit import router as audit_router
from .deployment_api import router as deployment_router
from .stubs_api import router as stubs_router
from .cron_api import router as cron_router
# ADD after cron_router import:
from .alerts_api import router as alerts_router
```

**Router registration block to follow** (main.py lines 178–190):
```python
app.include_router(auth_router)
app.include_router(ingest_router)
app.include_router(dashboard_router)
app.include_router(billing_router)
app.include_router(team_router)
app.include_router(settings_router)
app.include_router(audit_router)
app.include_router(deployment_router)
app.include_router(stubs_router)
app.include_router(api_keys_router)
app.include_router(cron_router)      # /cron/evaluate-alerts (Phase 12)
# ADD:
app.include_router(alerts_router)    # /api/v1/alert-rules (Phase 13)
```

---

### `frontend/src/app/alerts/page.tsx` (component/page, request-response + optimistic mutation)

**Analog:** `frontend/src/app/budgets/page.tsx`

This file is a **full replacement** of the existing alerts/page.tsx (which uses the dead v1.0 proxy-alert schema). Do not preserve any existing content.

**Imports pattern** (budgets/page.tsx lines 1–7, alerts/page.tsx lines 1–7 for reference):
```typescript
"use client";

import { useEffect, useState, useCallback } from "react";
import Shell from "@/components/Shell";
import EmptyState from "@/components/EmptyState";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { useToast } from "@/lib/contexts/ToastContext";
```
Note: `useToast` is needed for optimistic-toggle feedback (present in existing alerts/page.tsx line 7 — keep it).

**TypeScript interface pattern** (alerts/page.tsx lines 9–19 — shows the v1.0 shape to REPLACE):
```typescript
// REPLACE the old AlertRule interface entirely with:
interface AlertRule {
  id: string;
  threshold_pct: number;        // 80 or 100
  channel: string;              // "email" | "slack" | "both"
  enabled: boolean;
  has_slack: boolean;           // backend returns bool, never the raw URL
  extra_emails: string[];
  created_at: string;
  updated_at: string;
}
```

**Data fetch pattern** (budgets/page.tsx lines 46–65):
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

useEffect(() => { fetchRules(); }, [fetchRules]);
```

**Loading skeleton pattern** (budgets/page.tsx lines 67–73):
```typescript
if (loading) {
  return (
    <div style={{ padding: 16 }}>
      <div className="skeleton" style={{ height: 48, marginBottom: 8 }} />
      <div className="skeleton" style={{ height: 48, marginBottom: 8 }} />
    </div>
  );
}
```

**Error inline pattern** (budgets/page.tsx lines 76–81):
```typescript
if (error) {
  return (
    <div style={{ padding: 24 }}>
      <span className="error-inline" onClick={fetchRules}>
        Couldn't load alert rules — retry &#x2197;
      </span>
    </div>
  );
}
```

**Stat strip pattern** (budgets/page.tsx lines 88–109):
```tsx
<div className="stat-strip" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
  <div className="stat-cell">
    <div className="stat-label">Total Rules</div>
    <div className="stat-value">{rules.length}</div>
  </div>
  <div className="stat-cell">
    <div className="stat-label">Enabled</div>
    <div className="stat-value">{rules.filter(r => r.enabled).length}</div>
  </div>
</div>
```
Note: Override default 4-col strip to 2 cols via inline `gridTemplateColumns`.

**Data table + section-header pattern** (alerts/page.tsx lines 116–148 — existing structure, adapted):
```tsx
<div className="card" style={{ marginTop: 24 }}>
  <div className="section-header">
    <span className="section-header-title">Alert Rules</span>
  </div>
  <table className="data-table">
    <thead>
      <tr>
        <th>Threshold</th>
        <th>Channel</th>
        <th>Slack</th>
        <th>Recipients</th>
        <th>Enabled</th>
        {session?.role === "owner" && <th></th>}
      </tr>
    </thead>
    <tbody>
      {rules.map((rule) => (
        <tr key={rule.id}>...</tr>
      ))}
    </tbody>
  </table>
</div>
```

**Optimistic toggle pattern** (from RESEARCH.md verified pattern — no existing codebase example, but follows the try/catch/revert idiom used in alerts/page.tsx handleDelete):
```typescript
const handleToggle = async (rule: AlertRule) => {
  if (pendingId) return;                          // prevent concurrent toggles
  const original = rule.enabled;
  setPendingId(rule.id);
  // Optimistic update
  setRules(prev => prev.map(r => r.id === rule.id ? { ...r, enabled: !original } : r));
  try {
    await apiFetch(`/api/v1/alert-rules/${rule.id}`, session!.token, {
      method: "PATCH",
      body: JSON.stringify({ enabled: !original }),
    });
    showToast("Alert rule updated", "success");
  } catch (err: any) {
    // Revert on failure
    setRules(prev => prev.map(r => r.id === rule.id ? { ...r, enabled: original } : r));
    if (err instanceof AuthError) logout();
    else showToast("Failed to update rule", "error");
  } finally {
    setPendingId(null);
  }
};
```

**Shell wrapper pattern** (budgets/page.tsx — outer export default):
```typescript
export default function AlertsPage() {
  return (
    <Shell>
      <AlertsContent />
    </Shell>
  );
}
```

**EmptyState pattern** (budgets/page.tsx imports EmptyState — use same component):
```tsx
<EmptyState
  title="No alert rules"
  description="Alert rules are seeded automatically when your workspace is created. Contact support if none appear."
/>
```

**document.title** — set via useEffect at component mount:
```typescript
useEffect(() => { document.title = "Alerts | BurnLens"; }, []);
```

---

### `frontend/src/components/Sidebar.tsx` (component, nav wiring)

**Analog:** `frontend/src/components/Sidebar.tsx` (self — one item addition to GROUPS array)

**GROUPS array structure** (Sidebar.tsx lines 25–61):
```typescript
const GROUPS: SidebarGroup[] = [
  { label: "Workspace", items: [...] },
  { label: "Attribution", items: [...] },
  {
    label: "Intelligence",
    items: [
      { href: "/waste", label: "Waste alerts" },
      { href: "/savings", label: "Savings" },
      { href: "/budgets", label: "Budgets" },
      // ADD after "Budgets":
      { href: "/alerts", label: "Alerts" },
      // No lockedForPlan — alerts visible to all paid plans
    ],
  },
  { label: "System", items: [...] },
];
```

**SidebarItem interface** (Sidebar.tsx lines 10–18) — no change needed, `href` + `label` fields are sufficient (no `lockedForPlan`, no `badge`).

**Active state + link rendering** (Sidebar.tsx lines 110–138) — unchanged; the existing `pathname === item.href` check handles active state for `/alerts` automatically.

---

### `tests/test_phase13_alerts_api.py` (test, unit)

**Analog:** `tests/test_settings_api.py`

**File-level setup pattern** (test_settings_api.py lines 1–24):
```python
"""Tests for alerts API endpoints (GET /api/v1/alert-rules, PATCH /api/v1/alert-rules/{id})."""

import pytest
from unittest.mock import patch, AsyncMock
from uuid import uuid4

from burnlens_cloud.models import TokenPayload
from burnlens_cloud.auth import verify_token as _verify_token


def _auth(app, token):
    """Override the verify_token FastAPI dependency for a single test."""
    app.dependency_overrides[_verify_token] = lambda: token


def _make_alerts_app():
    from fastapi import FastAPI
    from burnlens_cloud.alerts_api import router as alerts_router
    app = FastAPI()
    app.include_router(alerts_router)
    return app
```

**Fixture pattern** (test_settings_api.py lines 27–60):
```python
@pytest.fixture
def owner_token():
    return TokenPayload(
        workspace_id=uuid4(), user_id=uuid4(),
        role="owner", plan="cloud",
        iat=int(__import__("time").time()),
        exp=int(__import__("time").time()) + 86400,
    )

@pytest.fixture
def viewer_token():
    return TokenPayload(
        workspace_id=uuid4(), user_id=uuid4(),
        role="viewer", plan="cloud",
        iat=int(__import__("time").time()),
        exp=int(__import__("time").time()) + 86400,
    )
```

**Test class + AsyncClient pattern** (test_settings_api.py lines 63–94):
```python
class TestAlertRulesGet:

    @pytest.mark.asyncio
    async def test_get_returns_rules_for_workspace(self, owner_token):
        from httpx import AsyncClient, ASGITransport
        app = _make_alerts_app()
        _auth(app, owner_token)

        mock_rows = [
            {"id": str(uuid4()), "threshold_pct": 80, "channel": "email",
             "enabled": True, "has_slack": False, "extra_emails": [],
             "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"},
        ]
        with patch("burnlens_cloud.alerts_api.execute_query", AsyncMock(return_value=mock_rows)):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
                response = await ac.get("/api/v1/alert-rules")

        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["threshold_pct"] == 80
```

**Role-rejection test pattern** (test_settings_api.py lines 315–325 — 403 check):
```python
@pytest.mark.asyncio
async def test_patch_requires_owner_role(self, viewer_token):
    from httpx import AsyncClient, ASGITransport
    app = _make_alerts_app()
    _auth(app, viewer_token)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.patch(
            f"/api/v1/alert-rules/{uuid4()}",
            json={"enabled": True},
        )

    assert response.status_code == 403
```

**IDOR test pattern** (no existing example — new test to write, described in RESEARCH.md Pitfall 1):
```python
@pytest.mark.asyncio
async def test_patch_returns_404_for_wrong_workspace(self, owner_token):
    """UPDATE with workspace_id mismatch returns 0 rows → 404, not 200."""
    from httpx import AsyncClient, ASGITransport
    app = _make_alerts_app()
    _auth(app, owner_token)

    with patch("burnlens_cloud.alerts_api.execute_insert", AsyncMock(return_value="UPDATE 0")):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            response = await ac.patch(
                f"/api/v1/alert-rules/{uuid4()}",
                json={"enabled": True},
            )

    assert response.status_code == 404
```

**422 validation test pattern** (test_settings_api.py lines 299–312 — pre-DB rejection):
```python
@pytest.mark.asyncio
async def test_patch_invalid_threshold_returns_422(self, owner_token):
    from httpx import AsyncClient, ASGITransport
    app = _make_alerts_app()
    _auth(app, owner_token)

    with patch("burnlens_cloud.alerts_api.execute_insert", AsyncMock()) as mock_insert:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            response = await ac.patch(
                f"/api/v1/alert-rules/{uuid4()}",
                json={"threshold_pct": 50},
            )

    assert response.status_code == 422
    mock_insert.assert_not_called()   # DB must not be reached
```

---

## Shared Patterns

### Auth dependency injection
**Source:** `burnlens_cloud/settings_api.py` lines 30–43
**Apply to:** `alerts_api.py` — all endpoints
```python
token: TokenPayload = Depends(verify_token)
await require_role("viewer", token)   # GET endpoints
await require_role("owner", token)    # PATCH endpoints
```

### execute_insert for writes (not execute_query)
**Source:** `burnlens_cloud/settings_api.py` lines 318–341
**Apply to:** `alerts_api.py` — PATCH handler
```python
# CORRECT for UPDATE/INSERT:
result = await execute_insert(sql, *params)
count = int(result.split()[-1]) if result else 0

# WRONG — execute_query is SELECT-only:
# rows = await execute_query(sql, *params)
```

### apiFetch + AuthError logout
**Source:** `frontend/src/app/alerts/page.tsx` lines 55–62 (existing pattern — preserve it)
**Apply to:** `frontend/src/app/alerts/page.tsx` (new version) — all API calls
```typescript
try {
  const data = await apiFetch("/api/v1/alert-rules", session.token);
  ...
} catch (err: any) {
  if (err instanceof AuthError) logout();
  else setError(err.message);   // or showToast for mutation errors
}
```

### Optimistic mutation rollback
**Source:** `frontend/src/app/alerts/page.tsx` lines 99–108 (handleDelete pattern — adapt for toggle)
**Apply to:** `frontend/src/app/alerts/page.tsx` (new) — handleToggle
```typescript
// Keep pre-mutation value, revert in catch
const original = rule.enabled;
setRules(prev => prev.map(r => r.id === rule.id ? { ...r, enabled: !original } : r));
try { ... }
catch { setRules(prev => prev.map(r => r.id === rule.id ? { ...r, enabled: original } : r)); }
```

### useCallback for refetchable fetch functions
**Source:** `frontend/src/app/budgets/page.tsx` lines 46–65
**Apply to:** `frontend/src/app/alerts/page.tsx` — fetchRules (enables retry on error-inline click)
```typescript
const fetchRules = useCallback(async () => { ... }, [session, logout]);
useEffect(() => { fetchRules(); }, [fetchRules]);
```

### Test dependency_overrides pattern
**Source:** `tests/test_settings_api.py` lines 11–13
**Apply to:** `tests/test_phase13_alerts_api.py` — every test
```python
def _auth(app, token):
    app.dependency_overrides[_verify_token] = lambda: token
```

---

## No Analog Found

All 5 files have strong analogs. No files require falling back to RESEARCH.md patterns alone.

The one sub-pattern with no prior codebase example is the **dynamic PATCH SET clause builder** — this is a new idiom for the project (settings_api.py uses static SET clauses). The complete implementation is provided in the RESEARCH.md Code Examples section and reproduced in the Pattern Assignments above.

---

## Metadata

**Analog search scope:** `burnlens_cloud/`, `frontend/src/app/`, `frontend/src/components/`, `tests/`
**Files read:** settings_api.py, main.py, alerts/page.tsx (existing), budgets/page.tsx, Sidebar.tsx, test_settings_api.py, conftest.py (cloud_client fixture), 13-RESEARCH.md, 13-UI-SPEC.md
**Pattern extraction date:** 2026-05-05
