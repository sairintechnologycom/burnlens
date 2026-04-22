---
phase: 09-quota-tracking-soft-enforcement
reviewed: 2026-04-22T00:00:00Z
depth: standard
files_reviewed: 14
files_reviewed_list:
  - burnlens_cloud/api_keys_api.py
  - burnlens_cloud/auth.py
  - burnlens_cloud/billing.py
  - burnlens_cloud/compliance/retention_prune.py
  - burnlens_cloud/dashboard_api.py
  - burnlens_cloud/database.py
  - burnlens_cloud/email.py
  - burnlens_cloud/emails/templates/usage_100_percent.html
  - burnlens_cloud/emails/templates/usage_80_percent.html
  - burnlens_cloud/ingest.py
  - burnlens_cloud/main.py
  - burnlens_cloud/models.py
  - burnlens_cloud/plans.py
  - burnlens_cloud/team_api.py
findings:
  critical: 0
  warning: 2
  info: 5
  total: 7
status: issues_found
---

# Phase 9: Code Review Report (Re-review)

**Reviewed:** 2026-04-22T00:00:00Z
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

Re-review of Phase 9 after the first code-review-fix pass addressed CR-01, CR-02, and WR-01 through WR-04. Those six findings are verified-resolved in the current source:

- **CR-01 verified:** `burnlens_cloud/ingest.py:42-69` now reads cycle bounds from `workspace_usage_cycles` with a calendar-month fallback; the phantom `workspaces.current_period_started_at` column reference is gone.
- **CR-02 verified:** `invalidate_api_key_cache()` is defined in `auth.py:145-159` and called from `api_keys_api.py:152` after `UPDATE ... RETURNING key_hash`.
- **WR-01 verified:** `dashboard_api.py:155-158` enforces `require_feature("customers_view"/"teams_view")` inline inside `get_costs_by_tag` based on `tag_type`.
- **WR-02 verified:** `api_keys_api.py:158-166` NULLs the legacy `workspaces.api_key_hash` column on revoke when it matches the revoked hash.
- **WR-03 verified:** `email.py:23-52` provides `_pending_email_tasks`, `track_email_task`, and `drain_pending_email_tasks`; `ingest.py:152,175` wraps both 80/100 task creations; `main.py:73-76` drains on lifespan shutdown.
- **WR-04 verified:** Root cause was subsumed by CR-01; `ingest.py:121-132` now carries a clarifying comment on the narrowed residual race.

No new Critical findings surfaced in this pass. Two Warnings remain that were not addressed by the fix pass (one latent pre-Phase-9 bug surfaced by Phase 9 files, one Phase 9-introduced bug). The four previously-deferred Info items (IN-01..IN-04) are still present; I'm re-listing them with their original severity for traceability, plus one new Info.

## Warnings

### WR-05: `send_invitation_email` schedules `_send_background` before it is defined — unreachable NameError on every invite send

**File:** `burnlens_cloud/email.py:134-138`
**Issue:** The control flow is:

```python
# Run in background task (non-blocking)
asyncio.create_task(_send_background())    # line 134 — reference BEFORE definition

async def _send_background():              # line 136 — define AFTER scheduling
    """Send email in background."""
    await asyncio.to_thread(_send)
```

`asyncio.create_task(_send_background())` executes before `_send_background` is bound in the enclosing function scope, so every invite-send raises `NameError: name '_send_background' is not defined`. The outer `try/except Exception` on line 142 swallows it and returns `False`, so invite emails silently never leave the server — only the caller sees the `True` return from the earlier `return True` branch... except there is no earlier return; execution reaches the `create_task` call and crashes into the except block. Either way, invitation email is never sent.

This is a latent pre-Phase-9 bug — `send_invitation_email` was not modified by the Phase 9 diff — but Phase 9 touches this file (adds `send_usage_warning_email`, `track_email_task`, `drain_pending_email_tasks`) and the docstring on the new helper at `email.py:276-277` explicitly acknowledges the trap: *"Define background wrapper BEFORE scheduling — avoids the NameError trap present in send_invitation_email's analog."* The team_api invite path (`team_api.py:423-428`) calls this function every time an admin sends an invite, so Phase 9's team_api changes now route through a broken code path whose failure mode is silent. Worth fixing while the file is open.

**Fix:** Move the `async def _send_background` definition above the `asyncio.create_task(...)` call site and register with `track_email_task` for consistency with `send_usage_warning_email`:

```python
async def _send_background():
    """Send email in background."""
    await asyncio.to_thread(_send)

# Now schedule:
track_email_task(asyncio.create_task(_send_background()))
return True
```

### WR-06: `team_api` SELECTs reference dropped plaintext `users.email` / `users.name` columns — `list_members`, `invite_member` 409 check, and `get_activity` all crash

**File:** `burnlens_cloud/team_api.py:151-162, 353-361, 469-484`
**Issue:** Phase 1c (`database.py:485-491`) drops `users.email`, `users.google_id`, `users.github_id`. The user-facing table now stores only `email_encrypted` / `email_hash` / `name`. Three team_api queries still project `u.email`:

1. `list_members` (lines 151-162): `SELECT ... u.email, u.name, u.last_login FROM workspace_members wm JOIN users u ON ...` — every `GET /team/members` call raises `asyncpg.UndefinedColumnError`.
2. `invite_member` duplicate-member check (lines 353-361): `... WHERE ... u.email = $2` — every `POST /team/invite` raises.
3. `get_activity` (lines 469-484): `SELECT ... u.email, u.name FROM workspace_activity wa LEFT JOIN users u ...` — every `GET /team/activity` raises.

All three are gated behind `require_feature("teams_view")`, so this only impacts Teams-plan workspaces — but that is exactly the Phase 9 target audience. Paid-Teams customers will see 500s on every team page load. Phase 9 did not introduce the queries but it DID add the `require_feature` dependency on these three routes, which means Phase 9 shipped an endpoint set that previously would have 402'd before running the broken query; now it runs (for paid Teams customers) and crashes.

Note: `users.name` still exists (it was never dropped), so the `u.name` references are fine. Only `u.email` is the problem.

**Fix:** Replace `u.email` with `u.email_encrypted` in the SELECT, and decrypt in the Python loop before populating `WorkspaceMemberResponse.email` / `UserResponse.email`. For the `invite_member` 409 check, switch from plaintext equality to `u.email_hash = $2` with `lookup_hash(request.email)`:

```python
from .pii_crypto import decrypt_pii, lookup_hash

# list_members:
# SELECT ..., u.email_encrypted, u.name, u.last_login ...
email_plain = decrypt_pii(row["email_encrypted"]) if row["email_encrypted"] else ""

# invite_member duplicate check:
existing = await execute_query(
    """
    SELECT user_id FROM workspace_members wm
    JOIN users u ON wm.user_id = u.id
    WHERE wm.workspace_id = $1 AND u.email_hash = $2 AND wm.active = true
    """,
    str(token.workspace_id),
    lookup_hash(request.email),
)
```

Add an integration test that covers each of the three endpoints under a Teams-plan workspace — the absence of such a test is how this survived the Phase 1c cutover.

## Info

### IN-01: `check_seat_limit(workspace_id, plan)` second argument is dead (carry-over from first review)

**File:** `burnlens_cloud/team_api.py:93-109`
**Issue:** The `plan` parameter is no longer used inside the function body — `get_seat_limit(workspace_id)` is the authoritative lookup. The docstring acknowledges "retained for backwards compatibility" but the only caller is `team_api.py:369` inside the same module. Dead parameter is a future-trap (someone passes the wrong plan and assumes it matters).

**Fix:** Drop the parameter and simplify the single call site:

```python
async def check_seat_limit(workspace_id: UUID) -> bool: ...
# call site:
if await check_seat_limit(token.workspace_id): ...
```

### IN-02: `_PLAN_PRICE_ORDER` duplicated across three files (carry-over from first review)

**File:** `burnlens_cloud/auth.py:275`, `burnlens_cloud/api_keys_api.py:29`, `burnlens_cloud/team_api.py:112`
**Issue:** Three independent definitions of `("free", "cloud", "teams")` with identical semantics. When an Enterprise plan launches or order changes, three places need edits and one will be missed.

**Fix:** Move to `plans.py` (or a new `burnlens_cloud/constants.py`) as a single `PLAN_PRICE_ORDER` constant and import from all three modules.

### IN-03: `get_seat_limit` returns `10**9` sentinel instead of explicit unlimited (carry-over from first review)

**File:** `burnlens_cloud/team_api.py:82-90`
**Issue:** The `10**9` magic number encodes "effectively unlimited" for `>=` comparisons. It works today but is the kind of value that leaks into JSON responses or log lines where an operator sees "1000000000" and wonders what it means. The name `get_seat_limit` does not signal the sentinel semantics.

**Fix:** Either return `None` / `math.inf` and make `check_seat_limit` handle the sentinel explicitly, or name the constant:

```python
UNLIMITED_SEAT_SENTINEL = 10**9  # "effectively unlimited" for >= comparisons
return limits.seat_count if limits.seat_count is not None else UNLIMITED_SEAT_SENTINEL
```

### IN-04: 100% email template omits `{current}` (carry-over from first review)

**File:** `burnlens_cloud/emails/templates/usage_100_percent.html:5`
**Issue:** The 80% template reads "You've used 80% of your {plan_label} requests this cycle ({current} / {limit})." The 100% template drops the actual current count: "You've hit your {plan_label} monthly cap ({limit} requests)." If a workspace blows 3x past the cap in a single batch, the user sees only the cap, not how far over they went. Harmless; `.format(current=...)` is already passing the value.

**Fix:** Include `{current}` in the 100% template body for parity:

```html
<p>You've hit your {plan_label} monthly cap ({current} / {limit} requests). We're still accepting your traffic through {cycle_end_date} — upgrade any time to raise the ceiling.</p>
```

### IN-05: `ingest.py` accesses `asyncpg.Record` via `.get()` on the OTEL config path

**File:** `burnlens_cloud/ingest.py:287-291`
**Issue:** `workspace_details[0]` returns an `asyncpg.Record`, which does NOT implement `.get()` — only `__getitem__`. The OTEL forward block calls:

```python
if otel_config and otel_config.get("otel_enabled"):
    ...
    endpoint = otel_config.get("otel_endpoint")
    encrypted_key = otel_config.get("otel_api_key_encrypted")
```

Every call to `/v1/ingest` that reaches this branch (i.e. any workspace with `otel_enabled = true`) raises `AttributeError: 'Record' object has no attribute 'get'`. The enclosing `try/except Exception` on line 307 swallows it and logs `"Failed to queue OTEL forward"`, so ingest still 200s and the rest of the pipeline (including the Phase 9 quota tracking) keeps working — the only observable effect is that OTEL forwarding silently stops for enterprise workspaces.

This bug pre-dates Phase 9 and is not introduced by this phase's diff, but `ingest.py` was heavily modified in Phase 9 (the usage-cycles block) so it's worth flagging. The billing.py review at a prior phase explicitly commented this pattern ("B2: asyncpg Record has no .get(); use subscript") — the convention just wasn't applied here.

**Fix:** Switch to subscript access and explicit None checks:

```python
otel_enabled = otel_config["otel_enabled"] if otel_config else False
if otel_enabled:
    endpoint = otel_config["otel_endpoint"]
    encrypted_key = otel_config["otel_api_key_encrypted"]
    ...
```

Or convert the Record to a dict up front: `otel_config = dict(workspace_details[0]) if workspace_details else None`.

---

_Reviewed: 2026-04-22T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
