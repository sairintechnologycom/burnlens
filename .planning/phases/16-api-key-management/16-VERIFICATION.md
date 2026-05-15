---
phase: 16-api-key-management
verified: 2026-05-15T00:00:00Z
status: passed
score: 6/6 must-haves verified (1 via override — SC-5 resolved by 16-10 path-b)
overrides_applied: 2
re_verification:
  previous_status: gaps_found
  previous_score: 3/6
  gaps_closed:
    - "CR-01 — PATCH /api-keys/{id} now refuses to rename revoked keys (SC-4 / D-04 indistinguishability restored)"
    - "CR-02 — resend_verification fail-open on NULL email_encrypted and decrypt exceptions (D-14 enumeration-safety restored)"
    - "CR-03 — BillingStatusBanner.handleResend now guards on r.ok before flipping to 'sent' (AUTH-08 truthful UI restored end-to-end)"
  gaps_remaining:
    - "SC-5 / D-04 policy ambiguity — DEFERRED to 16-10 (checkpoint:decision plan), intentionally not executed in this wave"
  regressions: []
overrides:
  - must_have: "A viewer-role user visiting /api-keys sees only their own key and cannot access the create or revoke actions (SC-5 / APIKEY-05)"
    reason: "Server-side filter is verified-correct; the UI surface deviation is a documented spec/decision ambiguity (ROADMAP SC-5 verbatim vs D-04 viewer self-create/self-revoke). 16-10-PLAN.md exists with a checkpoint:decision gate and is intentionally deferred from this gap-closure wave. Per verification context, do not penalize the score for this and flag as deferred."
    accepted_by: "verification context (16-VERIFICATION re-verification instruction)"
    accepted_at: "2026-05-15T00:00:00Z"
  - rule: "SC-5 verbatim wording 'cannot access the create or revoke actions'"
    accepted_by: "human (16-10 plan, path-b)"
    rationale: "Server-side enforcement of viewer-creator scoping is security-equivalent to a UI gate. D-04 (locked decision) explicitly permits viewers to self-create and self-revoke their own keys. ROADMAP wording predates D-04 and is the artefact that moves. No production code change."
    date: "2026-05-15"
gaps:
  - truth: "A viewer-role user visiting /api-keys sees only their own key and cannot access the create or revoke actions (SC-5 / APIKEY-05)"
    status: resolved_via_override
    resolution: "16-10 path-b — ROADMAP SC-5 reworded to match D-04 (no production code change). Override recorded above."
    reason: "Policy ambiguity between ROADMAP SC-5 verbatim wording and D-04 viewer self-create/self-revoke decision. Server-side scoping (_viewer_creator_filter) is correct; UI gating is the contested question. Resolved by 16-10 path-b: ROADMAP wording moves to match D-04."
    pointer: ".planning/phases/16-api-key-management/16-10-PLAN.md"
    artifacts:
      - path: ".planning/phases/16-api-key-management/16-10-PLAN.md"
        issue: "Resolved 2026-05-15 via path-b (ROADMAP wording updated; override recorded)"
human_verification:
  - test: "Owner full lifecycle on /api-keys — create / copy / revoke / edit label"
    expected: "All four flows succeed end-to-end; plaintext shown exactly once; revoked row dims; toasts match UI-SPEC copy"
    why_human: "Visual flow + clipboard + relative-time rendering"
  - test: "Sidebar nav — API Keys entry between Connections and Settings with key glyph; highlights on /api-keys"
    expected: "Three System-group items in order with correct glyph"
    why_human: "Visual ordering + glyph rendering"
  - test: "AUTH-08 happy path — clear localStorage, log in, click resend; expect 200 → 'email sent!'"
    expected: "POST /auth/resend-verification with empty body + cookie; 200; UI flips to 'email sent!'"
    why_human: "Logged-in cookie session + UI state transition"
  - test: "AUTH-08 sad path — expire/invalidate cookie, click resend; expect 401 → 'try again' (NOT 'email sent!')"
    expected: "Backend returns 401; UI shows 'try again'. This was previously failing; should now PASS after CR-03 closure."
    why_human: "Confirms CR-03 closure end-to-end at the browser level"
  - test: "Playwright behavioural pass for phase16_resend_banner.spec.ts on a maintainer machine"
    expected: "Both tests (200 happy + 401 sad) PASS after `npx playwright install chromium`. Sandbox couldn't run them; spec is syntactically validated and harness picked up both."
    why_human: "Required browser binary install was denied in the sandbox during 16-09 execution"
---

# Phase 16: API Key Management — Verification Report (Re-verification)

**Phase Goal:** Workspace owners can manage the full API key lifecycle from the UI, and the auth bug for API-key users is resolved
**Verified:** 2026-05-15
**Status:** gaps_found (1 deferred — SC-5 / 16-10 checkpoint)
**Re-verification:** Yes — after 16-07 / 16-08 / 16-09 gap-closure wave

## Re-verification Summary

The original 16-VERIFICATION report (2026-05-12) returned `gaps_found, 3/6` with three CR-level defects (CR-01, CR-02, CR-03) and one SC-5/D-04 policy ambiguity. The 16-07 / 16-08 / 16-09 closure wave has shipped and merged. This re-verification confirms:

- **CR-01 — VERIFIED CLOSED** — `update_api_key` UPDATE now contains `AND revoked_at IS NULL`; the IN-05 anti-assertion has been inverted to a positive guard assertion; `test_patch_revoked_key_returns_404` PASSES.
- **CR-02 — VERIFIED CLOSED** — `resend_verification` now guards `email_encrypted is None` and wraps `_dec(...)` in `try/except` per CLAUDE.md fail-open; both return the same 200 envelope; two regression tests PASS.
- **CR-03 — VERIFIED CLOSED (code level; Playwright run deferred to maintainer)** — `handleResend` now checks `r.ok` before `setResendStatus("sent")`; Playwright spec covers both 200 and 401 paths and is syntactically valid; the browser-binary install was sandbox-denied during execution, but the static GREEN diff is unambiguous.
- **SC-5 / D-04 — DEFERRED** — 16-10-PLAN.md exists with a `checkpoint:decision` gate, intentionally not executed in this wave. Flagged as `deferred`, not `gaps_found`. Per verification context, this does NOT downgrade the verdict.
- **No regressions** on the SC-1 / SC-2 / SC-3 artifacts that originally passed.

## Observable Truths (ROADMAP SC-1..SC-6)

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| SC-1 | Owner sees all active keys at `/api-keys` with labels and last-used timestamps | ✓ VERIFIED | Regression intact — GET endpoint at `api_keys_api.py:124`, page.tsx + ApiKeysTable.tsx still present, `_viewer_creator_filter` still applied (`api_keys_api.py:133`) |
| SC-2 | Owner creates a new key with custom label, copy-once before leaving dialog | ✓ VERIFIED | Regression intact — POST at `api_keys_api.py:64`, NewApiKeyModal reused, maxLength=128 on both create modals |
| SC-3 | Owner revokes key; subsequent requests immediately rejected | ✓ VERIFIED | Regression intact — DELETE handler at `api_keys_api.py:186` preserves `invalidate_api_key_cache`; legacy `workspaces.api_key_hash` clear preserved |
| SC-4 | Owner edits label without revoking — restricted to non-revoked keys (D-04 envelope intact) | ✓ VERIFIED (CR-01 closed) | `api_keys_api.py:171` — `AND revoked_at IS NULL` predicate present; PATCH on revoked key returns `404 {detail: {error: "api_key_not_found"}}` matching DELETE byte-for-byte; `test_patch_revoked_key_returns_404` PASSES; IN-05 anti-assertion replaced with positive guard at `test_phase16_api_keys.py:178` |
| SC-5 | Viewer sees only own key; cannot access create or revoke actions | ⚠️ DEFERRED | Server-side scoping verified-correct (unchanged). UI gating policy ambiguity (ROADMAP SC-5 verbatim vs D-04 viewer self-create) is parked behind `16-10-PLAN.md` checkpoint:decision — intentionally not executed this wave. Treated as deferred override, not a gap (per verification context). |
| SC-6 | API-key-signup user (null `owner_email`) receives resend-verification email — end-to-end truthful | ✓ VERIFIED (CR-02 + CR-03 closed) | Backend: `auth.py:1165-1173` — NULL guard + `try/except Exception as e: # noqa: BLE001`. Frontend: `BillingStatusBanner.tsx:40-46` — `if (!r.ok) { setResendStatus("error"); return; }` precedes `setResendStatus("sent")`. Regression tests PASS; Playwright spec covers both 200 / 401 paths. |

**Score:** 5/6 truths verified (SC-1, SC-2, SC-3, SC-4, SC-6); 1 deferred via override (SC-5 → 16-10).

## CR Closure Evidence

### CR-01 — PATCH `revoked_at IS NULL` guard (D-04 indistinguishability)

| Question | Answer | Evidence |
| --- | --- | --- |
| `update_api_key` UPDATE WHERE clause contains `AND revoked_at IS NULL`? | **yes** | `burnlens_cloud/api_keys_api.py:171` |
| PATCH on revoked key returns `404 {detail: {error: "api_key_not_found"}}` matching DELETE byte-for-byte? | **yes** | Both `api_keys_api.py:181` (PATCH) and `:212` (DELETE) raise `HTTPException(status_code=404, detail={"error": "api_key_not_found"})` — identical |
| Old IN-05 anti-assertion (`assert "revoked_at" not in sql.split("RETURNING")[0]`) removed? | **yes** | `tests/test_phase16_api_keys.py:178` now asserts the positive: `assert "revoked_at IS NULL" in sql.split("RETURNING")[0]` |
| New `test_patch_revoked_key_returns_404` exists and passes? | **yes** | `tests/test_phase16_api_keys.py:387`; `pytest tests/test_phase16_api_keys.py::test_patch_revoked_key_returns_404` → **PASSED** |

**Status:** `verified` — CR-01 closed end-to-end.

### CR-02 — `resend_verification` enumeration-safe under degraded row states

| Question | Answer | Evidence |
| --- | --- | --- |
| NULL `email_encrypted` returns the SAME 200 envelope as verified/missing? | **yes** | `auth.py:1166-1168` — `if email_blob is None: ... return {"message": "If applicable, a verification email has been sent."}` |
| `decrypt_pii` raising returns the SAME 200 envelope? | **yes** | `auth.py:1169-1173` — `try: recipient_email = _dec(email_blob); except Exception as e:  # noqa: BLE001 — fail-open per CLAUDE.md ... return {"message": ...}` |
| `send_verify_email` NOT called on either degraded path? | **yes** | Both early-returns happen BEFORE the `send_verify_email` call at `auth.py:1193`. `tests/test_phase16_auth08_resend.py:167-168` asserts `mock_dec.assert_not_called()` and `mock_send.assert_not_called()`; `:202` asserts `mock_send.assert_not_called()` on the decrypt-error path. |
| Any new 5xx path remains? | **no** | Both regression tests PASS asserting `r.status_code == 200`. |
| T-16-08-01 enumeration oracle threat closed? | **yes** | All three degraded paths (verified / missing user / NULL blob / decrypt fail) return the same 200 message envelope. |

**Status:** `verified` — CR-02 closed end-to-end. 7/7 resend tests pass.

### CR-03 — `BillingStatusBanner` truthful UI

| Question | Answer | Evidence |
| --- | --- | --- |
| `handleResend` checks `r.ok` BEFORE `setResendStatus("sent")`? | **yes** | `frontend/src/components/BillingStatusBanner.tsx:40-46` — `if (!r.ok) { setResendStatus("error"); return; }` precedes the `setResendStatus("sent")` on `:47` |
| Diff confined to handler body (Props/JSX/wrapper byte-identical)? | **yes** | `frontend/src/components/BillingStatusBanner.tsx` — Props interface (`:22-25`), JSX (`:56-130`), and `BillingStatusBannerConnected` wrapper (`:139-146`) unchanged; diff is ~10 lines inside `handleResend` |
| Playwright spec covers both 200 → 'sent' and 401 → 'error'? | **yes** | `frontend/tests/e2e/phase16_resend_banner.spec.ts:76` (`200 response → banner shows "email sent!"`) and `:96` (`401 response → banner shows "try again" (CR-03 regression)`) |
| Spec syntactically valid and picked up by runner? | **yes** | Single Playwright invocation in 16-09 confirmed both tests collected; 120-line spec parses cleanly; tsc passes |
| AUTH-08 sad path human-verification step (previously `THIS WILL FAIL`) now achievable? | **yes (code level)** | The 401 → 'try again' path is now the only branch reachable when `r.ok` is false; Playwright behavioural run is deferred to a maintainer machine (sandbox lacks chromium-1217 binary; documented in 16-09 SUMMARY) |
| Playwright `webServer` active and on non-3000 port post-merge? | **yes** | `frontend/playwright.config.ts:79-88` — `webServer` block active; `url: 'http://127.0.0.1:3500'`; `env: { NEXT_PUBLIC_API_URL: 'https://api.example.test' }`; the `:3000 → :3500` move was committed as `feba521` to avoid dev-server collision |

**Status:** `verified` (code level) — CR-03 closed in source; Playwright behavioural pass is the only remaining human-verification item, and is tractable on a maintainer machine.

## Behavioural Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| All Phase 16 backend tests pass | `.venv/bin/python -m pytest tests/test_phase16_*.py -q` | **36 passed, 7 warnings in 0.30s** | ✓ PASS |
| CR-01 regression test passes | `pytest tests/test_phase16_api_keys.py::test_patch_revoked_key_returns_404 -v` | **PASSED** | ✓ PASS |
| CR-02 NULL-blob regression passes | `pytest tests/test_phase16_auth08_resend.py::test_resend_verification_handles_null_email_encrypted -v` | **PASSED** | ✓ PASS |
| CR-02 decrypt-error regression passes | `pytest tests/test_phase16_auth08_resend.py::test_resend_verification_handles_decrypt_error -v` | **PASSED** | ✓ PASS |
| CR-01 SQL guard present | `grep -c "AND revoked_at IS NULL" burnlens_cloud/api_keys_api.py` | **3** (update_api_key + revoke_api_key + create-cap SELECT) | ✓ PASS |
| CR-02 BLE001 marker present | `grep -c "BLE001" burnlens_cloud/auth.py` | **2** (resend guard + pre-existing `_touch_last_used`) | ✓ PASS |
| CR-03 `r.ok` guard present | `grep -c 'if (!r.ok)' frontend/src/components/BillingStatusBanner.tsx` | **1** | ✓ PASS |
| Playwright spec syntactically valid | `wc -l frontend/tests/e2e/phase16_resend_banner.spec.ts && grep -c 'test(' ...` | **120 lines / 2 tests** | ✓ PASS |
| Playwright webServer on :3500 (not :3000) | `grep -E '127\.0\.0\.1:[0-9]+' frontend/playwright.config.ts` | `http://127.0.0.1:3500` | ✓ PASS |
| Playwright behavioural run | (sandbox can't install chromium-1217) | DEFERRED — maintainer machine | ? SKIP → human-verification |

## Key Link Verification (re-checked)

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| api_keys_api.py::update_api_key | DB UPDATE api_keys SET name | execute_query | ✓ WIRED | Now with `revoked_at IS NULL` guard — CR-01 closed |
| auth.py::resend_verification | pii_crypto.decrypt_pii | local import + try/except | ✓ WIRED | NULL guard + exception-safe — CR-02 closed |
| BillingStatusBanner.handleResend | /auth/resend-verification | fetch with credentials:'include' + r.ok check | ✓ WIRED | Response inspected — CR-03 closed |
| frontend/.../api-keys/page.tsx | GET/POST/PATCH/DELETE /api-keys | apiFetch | ✓ WIRED | Unchanged (SC-1/2/3/4 regression intact) |
| Sidebar.tsx | /api-keys route | href in System group | ✓ WIRED | Unchanged |
| auth.py::get_workspace_by_api_key | DB UPDATE api_keys SET last_used_at | asyncio.create_task | ✓ WIRED | Unchanged; WR-03 still flagged but non-blocking |

## Requirements Coverage (updated)

| Requirement | Source Plan(s) | Status | Evidence |
| --- | --- | --- | --- |
| APIKEY-01 | 16-01, 16-03, 16-04, 16-05 | ✓ SATISFIED | Regression intact |
| APIKEY-02 | 16-05 | ✓ SATISFIED | Regression intact |
| APIKEY-03 | 16-03, 16-04, 16-05 | ✓ SATISFIED | Regression intact |
| APIKEY-04 | 16-01, 16-03, 16-04, 16-05, **16-07** | ✓ SATISFIED | CR-01 closed — terminal-state invariant + D-04 envelope restored |
| APIKEY-05 | 16-03, 16-04, 16-05, **16-10 (deferred)** | ⚠️ DEFERRED | Server-side correct; UI policy ambiguity parked behind 16-10 checkpoint |
| AUTH-08 | 16-02, 16-06, **16-08, 16-09** | ✓ SATISFIED | CR-02 + CR-03 closed end-to-end |

## Anti-Patterns — Status After Closure Wave

| File | Pattern | Original Severity | Closure Status |
| --- | --- | --- | --- |
| burnlens_cloud/api_keys_api.py:148-178 | Missing `revoked_at IS NULL` (CR-01) | 🛑 Blocker | **CLOSED** (line 171) |
| burnlens_cloud/auth.py:1139-1146 | Unguarded `decrypt_pii` (CR-02) | 🛑 Blocker | **CLOSED** (lines 1165-1173) |
| frontend/src/components/BillingStatusBanner.tsx:32-44 | Missing `r.ok` check (CR-03) | 🛑 Blocker | **CLOSED** (lines 40-46) |
| tests/test_phase16_api_keys.py:176-177 | IN-05 anti-assertion | ℹ️ Info | **INVERTED** (line 178 — now positive guard) |
| frontend/src/components/RevokeKeyModal.tsx | WR-01 no typed-name confirm | ⚠️ Warning | Deferred to v1.4 (documented in 16-07/09 SUMMARYs) |
| burnlens_cloud/auth.py:178-182 | WR-03 task GC risk | ⚠️ Warning | Deferred to v1.4 (documented in 16-08 SUMMARY) |
| frontend/src/components/EditKeyLabelInline.tsx:29 | WR-04 untrimmed save | ⚠️ Warning | Deferred to v1.4 (documented in 16-09 SUMMARY) |

The three blockers from the original verification are all closed. The three deferred warnings (WR-01, WR-03, WR-04) and the IN-04/IN-01/WR-02/WR-05/WR-06 info-level items remain in v1.4 backlog; none block the Phase 16 goal.

## Gaps Summary

This re-verification finds **all three CR-level defects closed** end-to-end with regression tests in place and the original passing artifacts un-regressed. The single remaining open item is the **SC-5 / D-04 policy ambiguity**, which is intentionally parked behind `16-10-PLAN.md`'s `checkpoint:decision` gate and is not executed in this gap-closure wave per the explicit verification-context instruction. Treated as `deferred` (override applied), not `gaps_found`.

**Net verdict:** 5 of 6 must-haves verified end-to-end; 1 deferred via documented checkpoint plan. The Phase 16 goal — "Workspace owners can manage the full API key lifecycle from the UI, and the auth bug for API-key users is resolved" — is **achieved** at the code level, modulo the SC-5 UI-policy decision tracked in 16-10.

The one residual human-verification item is the **Playwright behavioural run** of `phase16_resend_banner.spec.ts` on a maintainer machine (sandbox lacked the chromium-1217 binary during 16-09 execution; documented and tractable).

---

_Re-verified: 2026-05-15_
_Verifier: Claude (gsd-verifier)_
