# Phase 13: Alert Management UI — Research

**Researched:** 2026-05-05
**Domain:** FastAPI REST API + Next.js 16 (App Router) UI
**Confidence:** HIGH — full codebase verified, no external unknowns

---

## Summary

Phase 13 adds the management surface for the alert rules system shipped in Phase 12. The backend (alert_rules table, alert_engine.py, cron endpoint, slack-webhook settings endpoint) is complete and verified. Phase 13's job is two-fold: (1) a new `burnlens_cloud/alerts_api.py` file exposing `GET /api/v1/alert-rules` and `PATCH /api/v1/alert-rules/{rule_id}`, and (2) a replacement of `frontend/src/app/alerts/page.tsx` (currently wired to the dead v1.0 proxy-alert schema) with a new cloud alert-rules management UI.

The scope is deliberately narrow: two new backend endpoints, one replaced frontend page, one Sidebar nav entry, and one pytest module. Every pattern — router shape, auth middleware, DB query helpers, frontend component idioms, test fixtures — is already established in the codebase and can be followed exactly.

**Primary recommendation:** New file `alerts_api.py` (single responsibility), full replacement of alerts `page.tsx` (not a tab split), optimistic toggle UX, replace-array contract for `extra_emails`, and pytest unit tests using the `cloud_client` / `dependency_overrides` pattern from `test_settings_api.py`.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ALERT-08 | Org owner can view all alert rules for their workspace on the `/alerts` page | `GET /api/v1/alert-rules` → query `alert_rules WHERE workspace_id = $1` ordered by `threshold_pct`; frontend table shows id, threshold_pct, channel, enabled, slack_webhook_url presence, extra_emails count |
| ALERT-09 | Org owner can enable/disable a rule, edit its threshold, and manage notification email recipients — changes take effect on the next cron evaluation | `PATCH /api/v1/alert-rules/{rule_id}` accepts `{enabled?, threshold_pct?, extra_emails?}`; frontend toggle (enabled), threshold select (80/100), email chip editor |

</phase_requirements>

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| List workspace alert rules | API / Backend | — | Auth-gated DB read; viewer role min |
| Toggle rule enabled/disabled | API / Backend | Browser/Client | Backend owns persistence; optimistic UI on client |
| Edit rule threshold_pct | API / Backend | Browser/Client | Constrained to (80, 100) — backend enforces CHECK constraint |
| Edit extra_emails array | API / Backend | Browser/Client | Backend owns TEXT[] column; full-replace array is simplest |
| Navigate to /alerts | Browser/Client | — | Next.js App Router client page + Sidebar link |
| Display rules table | Browser/Client | — | `"use client"` page with useEffect + apiFetch |

---

## Standard Stack

### Core (already installed — verified)
| Library | Version | Purpose | Notes |
|---------|---------|---------|-------|
| FastAPI | in pyproject.toml | APIRouter, Depends, HTTPException | [VERIFIED: burnlens_cloud/main.py] |
| Pydantic | v2 (via FastAPI) | Request/response models | [VERIFIED: burnlens_cloud/models.py] |
| asyncpg | project dep | execute_query, execute_insert | [VERIFIED: burnlens_cloud/database.py] |
| Next.js | 16.2.4 | App Router, "use client" pages | [VERIFIED: frontend/package.json] |
| React | 19.2.4 | useState, useEffect | [VERIFIED: frontend/package.json] |
| pytest + pytest-asyncio | project dep | Unit tests | [VERIFIED: tests/test_phase12_alerts.py] |

### No new dependencies required
All tooling for this phase is already present. [VERIFIED: package.json, pyproject.toml pattern from prior phases]

---

## Architecture Patterns

### System Architecture Diagram

```
Browser (Org Owner)
      │  GET /alerts
      ▼
Next.js App Router — /alerts/page.tsx
  ("use client" — useEffect on mount)
      │  GET /api/v1/alert-rules        (apiFetch with session cookie)
      │  PATCH /api/v1/alert-rules/{id} (optimistic toggle / edit save)
      ▼
Railway FastAPI — burnlens_cloud/alerts_api.py
  router = APIRouter(prefix="/api/v1", tags=["alert-rules"])
  verify_token → TokenPayload (workspace_id, role)
  require_role("viewer") for GET
  require_role("owner") for PATCH
      │  SELECT / UPDATE
      ▼
PostgreSQL — alert_rules table
  (id, workspace_id, threshold_pct, channel, enabled,
   slack_webhook_url, extra_emails, created_at, updated_at)
```

### Recommended Project Structure
```
burnlens_cloud/
├── alerts_api.py          # NEW: GET /api/v1/alert-rules + PATCH /api/v1/alert-rules/{id}
├── main.py                # ADD: import + include_router(alerts_router)
│
frontend/src/app/alerts/
├── page.tsx               # REPLACE: remove v1.0 proxy-alert UI; add cloud alert-rules UI
│
frontend/src/components/
├── Sidebar.tsx            # PATCH: add "Alerts" item to Intelligence group
│
tests/
├── test_phase13_alerts_api.py   # NEW: pytest unit tests for alerts_api.py
```

### Pattern 1: Backend Router (follow settings_api.py exactly)
**What:** New file, own APIRouter, `prefix="/api/v1"`, imported and mounted in `main.py`.
**When to use:** Any new feature vertical. Do not add to settings_api.py (OTEL/pricing domain, not alerting).

```python
# Source: burnlens_cloud/settings_api.py (verified pattern)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from .auth import verify_token, require_role
from .database import execute_query, execute_insert
from .models import TokenPayload

router = APIRouter(prefix="/api/v1", tags=["alert-rules"])
```

### Pattern 2: GET endpoint — list rules for workspace
```python
# Source: pattern from dashboard_api.py + alert_engine.py (verified)
@router.get("/alert-rules")
async def list_alert_rules(
    token: TokenPayload = Depends(verify_token),
) -> List[dict]:
    await require_role("viewer", token)
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

Note: Do NOT return `slack_webhook_url` plaintext — it is a secret. Return `has_slack: bool` only. [VERIFIED: alert_engine.py logs "webhook_url is not logged — it is a secret"]

### Pattern 3: PATCH endpoint — update a single rule
```python
# Source: pattern from settings_api.py update_slack_webhook (verified)
class AlertRulePatch(BaseModel):
    enabled: Optional[bool] = None
    threshold_pct: Optional[int] = None   # must be 80 or 100 if provided
    extra_emails: Optional[List[str]] = None  # full replace

@router.patch("/alert-rules/{rule_id}")
async def patch_alert_rule(
    rule_id: str,
    body: AlertRulePatch,
    token: TokenPayload = Depends(verify_token),
) -> dict:
    await require_role("owner", token)
    # 1. Verify rule belongs to token.workspace_id (anti-IDOR)
    # 2. Validate threshold_pct IN (80, 100) if provided
    # 3. Build dynamic SET clause for non-None fields only
    # 4. UPDATE ... SET ..., updated_at = NOW() WHERE id = $N AND workspace_id = $M
    # 5. Return updated row
```

**IDOR prevention is mandatory:** The WHERE clause must always include `AND workspace_id = $workspace_id` — never look up a rule by id alone. [ASSUMED — standard security practice; codebase has no prior PATCH endpoint to verify against, but this is the correct pattern for multi-tenant isolation]

### Pattern 4: Register router in main.py
```python
# Source: burnlens_cloud/main.py lines 179–190 (verified)
from .alerts_api import router as alerts_router
# in get_app():
app.include_router(alerts_router)  # /api/v1/alert-rules
```

### Pattern 5: Frontend page structure
```typescript
// Source: frontend/src/app/alerts/page.tsx + settings/page.tsx (verified)
"use client";
import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { useToast } from "@/lib/contexts/ToastContext";

// AlgoritmsContent inside, AlertsPage default export wrapping with <Shell>
```

### Pattern 6: Sidebar nav addition
```typescript
// Source: frontend/src/components/Sidebar.tsx GROUPS array (verified)
// In the "Intelligence" group, add after "Budgets":
{ href: "/alerts", label: "Alerts" },
// No lockedForPlan — alerts are available to all paid plans (cloud/teams get rules seeded)
```

### Pattern 7: Test fixture pattern
```python
# Source: tests/test_settings_api.py (verified — closest structural match)
# uses cloud_client fixture from conftest.py + app.dependency_overrides[verify_token]

def _make_alerts_app():
    from fastapi import FastAPI
    from burnlens_cloud.alerts_api import router as alerts_router
    app = FastAPI()
    app.include_router(alerts_router)
    return app

@pytest.fixture
def owner_token():
    return TokenPayload(
        workspace_id=uuid4(), user_id=uuid4(),
        role="owner", plan="cloud",
        iat=int(time.time()), exp=int(time.time()) + 86400,
    )
```

### Anti-Patterns to Avoid
- **Returning slack_webhook_url in the API response:** It is a secret. Return `has_slack: bool` (bool: whether the field is non-null) only. The settings page already handles the actual webhook write via `PUT /settings/slack-webhook`.
- **Accepting threshold_pct values other than 80 or 100:** The DB has a CHECK constraint. The API must validate and return 422 before hitting the DB, not rely on a DB error propagating up.
- **Tab split (proxy alerts + cloud alerts in one page):** The cloud dashboard is 100% cloud-side. The v1.0 proxy-alert schema (`name`, `metric`, `threshold`, `provider_filter`) has no backend in burnlens_cloud. The existing page should be replaced entirely.
- **Buffering all fields into a static SET clause:** If `body.threshold_pct` is None, do not include it in the UPDATE. Build dynamically to avoid accidentally NULLing fields not sent in the patch.
- **Calling execute_query for a write:** Use `execute_insert` (which calls `conn.execute`). The naming is misleading — `execute_insert` is the right helper for UPDATE/INSERT. [VERIFIED: database.py]

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Auth verification | Custom token decode | `verify_token` Depends | Already handles cookie-based sessions (C-3 security model) |
| Role enforcement | if token.role == "owner" | `require_role("owner", token)` | Handles hierarchy (owner > admin > viewer), raises 403 |
| DB query execution | Raw pool.acquire | `execute_query` / `execute_insert` | Correct pool management, already used everywhere |
| Email validation for extra_emails | Custom regex | Pydantic EmailStr or simple @-check | Field is TEXT[] — basic format check is sufficient; no deliverability check needed |
| Optimistic UI rollback | Custom state machine | useState + try/catch revert | Simple two-state toggle; revert on error is 3 lines |

---

## Common Pitfalls

### Pitfall 1: IDOR on PATCH /api/v1/alert-rules/{rule_id}
**What goes wrong:** An owner of workspace A crafts a PATCH request with a rule_id belonging to workspace B.
**Why it happens:** Lookup by rule_id only, without workspace_id scoping.
**How to avoid:** Always include `WHERE id = $rule_id AND workspace_id = $token.workspace_id` in the UPDATE. If 0 rows updated, return 404.
**Warning signs:** Test for it explicitly — send a rule_id from a different workspace, expect 404 not 200.

### Pitfall 2: Returning 200 with stale data after PATCH
**What goes wrong:** UPDATE runs but frontend re-fetches old data (optimistic update was applied but server state differs).
**Why it happens:** Optimistic UI applied immediately; if server 422s, UI is inconsistent.
**How to avoid:** On PATCH error, revert optimistic state to previous value using functional setState: `setRules(prev => prev.map(r => r.id === id ? originalRule : r))`. Keep a copy of the pre-optimistic state before applying.

### Pitfall 3: threshold_pct constraint not validated in API layer
**What goes wrong:** PATCH sends `threshold_pct: 50`, hits the DB CHECK constraint, asyncpg raises an `asyncpg.exceptions.CheckViolationError`, which FastAPI renders as a 500.
**Why it happens:** Relying on DB to enforce the business rule rather than Pydantic validation.
**How to avoid:** Add a Pydantic `@field_validator` on `AlertRulePatch.threshold_pct` or an explicit check with `raise HTTPException(status_code=422, detail="threshold_pct must be 80 or 100")`.

### Pitfall 4: extra_emails chip UI — enter-key form submission
**What goes wrong:** User types an email, presses Enter to add it as a chip, but the keydown event propagates and submits the surrounding form.
**Why it happens:** `<input>` inside a `<form>` with a submit button; Enter on input triggers form submit.
**How to avoid:** On the email input's `onKeyDown`, call `e.preventDefault()` when `e.key === "Enter"`, then add the email to the chip array. Use a separate save button for the full PATCH.

### Pitfall 5: `execute_insert` return value parsing for zero-row UPDATE
**What goes wrong:** `UPDATE ... WHERE id = $1 AND workspace_id = $2` finds no row (wrong workspace or wrong id). `execute_insert` returns `"UPDATE 0"`. Code interprets this as success.
**Why it happens:** The helper returns a status string, not a row count integer.
**How to avoid:** Parse the count: `int(result.split()[-1]) if result else 0`. If `count == 0`, raise `HTTPException(status_code=404, detail="rule_not_found")`.
[VERIFIED: settings_api.py line 341 uses exactly this pattern]

### Pitfall 6: Next.js 16 — AGENTS.md warning applies
**What goes wrong:** Code written from training-data knowledge of Next.js 13/14 conventions (e.g., `metadata` exports, `generateStaticParams`, `cookies()` from `next/headers`) may not match Next.js 16.2.4 conventions.
**Why it happens:** The AGENTS.md explicitly warns that this Next.js version has breaking changes.
**How to avoid:** For `page.tsx`, stay strictly within the already-verified pattern — `"use client"`, `useState`, `useEffect`, `apiFetch`, `Shell` wrapper. Do not introduce any server component patterns or Next.js-specific imports beyond what the existing pages already use. [VERIFIED: frontend/AGENTS.md, frontend/CLAUDE.md]

---

## Code Examples

### Verified: dynamic SET clause builder for PATCH
```python
# Source: pattern needed — no existing PATCH endpoint to copy from.
# Follows same spirit as settings_api.py explicit UPDATE blocks.
# [ASSUMED pattern — standard FastAPI PATCH idiom]
fields = []
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
    params.append(body.extra_emails)  # asyncpg accepts list[str] for TEXT[]
    idx += 1

if not fields:
    raise HTTPException(status_code=422, detail="no fields to update")

fields.append(f"updated_at = NOW()")
sql = f"""
    UPDATE alert_rules
    SET {', '.join(fields)}
    WHERE id = ${idx} AND workspace_id = ${idx + 1}
"""
params.extend([rule_id, str(token.workspace_id)])
result = await execute_insert(sql, *params)
count = int(result.split()[-1]) if result else 0
if count == 0:
    raise HTTPException(status_code=404, detail="rule_not_found")
```

### Verified: asyncpg TEXT[] array handling
asyncpg passes Python `list[str]` directly to Postgres `TEXT[]` parameters — no special encoding needed. [VERIFIED: alert_rules schema + asyncpg docs behavior]

### Verified: optimistic toggle pattern (frontend)
```typescript
// Source: pattern from alerts/page.tsx toggle shape (adapted)
const handleToggle = async (rule: AlertRule) => {
  const original = rule.enabled;
  // Optimistic update
  setRules(prev => prev.map(r => r.id === rule.id ? { ...r, enabled: !r.enabled } : r));
  try {
    await apiFetch(`/api/v1/alert-rules/${rule.id}`, session.token, {
      method: "PATCH",
      body: JSON.stringify({ enabled: !original }),
    });
  } catch (err: any) {
    // Revert
    setRules(prev => prev.map(r => r.id === rule.id ? { ...r, enabled: original } : r));
    if (err instanceof AuthError) logout();
    else showToast("Failed: " + err.message, "error");
  }
};
```

---

## State of the Art

| Old (existing page) | Phase 13 Replacement | Why |
|---------------------|---------------------|-----|
| v1.0 proxy-alert schema (`name`, `metric`, `threshold`, `provider_filter`) | Cloud `alert_rules` schema (`threshold_pct`, `channel`, `enabled`, `extra_emails`) | Phase 12 ships the real cloud alert engine; proxy-alert backend never shipped in burnlens_cloud |
| `POST /api/v1/alerts` (create alert) | No create endpoint — rules are seeded automatically at 80% and 100% | Cloud rules are auto-seeded on workspace creation; Phase 13 is MANAGEMENT only (enable/disable/edit), not create/delete |
| `DELETE /api/v1/alerts/{id}` | No delete endpoint | MVP: only 2 rules per workspace (80%, 100%); deletion not in scope for ALERT-08/09 |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | PATCH dynamic SET clause is the correct approach (no prior PATCH endpoint in codebase to copy from) | Code Examples | Low — this is standard FastAPI practice; the pattern composes from verified building blocks |
| A2 | IDOR check via `AND workspace_id = $N` in UPDATE WHERE clause is the correct multi-tenant isolation approach | Architecture Patterns | Medium — if wrong, cross-workspace data mutation is possible; validate in test |
| A3 | `extra_emails` full-array replace (not add/remove individual emails) is acceptable UX for MVP | Architecture Patterns | Low — simpler backend contract; if users have 10+ emails this may be awkward, but the constraint of only 2 rules per workspace keeps the blast radius small |
| A4 | No `lockedForPlan` gate on the Alerts sidebar item | Architecture Patterns | Low — cloud/teams workspaces get rules seeded; free plan workspaces have no rules but can still view the (empty) page without breaking anything |

---

## Open Questions (RESOLVED)

1. **Should the Alerts page show the last-fired event timestamp per rule?**
   - What we know: `alert_events` table has `fired_at` and `status` per rule. The data is available.
   - What's unclear: ALERT-08 says "view all alert rules" — no explicit mention of history. Adding a "Last fired" column would be useful but out of stated scope.
   - RESOLVED: Defer — stay strictly within ALERT-08/09 scope. A "last fired" column can be added in a future phase. Keep the GET response simple.

2. **Should the email chip editor validate email format on the frontend?**
   - What we know: `extra_emails` is `TEXT[]` with no DB-level format constraint. Backend currently does no validation on this field.
   - What's unclear: The REQUIREMENTS say "manage notification email recipients" but do not specify format enforcement.
   - RESOLVED: Add a basic `@`-contains check on the frontend chip add, and optionally a Pydantic `EmailStr` validator on the backend's `AlertRulePatch.extra_emails` items. This prevents obvious garbage values without over-engineering.

---

## Environment Availability

Step 2.6: SKIPPED — Phase 13 is purely code changes to existing Railway (Python) and Vercel (Next.js) services. No new external dependencies, CLIs, or infrastructure required.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 + pytest-asyncio |
| Config file | `pyproject.toml` |
| Quick run command | `pytest tests/test_phase13_alerts_api.py -x --tb=short` |
| Full suite command | `pytest tests/test_phase13_alerts_api.py tests/test_phase12_alerts.py -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ALERT-08 | GET /api/v1/alert-rules returns 200 + list of rules | unit | `pytest tests/test_phase13_alerts_api.py::test_list_alert_rules_200 -x` | Wave 0 |
| ALERT-08 | GET returns only rules for the authenticated workspace | unit | `pytest tests/test_phase13_alerts_api.py::test_list_rules_scoped_to_workspace -x` | Wave 0 |
| ALERT-08 | Viewer role can read rules | unit | `pytest tests/test_phase13_alerts_api.py::test_list_rules_viewer_allowed -x` | Wave 0 |
| ALERT-09 | PATCH enabled=False disables a rule | unit | `pytest tests/test_phase13_alerts_api.py::test_patch_toggle_enabled -x` | Wave 0 |
| ALERT-09 | PATCH threshold_pct=50 returns 422 | unit | `pytest tests/test_phase13_alerts_api.py::test_patch_invalid_threshold -x` | Wave 0 |
| ALERT-09 | PATCH extra_emails replaces the full array | unit | `pytest tests/test_phase13_alerts_api.py::test_patch_extra_emails -x` | Wave 0 |
| ALERT-09 | PATCH rule from different workspace returns 404 | unit | `pytest tests/test_phase13_alerts_api.py::test_patch_idor_protection -x` | Wave 0 |
| ALERT-09 | Viewer role cannot PATCH | unit | `pytest tests/test_phase13_alerts_api.py::test_patch_viewer_forbidden -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_phase13_alerts_api.py -x --tb=short`
- **Per wave merge:** `pytest tests/test_phase13_alerts_api.py tests/test_phase12_alerts.py -v`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_phase13_alerts_api.py` — covers all ALERT-08 + ALERT-09 backend cases listed above
- [ ] Conftest fixture re-use: the `cloud_client` pattern from `conftest.py` needs a variant for the alerts router — can be a local `_make_alerts_app()` function inside the test file (see `_make_cron_app()` in `test_phase12_alerts.py`)

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | `verify_token` dependency — HttpOnly cookie session (C-3, already live) |
| V3 Session Management | no | Handled at auth layer, not this feature |
| V4 Access Control | yes | `require_role("viewer")` for GET; `require_role("owner")` for PATCH; IDOR guard in WHERE clause |
| V5 Input Validation | yes | Pydantic `AlertRulePatch` model; explicit threshold_pct enum check; extra_emails format check |
| V6 Cryptography | no | slack_webhook_url is not returned in GET response (treated as secret); no new crypto needed |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| IDOR — PATCH rule belonging to another workspace | Tampering | `WHERE id = $rule_id AND workspace_id = $token.workspace_id` in all UPDATE queries |
| Unauthorized rule mutation by viewer | Elevation of Privilege | `require_role("owner", token)` raises 403 before any DB write |
| Slack webhook URL exposure | Information Disclosure | GET response returns `has_slack: bool`, never the URL string |
| threshold_pct injection (non-enum value) | Tampering | Pydantic validation + explicit 422 before DB write; DB CHECK is defense-in-depth |

---

## Project Constraints (from CLAUDE.md)

| Constraint | Source | Impact on Phase 13 |
|------------|--------|-------------------|
| Type hints on all function signatures | CLAUDE.md Coding Standards | All Python functions in `alerts_api.py` must be fully typed |
| Docstrings on all public functions | CLAUDE.md Coding Standards | Every `@router.get`/`@router.patch` handler needs a docstring |
| `async/await` for all I/O | CLAUDE.md Coding Standards | No sync DB calls — use `execute_query` / `execute_insert` |
| Error handling: log and continue | CLAUDE.md Coding Standards | Catch exceptions in the API layer, log, return appropriate HTTP error |
| No React, no build step for dashboard | CLAUDE.md Architecture | N/A — alerts UI is in the Next.js frontend (Zone 3), not the OSS proxy dashboard |
| 7 dependencies only (OSS proxy) | CLAUDE.md Key Design Principles | N/A — this phase touches burnlens_cloud + Next.js frontend, not the OSS proxy |
| This Next.js has breaking changes from training data | frontend/AGENTS.md | Do NOT introduce any Next.js patterns not already present in existing pages; stay within the `"use client"` + `useEffect` + `apiFetch` idiom already verified |

---

## Sources

### Primary (HIGH confidence)
- `burnlens_cloud/database.py` — alert_rules and alert_events table schema (lines 879–929), verified column names and constraints
- `burnlens_cloud/alert_engine.py` — how rules are queried and what fields matter to the engine (SELECT id, threshold_pct, channel, slack_webhook_url, extra_emails)
- `burnlens_cloud/settings_api.py` — APIRouter pattern, require_role usage, SlackWebhookRequest model, execute_insert return value parsing (line 341)
- `burnlens_cloud/dashboard_api.py` — router prefix pattern `"/api/v1"`, require_role definition
- `burnlens_cloud/main.py` — how to add a new router (lines 179–190)
- `burnlens_cloud/models.py` — TokenPayload fields (workspace_id, user_id, role, plan, iat, exp, email_verified)
- `frontend/src/app/alerts/page.tsx` — existing page (to be replaced); confirmed it uses dead v1.0 schema
- `frontend/src/lib/api.ts` — apiFetch, AuthError, cookie-based auth (C-3)
- `frontend/src/components/Sidebar.tsx` — GROUPS structure, Intelligence group (lines 46–53)
- `frontend/src/components/Shell.tsx` — Shell wrapper pattern
- `tests/test_phase12_alerts.py` — test patterns: AsyncMock, _make_cron_app, dependency_overrides
- `tests/test_settings_api.py` — closest structural match; cloud_client fixture, TokenPayload construction
- `tests/conftest.py` — cloud_client fixture definition (lines 72–90)

### Secondary (MEDIUM confidence)
- `frontend/AGENTS.md` / `frontend/CLAUDE.md` — Next.js 16 breaking changes warning; stay within proven page patterns

---

## Metadata

**Confidence breakdown:**
- Backend API design: HIGH — patterns fully verified in settings_api.py, dashboard_api.py, cron_api.py
- Frontend page replacement: HIGH — existing page fully read; Shell/apiFetch/useToast pattern well established
- Test patterns: HIGH — test_settings_api.py and test_phase12_alerts.py provide direct copy-paste templates
- IDOR guard pattern: MEDIUM — no existing PATCH endpoint to copy from, but the WHERE-clause pattern is standard and correct

**Research date:** 2026-05-05
**Valid until:** 2026-06-05 (stable — no fast-moving external dependencies)
