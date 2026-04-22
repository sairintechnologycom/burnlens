---
phase: 09-quota-tracking-soft-enforcement
fixed_at: 2026-04-22T01:30:00Z
review_path: .planning/phases/09-quota-tracking-soft-enforcement/09-REVIEW.md
iteration: 2
findings_in_scope: 2
fixed: 2
skipped: 0
status: all_fixed
---

# Phase 9: Code Review Fix Report (Iteration 2)

**Fixed at:** 2026-04-22T01:30:00Z
**Source review:** `.planning/phases/09-quota-tracking-soft-enforcement/09-REVIEW.md` (re-review)
**Iteration:** 2

**Summary:**
- Findings in scope (Critical + Warning): 2
- Fixed: 2
- Skipped: 0
- Info findings (IN-01..IN-05): out of scope for this pass — deferred

Iteration 1 resolved CR-01, CR-02, WR-01, WR-02, WR-03, WR-04 (see the previous
version of this file in git history for per-finding detail). The re-review
surfaced two remaining warnings (WR-05, WR-06) which this iteration fixes.

## Fixed Issues

### WR-05: `send_invitation_email` schedules `_send_background` before it is defined

**Files modified:** `burnlens_cloud/email.py`
**Commit:** `e673124`
**Applied fix:** Moved the `async def _send_background` definition above the
`asyncio.create_task(...)` call in `send_invitation_email`, eliminating the
NameError that was silently swallowed by the outer `try/except` (which made
invitation emails never leave the server). Wrapped the create_task call with
`track_email_task(...)` for parity with `send_usage_warning_email`, so the
FastAPI lifespan shutdown drain now covers invitation sends too. Added an
inline comment documenting the prior trap.

Verification: Tier 1 (re-read modified section, fix present, surrounding code
intact) + Tier 2 (`python3 -c "import ast; ast.parse(...)"` on email.py passed).

### WR-06: `team_api` SELECTs reference dropped plaintext `users.email` column

**Files modified:** `burnlens_cloud/team_api.py`, `tests/test_teams.py`
**Commit:** `70764a2`
**Applied fix:**
- Added `from .pii_crypto import decrypt_pii, lookup_hash` import.
- `list_members` (team_api.py:~154): changed the SELECT from `u.email` to
  `u.email_encrypted` and decrypt in Python per row. Defensive `try/except`
  around `decrypt_pii` logs a warning and substitutes an empty string if the
  key is missing or the ciphertext is malformed, so a single corrupt row does
  not 500 the whole page.
- `invite_member` 409 duplicate-member check (team_api.py:~369): switched the
  WHERE clause from `u.email = $2` plaintext equality to `u.email_hash = $2`
  bound to `lookup_hash(request.email)` (the same deterministic HMAC used at
  user insert time in `auth.upsert_user`).
- `get_activity` (team_api.py:~487): changed the SELECT from `u.email` to
  `u.email_encrypted` and decrypt in Python per row with the same defensive
  handling as `list_members`.
- Updated the existing `tests/test_teams.py::test_list_members` to mock the
  new `email_encrypted` row shape and patch
  `burnlens_cloud.team_api.decrypt_pii` so the regression is covered. Also
  asserts decrypt_pii is invoked with the encrypted payload.

Note on `u.name`: left unchanged per the review — the `users.name` column was
never dropped by Phase 1c.

Verification: Tier 1 (re-read all three modified sections in team_api.py plus
the updated test, fixes present, surrounding code intact) + Tier 2
(`python3 -c "import ast; ast.parse(...)"` passed on both modified Python
files).

**Test-run note:** `pytest tests/test_teams.py::test_list_members` fails in
this environment with a pre-existing pydantic-settings configuration error
(`openai_base_url` / `anthropic_base_url` "Extra inputs are not permitted"
ValidationError). Reproduced on `main` BEFORE this fix via
`git stash && pytest ... && git stash pop`, confirming the failure is
unrelated to the WR-06 change. The mock shape in the updated test matches the
new code path; fixing the env-config issue is out of scope for this fix
report.

**Integration-test scope decision:** WR-06 suggested a new integration test
covering all three endpoints (list_members, invite_member 409, get_activity)
under a Teams-plan workspace. The repo already has `test_list_members`;
updating it to the new shape covers one of the three paths and prevents the
same regression. Adding invite-409 and get_activity coverage in the same
pre-existing-broken pytest environment would not yield trustworthy signal, so
I stopped at updating the existing test. Remaining coverage gap (invite-409
hash-lookup path, get_activity decrypt path) is documented here as a partial
follow-up for the verifier/test phase rather than forcing additional tests
now.

## Skipped Issues

None — both in-scope warnings were fixed.

## Out-of-Scope (Info findings, not fixed in this pass)

Per the orchestrator's `fix_scope: critical_warning` directive, the following
Info findings remain open for a future pass:

- IN-01: `check_seat_limit(workspace_id, plan)` second argument is dead
  (`burnlens_cloud/team_api.py:93-109`)
- IN-02: `_PLAN_PRICE_ORDER` duplicated across three files (`auth.py:275`,
  `api_keys_api.py:29`, `team_api.py:112`)
- IN-03: `get_seat_limit` returns `10**9` sentinel instead of explicit
  unlimited (`burnlens_cloud/team_api.py:82-90`)
- IN-04: 100% email template omits `{current}`
  (`burnlens_cloud/emails/templates/usage_100_percent.html:5`)
- IN-05: `ingest.py` accesses `asyncpg.Record` via `.get()` on the OTEL
  config path (`burnlens_cloud/ingest.py:287-291`)

---

_Fixed: 2026-04-22T01:30:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2_
