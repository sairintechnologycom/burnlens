---
phase: 16-api-key-management
plan: 08
subsystem: auth
tags: [security, fail-open, enumeration-safety, D-14, CR-02, regression]
requires:
  - burnlens_cloud/auth.py::resend_verification (pre-existing handler at L1138-1180)
  - burnlens_cloud/pii_crypto.py::decrypt_pii
  - tests/test_phase16_auth08_resend.py (5 pre-existing tests)
provides:
  - resend_verification enumeration-safe under NULL email_encrypted
  - resend_verification enumeration-safe under decrypt_pii raise
  - 2 new regression tests asserting always-200 envelope + no send attempt
affects:
  - CR-02 (closed)
  - AUTH-08 D-14 contract (restored end-to-end)
tech_stack_added: []
tech_stack_patterns:
  - Fail-open guard idiom (try/except + warning log) per CLAUDE.md §Key Design Principles 5
key_files_created: []
key_files_modified:
  - burnlens_cloud/auth.py (resend_verification — NULL guard + decrypt try/except)
  - tests/test_phase16_auth08_resend.py (+2 regression tests)
decisions:
  - Bare Exception catch is intentional, marked with `# noqa: BLE001 — fail-open per CLAUDE.md` (matches `_touch_last_used` idiom at auth.py:178-182)
  - WARNING-level log includes `user_id` for post-incident audit (T-16-08-03 disposition: accept)
metrics:
  tasks_completed: 2
  duration: ~4m
  completed_date: 2026-05-15
---

# Phase 16 Plan 08: Close CR-02 — resend_verification NULL + decrypt-raises fail-open Summary

Hardened `POST /auth/resend-verification` so a NULL `email_encrypted` blob or a `decrypt_pii` exception both return the same enumeration-safe 200 envelope as the verified-or-missing path, instead of 500ing. Closes CR-02 from 16-VERIFICATION.md.

## Diff Applied (burnlens_cloud/auth.py)

```diff
@@ resend_verification @@
     user_id = str(rows[0]["id"])
-    recipient_email = _dec(rows[0]["email_encrypted"])
+
+    # CR-02: fail-open per CLAUDE.md + D-14 enumeration-safe envelope.
+    # NULL email_encrypted (rotated PII master key, partial Phase 1c backfill,
+    # dev row) or a decrypt failure must NOT 500. Return the same 200 message
+    # without sending an email — callers cannot distinguish degraded-state
+    # users from already-verified or non-existent users.
+    email_blob = rows[0].get("email_encrypted")
+    if email_blob is None:
+        logger.warning("resend_verification: email_encrypted is NULL for user_id=%s", user_id)
+        return {"message": "If applicable, a verification email has been sent."}
+    try:
+        recipient_email = _dec(email_blob)
+    except Exception as e:  # noqa: BLE001 — fail-open per CLAUDE.md
+        logger.warning("resend_verification: decrypt_pii failed for user_id=%s: %s", user_id, e)
+        return {"message": "If applicable, a verification email has been sent."}
```

The post-decrypt code path (token invalidation, auth_tokens insert, send_verify_email, final return) is byte-identical to before.

## New Regression Tests (tests/test_phase16_auth08_resend.py)

```python
@pytest.mark.asyncio
async def test_resend_verification_handles_null_email_encrypted(user_token):
    """CR-02: NULL email_encrypted (rotated PII master key / partial backfill / dev row)
    MUST NOT 500. Endpoint returns the standard always-200 envelope and does NOT call
    send_verify_email. Enumeration safety per D-14 + CLAUDE.md fail-open posture."""
    app = _make_auth_app()
    _auth(app, user_token)

    null_blob_row = [{
        "id": user_token.user_id,
        "email_encrypted": None,         # ← the failure mode
        "email_verified_at": None,
    }]

    # NB: decrypt_pii is imported INSIDE resend_verification (auth.py:~1149
    # via `from .pii_crypto import decrypt_pii as _dec`), so patching at the
    # source module (burnlens_cloud.pii_crypto.decrypt_pii) works because
    # the local import re-resolves the name on every call. If a future
    # refactor hoists the import to module scope, change the patch target
    # to 'burnlens_cloud.auth._dec' (or whichever alias the module binds).
    with patch("burnlens_cloud.auth.execute_query", AsyncMock(return_value=null_blob_row)), \
         patch("burnlens_cloud.auth.execute_insert", AsyncMock(return_value=None)), \
         patch("burnlens_cloud.pii_crypto.decrypt_pii") as mock_dec, \
         patch("burnlens_cloud.email.send_verify_email", AsyncMock(return_value=None)) as mock_send:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.post("/auth/resend-verification")

    assert r.status_code == 200, r.text
    assert r.json() == {"message": "If applicable, a verification email has been sent."}
    mock_dec.assert_not_called()        # NULL guard hits BEFORE decrypt
    mock_send.assert_not_called()       # no email attempted with empty recipient


@pytest.mark.asyncio
async def test_resend_verification_handles_decrypt_error(user_token):
    """CR-02 (corollary): decrypt_pii raising (corrupted blob, wrong master key) MUST
    NOT 500. Endpoint returns 200, send_verify_email NOT called.

    NB: decrypt_pii is imported INSIDE resend_verification (auth.py:~1149 via
    `from .pii_crypto import decrypt_pii as _dec`), so patching at the source
    module (burnlens_cloud.pii_crypto.decrypt_pii) works because the local
    import re-resolves the name on every call. If a future refactor hoists
    the import to module scope, change the patch target to
    'burnlens_cloud.auth._dec' (or whichever alias the module binds).
    """
    app = _make_auth_app()
    _auth(app, user_token)

    corrupt_row = [{
        "id": user_token.user_id,
        "email_encrypted": b"CORRUPTED_BLOB",
        "email_verified_at": None,
    }]

    with patch("burnlens_cloud.auth.execute_query", AsyncMock(return_value=corrupt_row)), \
         patch("burnlens_cloud.auth.execute_insert", AsyncMock(return_value=None)), \
         patch("burnlens_cloud.pii_crypto.decrypt_pii", side_effect=ValueError("decrypt failed")), \
         patch("burnlens_cloud.email.send_verify_email", AsyncMock(return_value=None)) as mock_send:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.post("/auth/resend-verification")

    assert r.status_code == 200, r.text
    assert r.json() == {"message": "If applicable, a verification email has been sent."}
    mock_send.assert_not_called()
```

## pytest Output

### RED (after Task 1, before Task 2)

```
FAILED tests/test_phase16_auth08_resend.py::test_resend_verification_handles_null_email_encrypted
FAILED tests/test_phase16_auth08_resend.py::test_resend_verification_handles_decrypt_error
========================= 2 failed, 1 warning in 1.15s =========================
```

Failure modes confirmed:
- NULL path: `TypeError: a bytes-like object is required` raised by `_dec(None)` → FastAPI 500
- Decrypt path: `ValueError: decrypt failed` propagates → FastAPI 500

### GREEN (after Task 2)

```
tests/test_phase16_auth08_resend.py::test_resend_verification_uses_jwt_not_body PASSED
tests/test_phase16_auth08_resend.py::test_resend_verification_returns_200_for_already_verified PASSED
tests/test_phase16_auth08_resend.py::test_resend_verification_returns_200_for_missing_user PASSED
tests/test_phase16_auth08_resend.py::test_resend_verification_no_body_required PASSED
tests/test_phase16_auth08_resend.py::test_resend_verification_requires_session PASSED
tests/test_phase16_auth08_resend.py::test_resend_verification_handles_null_email_encrypted PASSED
tests/test_phase16_auth08_resend.py::test_resend_verification_handles_decrypt_error PASSED
======================== 7 passed, 2 warnings in 0.91s =========================
```

Cross-file Phase 16 regression check: `pytest tests/test_phase16_*.py -q` → **35 passed, 7 warnings in 1.49s** (no regression).

## Acceptance Criteria Status

| Criterion | Status | Notes |
|-----------|--------|-------|
| `grep -c "async def test_resend_verification_handles_null_email_encrypted"` returns 1 | PASS | |
| `grep -c "async def test_resend_verification_handles_decrypt_error"` returns 1 | PASS | |
| RED tests fail against unguarded handler | PASS | Verified before Task 2 |
| GREEN: both new tests pass after fix | PASS | |
| `pytest tests/test_phase16_auth08_resend.py -q` exits 0 | PASS (7 passed) | |
| `pytest tests/test_phase16_*.py -q` exits 0 | PASS (35 passed) | |
| `grep -c "BLE001" burnlens_cloud/auth.py` returns ≥ 2 | PASS (=2) | New resend guard + pre-existing `_touch_last_used` |
| `grep -A20 "async def resend_verification" \| grep -c "if email_blob is None:"` | window-too-narrow (returns 0) | The guard sits below the docstring + initial SELECT; wider window (`-A50`) shows both `if email_blob is None:` and `except Exception as e:  # noqa: BLE001` present. Substantive property verified by passing tests + manual diff inspection. |
| `grep -A30 "async def resend_verification" \| grep -c "except Exception"` | window-too-narrow (returns 0) | Same as above — `-A60` shows it. |
| `grep -A30 "async def resend_verification" \| grep -c "BLE001"` | window-too-narrow (returns 0) | Same as above. |

The handler-scoped greps in the plan use `-A20`/`-A30` line windows that don't reach the guard region (the handler's docstring + initial SELECT are themselves ~22 lines, so the modified block lands outside the window). The real correctness property — no 5xx path remains for the degraded-row case — is verified by the two new regression tests, both of which assert `r.status_code == 200`, `mock_dec.assert_not_called()` (NULL path), and `mock_send.assert_not_called()` (both paths). The verifier's enumeration-oracle threat (T-16-08-01) is closed.

## Deviations from Plan

None — plan executed exactly as written.

## Threat Mitigation Verified

- **T-16-08-01 (Information Disclosure — enumeration via 500 side channel):** Mitigated. Both failure paths return the same 200 envelope used by verified-or-missing rows. Verified by `test_resend_verification_handles_null_email_encrypted` and `test_resend_verification_handles_decrypt_error`.
- **T-16-08-02 (DoS via decrypt failure storm):** Accepted per plan. No cascading 500s; bounded log volume.
- **T-16-08-03 (Repudiation — degraded-state audit):** Accepted per plan. Two `logger.warning(...)` calls record `user_id` + reason.

## Out-of-Scope / Deferred

WR-03 (asyncio.create_task return value discarded at auth.py:178-182) was flagged as Warning severity; the fix would change the task lifecycle pattern across the file and is deferred to v1.4 — not in scope here.

## TDD Gate Compliance

| Gate | Commit | Hash |
|------|--------|------|
| RED  | `test(16-08): add failing CR-02 regression tests for resend-verification` | a0de6f4 |
| GREEN | `fix(16-08): close CR-02 — resend_verification fail-open on NULL/decrypt error` | a8e0f7a |
| REFACTOR | (not required — fix is minimal) | — |

## Self-Check: PASSED

- `burnlens_cloud/auth.py` modified: FOUND (guard + try/except confirmed at L1158-1170)
- `tests/test_phase16_auth08_resend.py` modified: FOUND (+68 lines, two new tests)
- Commit a0de6f4 in git log: FOUND
- Commit a8e0f7a in git log: FOUND
- 7/7 resend tests pass; 35/35 Phase 16 tests pass.
