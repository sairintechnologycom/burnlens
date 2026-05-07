---
phase: 11-auth-essentials
plan: "02"
subsystem: cloud-backend
tags: [email, transactional, sendgrid, templates, auth]
dependency_graph:
  requires: []
  provides:
    - burnlens_cloud/email.py::TemplateSpec
    - burnlens_cloud/email.py::TEMPLATE_REGISTRY
    - burnlens_cloud/email.py::send_welcome_email
    - burnlens_cloud/email.py::send_verify_email
    - burnlens_cloud/email.py::send_password_changed_email
    - burnlens_cloud/email.py::send_reset_password_email
    - burnlens_cloud/email.py::send_payment_receipt_email
  affects:
    - burnlens_cloud/email.py (extended)
tech_stack:
  added: []
  patterns:
    - TypedDict template registry for typed email template metadata
    - fail-open background-task send pattern via track_email_task(asyncio.create_task())
    - str.replace() variable substitution in HTML templates (no eval/f-strings)
key_files:
  created:
    - burnlens_cloud/emails/templates/welcome.html
    - burnlens_cloud/emails/templates/verify_email.html
    - burnlens_cloud/emails/templates/password_changed.html
    - burnlens_cloud/emails/templates/reset_password.html
    - burnlens_cloud/emails/templates/payment_receipt.html
  modified:
    - burnlens_cloud/email.py
decisions:
  - "Added send_reset_password_email in addition to the 4 listed in acceptance_criteria, because TEMPLATE_REGISTRY includes a reset_password entry and Plan 03 requires it for the password-reset flow; omitting it would leave a dangling registry entry"
metrics:
  duration: "3m 28s"
  completed: "2026-05-02T05:33:31Z"
  tasks_completed: 3
  files_modified: 6
---

# Phase 11 Plan 02: Email Template Registry and Transactional Send Functions Summary

**One-liner:** TypedDict TemplateSpec registry + 5 fail-open background-task send functions + 5 HTML templates for Phase 11 transactional emails (welcome, verify, password-changed, reset-password, payment-receipt).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add TemplateSpec TypedDict and TEMPLATE_REGISTRY | c3151df | burnlens_cloud/email.py |
| 2 | Add 5 send_*_email() functions | 95e73cd | burnlens_cloud/email.py |
| 3 | Create 5 HTML email template files | e0ba0c5 | 5 template HTML files |

## What Was Built

### email.py extensions

**TemplateSpec TypedDict** — typed dict with `subject`, `template_file`, `required_vars` fields. Makes the registry self-documenting and type-safe.

**TEMPLATE_REGISTRY** — `dict[str, TemplateSpec]` with 5 entries: welcome, verify_email, password_changed, reset_password, payment_receipt. Adding a new template in the future is a single dict entry.

**5 send functions** — all follow the existing `send_usage_warning_email` pattern exactly:
- Check `settings.sendgrid_api_key`; log warning and return if missing (fail-open)
- Define inner `async def _send_background()` that reads template, substitutes variables, builds Mail object, calls SendGrid
- Wrap in `try/except Exception` — logs on failure, never raises
- Register via `track_email_task(asyncio.create_task(_send_background()))`

### HTML templates

5 template files in `burnlens_cloud/emails/templates/` with inline CSS, max-width 600px container, BurnLens brand styling (`#3b82f6` button color, `-apple-system` font stack). Variable substitution uses `{{placeholder}}` syntax replaced by `str.replace()`.

## Deviations from Plan

### Auto-additions

**1. [Rule 2 - Missing Functionality] Added send_reset_password_email**
- **Found during:** Task 2
- **Issue:** TEMPLATE_REGISTRY includes a `reset_password` entry and Plan 03 explicitly requires a password-reset send function for `POST /auth/reset-password/confirm`. Plan 02 acceptance criteria listed only 4 functions but the action block specified 5 including `send_reset_password_email`. Omitting it would leave a dangling registry entry and break Plan 03 integration.
- **Fix:** Added `send_reset_password_email(recipient_email, reset_url)` following the same fail-open pattern. Also created `reset_password.html` template.
- **Files modified:** burnlens_cloud/email.py, burnlens_cloud/emails/templates/reset_password.html
- **Commit:** 95e73cd (Task 2), e0ba0c5 (Task 3)

## Verification Results

All plan verification checks passed:
1. `grep -c "class TemplateSpec" burnlens_cloud/email.py` → 1
2. `grep -c "TEMPLATE_REGISTRY" burnlens_cloud/email.py` → 6 (definition + 5 usages in send functions)
3. All 4 required send functions present in burnlens_cloud/email.py
4. All 4 required template files exist (plus reset_password.html as bonus)
5. `python3 -c "import ast; ast.parse(...); print('OK')"` → OK

## Known Stubs

None — all send functions are fully wired and functional. Template placeholders (`{{workspace_name}}`, etc.) are intentional substitution markers, not stubs.

## Threat Flags

None — no new network endpoints or trust boundaries introduced. Security mitigations from plan's threat model are all in place (str.replace-only substitution, no eval, recipient_email from DB, subject is a constant string).

## Self-Check: PASSED

- burnlens_cloud/email.py: FOUND (modified)
- burnlens_cloud/emails/templates/welcome.html: FOUND
- burnlens_cloud/emails/templates/verify_email.html: FOUND
- burnlens_cloud/emails/templates/password_changed.html: FOUND
- burnlens_cloud/emails/templates/reset_password.html: FOUND
- burnlens_cloud/emails/templates/payment_receipt.html: FOUND
- Commit c3151df: FOUND (Task 1)
- Commit 95e73cd: FOUND (Task 2)
- Commit e0ba0c5: FOUND (Task 3)
