# Phase 14: Budget-Aware Model Downgrade Routing — Context

**Gathered:** 2026-05-05
**Status:** Ready for planning
**Source:** PRD spec (inline args) + codebase inspection

---

<domain>
## Phase Boundary

Deliver budget-aware model downgrade routing to the open-source proxy package
(`burnlens/`). When a request arrives and the caller's remaining budget is below
a configurable threshold, BurnLens silently rewrites the `model` field to a
cheaper tier instead of returning HTTP 429. The caller sees a valid API response
from the cheaper model; their code requires zero changes.

**In scope:**
- DOWNGRADE_MAP + `get_downgrade_model()` helper
- `RoutingConfig` dataclass + YAML parse in `config.py`
- New file `burnlens/proxy/router.py` with `RouteDecision` + `decide_route()`
- Interceptor integration: body rewrite, cost-model update, log columns
- DB migration: `routed_model TEXT`, `downgrade_reason TEXT` on `requests` table
- Dashboard: `/api/routing-stats` endpoint + "Downgrades Today" stat card + amber badge on request rows
- CLI: `burnlens routing [--today] [--json]` command
- Test suite: `tests/test_router.py` (12 tests specified)

**Out of scope:**
- Provider-level model existence validation (no API call to verify the target model exists)
- Per-model downgrade chains deeper than one hop
- Downgrade on streaming requests (body rewrite is the same — include it)
- Cloud-side (burnlens_cloud/) changes

</domain>

<decisions>
## Implementation Decisions

### D-01 — DOWNGRADE_MAP location
**Locked:** Add `DOWNGRADE_MAP` and `get_downgrade_model()` to `burnlens/providers/downgrade.py`
(new file). **Not** in `burnlens/proxy/providers.py` — that file is a backward-compat shim and
must not gain new logic. Import from `burnlens.providers.downgrade` in the router.

Map contents (locked):
```python
DOWNGRADE_MAP = {
    # OpenAI
    "gpt-4o":                     "gpt-4o-mini",
    "gpt-4-turbo":                "gpt-4o-mini",
    "o1":                         "gpt-4o-mini",
    "o3":                         "gpt-4o-mini",
    "o1-mini":                    "gpt-4o-mini",
    # Anthropic
    "claude-opus-4-6":            "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6":          "claude-haiku-4-5-20251001",
    "claude-3-5-sonnet-20241022": "claude-haiku-4-5-20251001",
    # Google
    "gemini-1.5-pro":             "gemini-1.5-flash",
    "gemini-2.0-pro":             "gemini-1.5-flash",
}

def get_downgrade_model(model: str) -> str | None:
    """Return cheaper alternative, or None if already cheapest tier."""
    return DOWNGRADE_MAP.get(model)
```

### D-02 — Config schema
**Locked:** Add `RoutingConfig` dataclass to `config.py` and a `routing` field on `BurnLensConfig`.
YAML key is `routing:`.

```python
@dataclass
class RoutingConfig:
    budget_downgrade: bool = True
    downgrade_threshold_pct: float = 20.0
    downgrade_threshold_usd: float = 5.00
    log_downgrades: bool = True
```

`BurnLensConfig` gains: `routing: RoutingConfig = field(default_factory=RoutingConfig)`

Parse in `load_config()` under key `routing:` (same pattern as existing `cloud:`, `email:` blocks).

### D-03 — Router file
**Locked:** New file `burnlens/proxy/router.py`.

```python
@dataclass
class RouteDecision:
    original_model: str
    routed_model: str
    downgraded: bool
    reason: str   # "budget_pct" | "budget_usd" | "no_downgrade_needed" | "no_alternative" | "no_budget" | "error"
    budget_remaining_usd: float
    budget_remaining_pct: float
```

```python
async def decide_route(
    model: str,
    tag_team: str | None,
    tag_customer: str | None,
    config: "BurnLensConfig",
    db_path: str,
) -> RouteDecision:
```

Budget priority order (highest to lowest):
1. Customer budget → `config.alerts.customer_budgets` (if `tag_customer` set)
2. Team budget → `config.alerts.budgets.teams` (if `tag_team` set)
3. Global team budget → `config.alerts.budgets.global_usd`
4. Legacy global → `config.alerts.budget_limit_usd`

If no budget is configured anywhere → return `RouteDecision(downgraded=False, reason="no_budget", ...)`

Spend lookups reuse existing functions:
- `get_spend_by_customer_this_month(db_path)` → dict, look up `tag_customer`
- `get_spend_by_team_this_month(db_path)` → dict, look up `tag_team`

**CRITICAL:** `decide_route()` must never raise. Wrap entirely in `try/except Exception`.
On error → `RouteDecision(downgraded=False, reason="error", budget_remaining_usd=0.0, budget_remaining_pct=100.0, routed_model=model)`.

Downgrade condition (either triggers):
- `remaining_pct < config.routing.downgrade_threshold_pct`  → reason = "budget_pct"
- `remaining_usd < config.routing.downgrade_threshold_usd`  → reason = "budget_usd"
(check pct first; if both, use "budget_pct")

If downgrade triggered but `get_downgrade_model(model)` returns None → `reason="no_alternative"`, `downgraded=False` (pass-through, don't block).

### D-04 — handle_request() integration
**Locked:** Add routing call AFTER tag extraction and BEFORE customer budget enforcement.

```python
# --- Budget-aware model downgrade routing ---
routing_config = getattr(config, "routing", None) if config else None
decision = await decide_route(model, tags.get("team"), tags.get("customer"), config, db_path)
if decision.downgraded:
    # Rewrite model in body
    try:
        body_dict = json.loads(body_bytes)
        body_dict["model"] = decision.routed_model
        body_bytes = json.dumps(body_dict).encode()
    except Exception:
        pass   # fail open — use original body
    model = decision.routed_model
    if config and getattr(config.routing, "log_downgrades", True):
        logger.info(
            "[BurnLens] Downgraded %s → %s | Budget remaining: $%.4f (%.1f%%)",
            decision.original_model, decision.routed_model,
            decision.budget_remaining_usd, decision.budget_remaining_pct,
        )
```

`handle_request()` currently receives `customer_budgets` and `api_key_budgets` params.
Add `config: "BurnLensConfig | None" = None` parameter. The proxy server (`server.py`) already
has the full config — pass it through.

### D-05 — RequestRecord schema extension
**Locked:** Add two optional fields to `RequestRecord` in `models.py`:
```python
routed_model: str | None = None
downgrade_reason: str | None = None
```

Both default to `None` (backward-compatible — all existing call sites unaffected).

Set `record.routed_model = decision.routed_model` (always — same as model if not downgraded).
Set `record.downgrade_reason = decision.reason if decision.downgraded else None`.

### D-06 — DB migration
**Locked:** Add `migrate_add_routing_columns(db_path)` in `database.py`:
```sql
ALTER TABLE requests ADD COLUMN routed_model TEXT;
ALTER TABLE requests ADD COLUMN downgrade_reason TEXT;
```
Use `IF NOT EXISTS` pattern (same as existing migration functions). Call from `init_db()` at startup.
Also update `insert_request()` to persist `routed_model` and `downgrade_reason` from `RequestRecord`.

### D-07 — Dashboard: /api/routing-stats
**Locked:** New endpoint in `burnlens/dashboard/routes.py`:
```
GET /api/routing-stats
→ {
    "downgrades_today": int,
    "saved_usd_today": float,
    "downgrades_this_month": int,
    "saved_usd_this_month": float
  }
```

"Saved" = `cost(original_model) - cost(routed_model)` per downgraded request.
Query: `WHERE downgrade_reason IS NOT NULL AND DATE(timestamp) = DATE('now')` for today.

### D-08 — Dashboard UI
**Locked:**
- Add a "Downgrades Today: N  Saved: $X.XX" stat card to the dashboard header row (same style as existing cards in `index.html`/`app.js`)
- In the Recent Requests table add a "Routed" column:
  - If `downgrade_reason` is non-null: show `original_model → routed_model` with an amber badge `↓ downgraded`
  - Badge tooltip: "Budget <20% remaining — routed to cheaper model"
  - If no downgrade: show `-`

### D-09 — CLI command
**Locked:** Add `burnlens routing [--today] [--json]` in `cli.py`:
```
Timestamp            Original Model    Routed Model      Reason        Budget Left
2025-04-10 14:22     gpt-4o            gpt-4o-mini       budget_pct    18.3% / $9.20
```
`--today` filters to today's rows. `--json` outputs raw JSON array.
Query: SELECT all rows WHERE downgrade_reason IS NOT NULL, order by timestamp DESC, limit 200.

### D-10 — Spend cache reuse
**Locked:** Routing uses the _existing_ `_customer_spend_cache` (60-second TTL) in `interceptor.py`
for customer spend lookups. Team spend has no cache yet — add a `_team_spend_cache` dict with
the same TTL pattern in `router.py` (not in `interceptor.py`).

### D-11 — Tests
**Locked:** Create `tests/test_router.py` covering exactly these 12 cases:
- `test_downgrade_triggers_at_threshold_pct`
- `test_downgrade_triggers_at_threshold_usd`
- `test_no_downgrade_when_budget_healthy`
- `test_no_downgrade_when_feature_disabled`
- `test_no_alternative_model_passes_through_without_block`
- `test_customer_budget_takes_priority_over_team`
- `test_team_budget_takes_priority_over_global`
- `test_decide_route_never_raises_on_db_error`
- `test_request_body_rewritten_with_routed_model`
- `test_cost_calculated_on_routed_model_not_original`
- `test_routing_stats_api_returns_correct_counts`
- `test_downgrade_reason_stored_in_db`

Use `pytest-asyncio` (already in use). Mock DB calls with `AsyncMock`. No real DB required.

### Claude's Discretion
- Exact placement of routing stats card in index.html (maintain existing card grid rhythm)
- Whether to show "Saved: $0.00" or hide the saved amount when zero
- Error message text in the 429 customer-budget rejection (existing behavior unchanged)
- Whether `decide_route()` uses `asyncio.get_event_loop().run_until_complete` or stays fully async (stay fully async)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Core files being modified
- `burnlens/proxy/interceptor.py` — `handle_request()`, `check_customer_budget()`, `_customer_spend_cache`
- `burnlens/config.py` — `BurnLensConfig`, `AlertsConfig`, `load_config()` parsing pattern
- `burnlens/storage/models.py` — `RequestRecord` dataclass
- `burnlens/storage/database.py` — `insert_request()`, `get_spend_by_customer_this_month()`, `get_spend_by_team_this_month()`, `init_db()`, migration pattern
- `burnlens/dashboard/routes.py` — existing dashboard API endpoints
- `burnlens/dashboard/static/index.html` — stat cards, request table
- `burnlens/dashboard/static/app.js` — Chart.js rendering, fetch calls
- `burnlens/cli.py` — Typer commands (existing pattern for new commands)

### New files to create
- `burnlens/providers/downgrade.py` — DOWNGRADE_MAP + get_downgrade_model()
- `burnlens/proxy/router.py` — RouteDecision + decide_route()
- `tests/test_router.py` — 12 test cases

### Provider architecture note
- `burnlens/proxy/providers.py` is a backward-compat SHIM — do NOT add DOWNGRADE_MAP there
- Real provider logic lives in `burnlens/providers/` package
- `burnlens/providers/registry.py` and `burnlens/providers/base.py` for reference

### Existing spend functions (reuse, don't duplicate)
- `burnlens/storage/database.py:411` — `get_spend_by_team_this_month(db_path) -> dict[str, float]`
- `burnlens/storage/database.py:440` — `get_spend_by_customer_this_month(db_path) -> dict[str, float]`

### Existing cache pattern to replicate (for team spend cache in router.py)
- `burnlens/proxy/interceptor.py:32-45` — `_customer_spend_cache` + TTL pattern

</canonical_refs>

<specifics>
## Specific Implementation Notes

### Body rewrite for Google requests
Google's model is in the URL path, not the body. When `provider_name == "google"` and model was
extracted from path, rewriting `body["model"]` has no effect on routing. For Google requests,
the URL must also be rewritten. This is a known complexity — the spec does not require Google
body rewrite in v1 (it's in the DOWNGRADE_MAP for future use but the URL-path case can be
deferred). Document this limitation in a comment.

### handle_request() signature change
Current signature ends with:
```python
api_key_budgets: "ApiKeyBudgetsConfig | None" = None,
```
Add after it:
```python
config: "BurnLensConfig | None" = None,
```
The proxy `server.py` passes config — check that call site and update it.

### insert_request() SQL update
The INSERT statement in `database.py` needs `routed_model` and `downgrade_reason` columns.
Check exact column order and INSERT statement — don't break existing inserts with None values.

### Test isolation
`test_router.py` tests must NOT hit the real SQLite DB. Use `AsyncMock` for all DB calls:
```python
from unittest.mock import AsyncMock, patch
```

</specifics>

<deferred>
## Deferred Items

- Google URL-path model rewrite (model is in path, not body — requires URL surgery; deferred to v2)
- Downgrade chains deeper than one hop (e.g., opus → sonnet → haiku)
- Per-request downgrade override header (`X-BurnLens-Allow-Downgrade: false`)
- Dashboard: historical downgrade trend chart
- Cloud sync of downgrade events to burnlens_cloud/

</deferred>

---

*Phase: 14-budget-aware-model-downgrade*
*Context gathered: 2026-05-05 via spec + codebase inspection*
