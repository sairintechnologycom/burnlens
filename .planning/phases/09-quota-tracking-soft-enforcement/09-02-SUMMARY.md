---
phase: 09-quota-tracking-soft-enforcement
plan: 02
subsystem: backend
tags: [pydantic, email, templates, api_keys, docs]
requirements: [QUOTA-02, GATE-04]
dependency_graph:
  requires:
    - "burnlens_cloud/models.py existing BaseModel/Field/Optional/UUID/datetime imports"
    - "burnlens_cloud/email.py send_invitation_email SMTP pattern"
    - "burnlens_cloud/pii_crypto.decrypt_pii"
    - "burnlens_cloud/database.execute_query"
    - "burnlens_cloud/plans.resolve_limits existing signature"
  provides:
    - "burnlens_cloud.models.ApiKey (pydantic)"
    - "burnlens_cloud.models.ApiKeyCreateRequest (pydantic)"
    - "burnlens_cloud.models.ApiKeyCreateResponse (pydantic, plaintext-once)"
    - "burnlens_cloud.email.send_usage_warning_email (async, fire-and-forget)"
    - "burnlens_cloud/emails/templates/usage_80_percent.html"
    - "burnlens_cloud/emails/templates/usage_100_percent.html"
    - "burnlens_cloud.plans.resolve_limits docstring invariant (retention_days=0 == retain-forever)"
  affects:
    - "Plan 04 (api_keys_api router) — can import ApiKey* models"
    - "Plan 05 (ingest threshold email) — can call send_usage_warning_email"
    - "Plan 06+ (retention prune) — honors docstring invariant"
tech_stack:
  added: []
  patterns:
    - "First on-disk HTML email templates (invitation was inline)"
    - "Template path built from whitelist-validated threshold ({'80','100'}) — T-09-08 mitigation"
    - "Define _send_background BEFORE asyncio.create_task — fix of known NameError trap in send_invitation_email analog"
key_files:
  created:
    - "burnlens_cloud/emails/templates/usage_80_percent.html"
    - "burnlens_cloud/emails/templates/usage_100_percent.html"
  modified:
    - "burnlens_cloud/models.py"
    - "burnlens_cloud/email.py"
    - "burnlens_cloud/plans.py"
decisions:
  - "Threshold is a whitelist ({'80','100'}) rather than int — keeps the file-path build trivially safe and matches template naming."
  - "Did NOT replicate send_invitation_email's NameError trap (async def _send_background defined after create_task)."
  - "Owner email lookup uses workspace_members.role='owner' + users.email_encrypted + decrypt_pii — no new helper added; kept inline within the one call site."
metrics:
  duration_minutes: ~12
  tasks_completed: 3
  completed_date: 2026-04-21
---

# Phase 9 Plan 02: Wave-1 Shared Contracts Summary

**One-liner:** Stood up three new Pydantic API-key models, two on-disk HTML quota-warning templates with exact D-09 copy, a new `send_usage_warning_email` fire-and-forget helper, and a `resolve_limits` docstring note codifying the D-23 retention-forever sentinel — so Wave-2 plans (04 api_keys router, 05 ingest threshold email) can import these artifacts without cross-dependency.

## What Shipped

### models.py (3 new Pydantic models — lines 408–434)

- **Line 408** `class ApiKeyCreateRequest(BaseModel)` — single optional `name: str` capped at 64 chars.
- **Line 416** `class ApiKey(BaseModel)` — list-response row: `id: UUID`, `name: str`, `last4: str`, `created_at: datetime`, `revoked_at: Optional[datetime] = None`.
- **Line 428** `class ApiKeyCreateResponse(ApiKey)` — extends `ApiKey` with plaintext `key: str`. Docstring explicitly flags the plaintext-once invariant ("emitted EXACTLY ONCE at key-creation time and is never stored server-side or re-emitted").
- No DB-only fields (`key_hash`, `workspace_id`, `created_by_user_id`) ever surface on the wire.

### Email templates (2 new files)

- **`burnlens_cloud/emails/templates/usage_80_percent.html`** — 1,024 bytes. Heading "Heads up on your BurnLens usage". Body (verbatim D-09): *"You've used 80% of your {plan_label} requests this cycle ({current} / {limit}). Your counter resets on {cycle_end_date}. Upgrade to keep flowing if you need more."*
- **`burnlens_cloud/emails/templates/usage_100_percent.html`** — 1,065 bytes. Heading "You've hit your BurnLens monthly cap". Body (verbatim D-09): *"You've hit your {plan_label} monthly cap ({limit} requests). We're still accepting your traffic through {cycle_end_date} — upgrade any time to raise the ceiling."*
- Both use single-brace `{placeholder}` tokens for Python `str.format()`; exactly one `<a href="{upgrade_url}">` CTA labelled "Upgrade plan" (D-10); outer layout copied verbatim from `send_invitation_email`'s inline block; inline styles only (survives email clients).

### email.py (lines 110–254)

- New `async def send_usage_warning_email(workspace_id, threshold, current, limit, cycle_end_date, plan_label) -> bool` at line **110**.
- Module imports extended: added `pathlib.Path`, `burnlens_cloud.database.execute_query`, `burnlens_cloud.pii_crypto.decrypt_pii`; added `_TEMPLATE_DIR = Path(__file__).parent / "emails" / "templates"` module-level constant.
- Fail-open on every path: no SendGrid key, invalid threshold, missing owner, missing `email_encrypted`, decrypt failure, template read failure, SMTP exception — all log warning and `return False`, never raise (D-08).
- Threshold whitelist `("80", "100")` validated before building the template path (threat T-09-08 mitigated — no traversal possible).
- `_send_background` is defined **before** `asyncio.create_task(_send_background())` — explicitly avoiding the analog's NameError trap flagged in 09-PATTERNS.md.

### plans.py (lines 36–38)

- `resolve_limits` docstring gained a new paragraph (line **36**) documenting the D-23 invariant:
  > `retention_days = 0` in `workspaces.limit_overrides` means **retain forever** (the retention-prune loop skips the workspace entirely). Zero is sentinel-for-unlimited; null means "use plan default." Per D-23.
- No behavior change; body/signature/return type untouched.

## Commits

| Hash | Summary | Files |
| ---- | ------- | ----- |
| `d6f7a4b` | feat(09-02): add ApiKey/ApiKeyCreateRequest/ApiKeyCreateResponse pydantic models | burnlens_cloud/models.py |
| `f699ca2` | feat(09-02): add usage_80_percent.html and usage_100_percent.html email templates | burnlens_cloud/emails/templates/usage_80_percent.html, usage_100_percent.html |
| `5afbc19` | feat(09-02): add send_usage_warning_email + document retention_days=0 semantics | burnlens_cloud/email.py, burnlens_cloud/plans.py |

## Verification

All plan-level checks pass:

- `from burnlens_cloud.models import ApiKey, ApiKeyCreateRequest, ApiKeyCreateResponse` — OK
- `ApiKeyCreateResponse.__mro__[1] is ApiKey` — OK
- `inspect.iscoroutinefunction(send_usage_warning_email)` — OK
- `send_usage_warning_email` signature == `(workspace_id, threshold, current, limit, cycle_end_date, plan_label)` — OK
- `_send_background` defined before `asyncio.create_task(_send_background())` — OK (src-offset check)
- Both templates contain exact D-09 body snippets, one CTA anchor each, no Jinja double-braces — OK
- `resolve_limits.__doc__` contains "retain forever" — OK
- `pytest --co` collects 207 tests cleanly — no import regressions

## Deviations from Plan

None — plan executed exactly as written. Threat model mitigations for T-09-07 (plaintext-once docstring) and T-09-08 (threshold whitelist guard) are both in place as designed.

## Security Notes

- **T-09-07 Information Disclosure (ApiKeyCreateResponse.key plaintext):** Docstring flags the plaintext-once invariant so Plan 04's handler author sees it when adding the router. No `repr=True` override added — matches plan's mitigation strategy.
- **T-09-08 Template path-traversal via `threshold`:** `threshold` is validated against the literal set `{"80", "100"}` before the path is built. Any other value short-circuits to `return False` with a warning log. No traversal reachable.
- **T-09-09 Email in tracebacks:** `exc_info` is not requested on any warning path in `send_usage_warning_email`; only `workspace_id` appears in log lines. Explicit error lines use `%s` formatting with the raw exception message (which may contain email only if the underlying library includes it — matches invitation-email precedent).

## Self-Check

File existence:
- FOUND: burnlens_cloud/models.py
- FOUND: burnlens_cloud/email.py
- FOUND: burnlens_cloud/plans.py
- FOUND: burnlens_cloud/emails/templates/usage_80_percent.html
- FOUND: burnlens_cloud/emails/templates/usage_100_percent.html

Commits in log:
- FOUND: d6f7a4b
- FOUND: f699ca2
- FOUND: 5afbc19

## Self-Check: PASSED
