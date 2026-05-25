---
phase: 17-google-url-path-routing
verified: 2026-05-25T00:00:00Z
status: passed
score: 8/8 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: none
  previous_score: n/a
---

# Phase 17: Google URL-Path Routing — Verification Report

**Phase Goal (ROADMAP.md):** The OSS proxy correctly downgrades Google model requests by rewriting the URL path, not just the request body. Closes ROUTE-08.

**Verified:** 2026-05-25
**Status:** PASSED
**Re-verification:** No — initial verification

## Goal Achievement: PASS

ROUTE-08 is closed in the codebase. The polymorphic `Provider.rewrite_path_for_routing()` hook is implemented in `burnlens/providers/base.py`, overridden in `burnlens/providers/google.py` with a linear (ReDoS-safe) regex restricted to the two generation methods, wired into the downgrade block of `burnlens/proxy/interceptor.py` immediately before the body rewrite, and the deferred-to-v2 NOTE comment is gone. The body rewrite is now guarded by `if "model" in body_dict:` so Google bodies (which have no `model` field) are forwarded byte-exact. DOWNGRADE_MAP normalization (`-latest`/`-NNN`) is implemented in `burnlens/providers/downgrade.py`. All 20 must-have unit tests pass. 273 OSS regression tests pass.

## Observable Truths

| #   | Truth                                                                                                       | Status     | Evidence                                                                                                                                                                                                |
| --- | ----------------------------------------------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Google `:generateContent` URL path is rewritten with downgrade model name                                   | VERIFIED   | `test_google_rewrites_generate_content` + `test_google_rewrites_v1_prefix` PASS; regex `_MODEL_IN_PATH_RE` in `google.py:28-30` matches `/v1/` and `/v1beta/` with `\g<1>{routed_model}\g<3>` substitution |
| 2   | Google `:streamGenerateContent` retains its suffix so `_is_streaming()` continues to detect streaming       | VERIFIED   | `test_google_rewrites_stream_generate_content` PASS — asserts output ends in `:streamGenerateContent`. `_is_streaming()` at `interceptor.py:250-257` checks `":streamGenerateContent" in upstream_path`   |
| 3   | `:countTokens`, `:embedContent`, `:batchEmbedContents`, tuning paths pass through unmodified                | VERIFIED   | 4 pass-through tests PASS (`test_google_passes_through_count_tokens`, `test_google_passes_through_embed_content`, `test_google_passes_through_batch_embed`, `test_google_passes_through_tuning_path`)  |
| 4   | OpenAI/Anthropic body['model'] rewrite preserved exactly                                                    | VERIFIED   | `test_request_body_rewritten_with_routed_model` (pre-existing) PASS; `test_openai_default_no_op` + `test_anthropic_default_no_op` PASS; downgrade block at `interceptor.py:456-460` still mutates body when key present |
| 5   | Body without `model` field does not KeyError; original bytes are preserved                                  | VERIFIED   | `test_google_body_without_model_not_mutated_on_downgrade` PASS — drives real `decide_route()` to `decision.downgraded=True` then asserts Google body unchanged. Guard at `interceptor.py:458`             |
| 6   | DOWNGRADE_MAP normalizes `-latest`/`-001`/`-002`/`-NNN` (3+ digits) suffixes for lookup                     | VERIFIED   | 9 tests in `TestDowngradeMapNormalization` PASS. `_SUFFIX_RE = re.compile(r"-(latest|\d{3,})$")` in `downgrade.py:25`. `get_downgrade_model()` does exact-match-then-strip lookup                       |
| 7   | The 4-line NOTE comment at interceptor.py:445–448 ("deferred to v2") is removed                             | VERIFIED   | `grep "Google URL-path model rewrite is deferred to v2" interceptor.py` returns nothing; `grep "NOTE: Google models are specified in the URL path" interceptor.py` returns nothing                       |
| 8   | No `if provider.name == "google":` polymorphic branch in the downgrade dispatch                             | VERIFIED   | Downgrade block at `interceptor.py:444-471` uses `provider.rewrite_path_for_routing(...)` once. The two `provider_name == "google"` branches at lines 202/213 are in pre-existing helper functions (`_extract_model`, `_extract_model_from_path`), not in the downgrade dispatch — these are unchanged by phase 17 |

**Score:** 8/8 truths verified.

## Required Artifacts

| Artifact                              | Expected                                                                       | Status     | Details                                                                                                       |
| ------------------------------------- | ------------------------------------------------------------------------------ | ---------- | ------------------------------------------------------------------------------------------------------------- |
| `burnlens/providers/base.py`          | Default no-op `rewrite_path_for_routing(path, routed_model)` hook              | VERIFIED   | Lines 97-103. Returns `path` unchanged. Docstring documents override contract.                                |
| `burnlens/providers/google.py`        | `GoogleProvider.rewrite_path_for_routing` + `_MODEL_IN_PATH_RE` compiled regex | VERIFIED   | Regex at lines 28-30; method at lines 43-56. `re.sub(rf"\g<1>{routed_model}\g<3>", path, count=1)` — named backrefs as planned. |
| `burnlens/providers/downgrade.py`     | `get_downgrade_model()` with exact-then-stripped lookup; `_SUFFIX_RE`          | VERIFIED   | `_SUFFIX_RE` at line 25; `get_downgrade_model()` at lines 28-42 implements exact-first-then-strip-retry.       |
| `burnlens/proxy/interceptor.py`       | Polymorphic hook call BEFORE body rewrite; `if "model" in body_dict:` guard; NOTE gone | VERIFIED   | Hook call at lines 450-452; body guard at line 458; NOTE comment gone (replaced with phase-17 inline comment) |
| `tests/test_providers_plugin.py`      | `TestRewritePathForRouting` + `TestDowngradeMapNormalization` classes          | VERIFIED   | Classes at lines 244 and 296; all 18 test methods present.                                                    |
| `tests/test_router.py`                | `test_google_body_without_model_not_mutated_on_downgrade`                      | VERIFIED   | At line 204. Uses real `decide_route()` with `_cfg`/`TEAM_SPEND_PATCH`.                                      |

## Key Link Verification

| From                                       | To                                                          | Via                                                                          | Status |
| ------------------------------------------ | ----------------------------------------------------------- | ---------------------------------------------------------------------------- | ------ |
| `interceptor.py` downgrade block           | `Provider.rewrite_path_for_routing`                         | `provider.rewrite_path_for_routing(upstream_path, decision.routed_model)`    | WIRED  |
| `GoogleProvider.rewrite_path_for_routing`  | `_MODEL_IN_PATH_RE`                                         | `self._MODEL_IN_PATH_RE.sub(...)` with named backrefs `\g<1>`, `\g<3>`       | WIRED  |
| `router.py::decide_route`                  | `downgrade.py::get_downgrade_model`                         | Import + call returning `RouteDecision.routed_model`                         | WIRED  |
| Rewritten `upstream_path`                  | `upstream_url = f"{provider.upstream_base}{upstream_path}"` | Same local variable consumed two lines later (line 473)                      | WIRED  |
| Rewritten path with `:streamGenerateContent` | `_is_streaming()` SSE detection                           | `_is_streaming()` checks `":streamGenerateContent" in upstream_path`         | WIRED  |

## Data-Flow Trace (Level 4)

| Artifact                                  | Data Variable    | Source                                                | Produces Real Data | Status   |
| ----------------------------------------- | ---------------- | ----------------------------------------------------- | ------------------ | -------- |
| `interceptor.py` downgrade block          | `upstream_path`  | Rewritten by `provider.rewrite_path_for_routing()` then consumed by `upstream_url = f"{provider.upstream_base}{upstream_path}"` at line 473 | Yes — rewritten value flows directly into the outbound URL                | FLOWING  |
| `get_downgrade_model("gemini-1.5-pro")`   | return value     | `DOWNGRADE_MAP.get(model)`                            | Yes — returns `"gemini-1.5-flash"` (verified by `test_exact_match_wins`) | FLOWING  |
| `get_downgrade_model("gemini-1.5-pro-latest")` | return value | `_SUFFIX_RE.sub("", model)` then `DOWNGRADE_MAP.get(stripped)` | Yes — returns `"gemini-1.5-flash"` (verified by `test_strips_latest_suffix`) | FLOWING  |

## Test Results

### Phase 17 must-have tests (20/20 PASS)

```
pytest tests/test_providers_plugin.py::TestRewritePathForRouting \
       tests/test_providers_plugin.py::TestDowngradeMapNormalization \
       tests/test_router.py::test_google_body_without_model_not_mutated_on_downgrade \
       tests/test_router.py::test_request_body_rewritten_with_routed_model -v

→ 20 passed in 0.05s
```

### Plugin + router test surface (65/65 PASS)

```
pytest tests/test_providers_plugin.py tests/test_router.py -x --tb=short -q
→ 65 passed in 0.31s
```

### OSS regression surface (273/273 PASS)

```
pytest tests/test_proxy.py tests/test_providers_plugin.py tests/test_router.py \
       tests/test_streaming.py tests/test_cost.py tests/test_storage.py \
       tests/test_billing_google.py tests/test_recommender.py
→ 273 passed in 7.05s
```

## Grep Invariants — All PASS

| # | Invariant | Result |
|---|-----------|--------|
| 1 | `grep -q "def rewrite_path_for_routing" burnlens/providers/base.py` | PASS |
| 2 | `grep -q "def rewrite_path_for_routing" burnlens/providers/google.py` | PASS |
| 3 | `grep -c "provider.rewrite_path_for_routing(" burnlens/proxy/interceptor.py` | 1 (exactly once, as planned) |
| 4 | `grep -q 'if "model" in body_dict:' burnlens/proxy/interceptor.py` | PASS |
| 5 | `! grep -q "Google URL-path model rewrite is deferred to v2" burnlens/proxy/interceptor.py` | PASS (NOTE removed) |
| 6 | `! grep -q "NOTE: Google models are specified in the URL path" burnlens/proxy/interceptor.py` | PASS (NOTE removed) |
| 7 | `grep -q "_SUFFIX_RE" burnlens/providers/downgrade.py` | PASS |
| 8 | `grep -q "_MODEL_IN_PATH_RE" burnlens/providers/google.py` | PASS |
| 9 | `grep -q "generateContent\|streamGenerateContent" burnlens/providers/google.py` | PASS |
| 10 | No `if provider.name == "google":` in any phase-17-modified file | PASS |

## Threat-Model Mitigations

| Threat | Mitigation | Status |
|--------|-----------|--------|
| T-17-01 (ReDoS) | `_MODEL_IN_PATH_RE` is anchored to fixed literal prefixes `/v1/` or `/v1beta/`, uses negated-class `[^:/]+` for the model segment, and no nested quantifiers. Compiled once at module load. | VERIFIED (regex inspected at google.py:28-30) |
| T-17-02 (URL injection / path traversal) | `routed_model` flows only from hardcoded `DOWNGRADE_MAP` → `get_downgrade_model()` → `decision.routed_model`. Substitution uses named backreferences `\g<1>` and `\g<3>` to avoid digit ambiguity. Invariant documented in `google.py:50-52` docstring. | VERIFIED (no user-input path to `routed_model`; named backrefs used) |
| T-17-03 (Log leakage) | No new `logger.info` lines added in the downgrade block. The single existing `[BurnLens] Downgraded %s → %s | Budget remaining: $%.4f (%.1f%%)` line at interceptor.py:465-471 is preserved verbatim. | VERIFIED (only 1 logger.info in the downgrade block, same as before) |
| T-17-04 (Failure to fail-open) | Body rewrite remains inside `try/except Exception: pass` (interceptor.py:456-462). URL-path rewrite is a pure regex on str input (no I/O, cannot raise on valid input) and sits outside the try/except by design — documented in inline comment at interceptor.py:445-449. | VERIFIED (structure inspected at lines 444-471) |

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| ROUTE-08    | 17-01-PLAN  | `decide_route()` applies model downgrade via URL-path rewrite for Google Generative Language API requests | SATISFIED | Truths 1-3 verified; closing the deferred-to-v2 limitation explicitly called out in REQUIREMENTS.md and 14-CONTEXT.md |

## Anti-Patterns Scan

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| `burnlens/providers/base.py` | None | — | Clean |
| `burnlens/providers/google.py` | None | — | Clean |
| `burnlens/providers/downgrade.py` | None | — | Clean |
| `burnlens/proxy/interceptor.py` | Pre-existing `if provider_name == "google":` branches at lines 202 and 213 | Info | These are in `_extract_model()` and `_extract_model_from_path()` — unchanged helper functions, NOT in the polymorphic dispatch under verification. The phase-17 dispatch in the downgrade block correctly uses the polymorphic hook. |
| `tests/test_providers_plugin.py` | None | — | Clean |
| `tests/test_router.py` | None | — | Clean |

## CLAUDE.md "Provider Routing" Convention Compliance

The CLAUDE.md "Provider Routing" section states: *"Adding a provider = one new file in `burnlens/providers/` + one new pricing JSON. No core changes required."* The implementation honors this:

- Adding a hook on `Provider` base is the established pattern (sibling of `normalize_model_name`, `headers_to_strip`).
- The Google override lives in `burnlens/providers/google.py` — no `if provider.name == "google":` branch in `interceptor.py` for the new dispatch.
- A future provider that encodes models in the URL path only needs to override `rewrite_path_for_routing()` — no core changes required.

VERIFIED.

## Pre-existing Failures (Not Phase 17 Regressions)

`tests/test_cloud_sync_e2e.py::test_proxy_request_syncs_to_cloud` fails with `KeyError: 'api_key'`. This test was NOT modified by phase 17 (`git diff --stat 757a1f5..HEAD` shows only phase-17 files: base.py, google.py, downgrade.py, interceptor.py, test_providers_plugin.py, test_router.py, plus the summary). The failure is unrelated to URL-path routing or downgrade behavior (it asserts on a sync-batch `api_key` field). Phase 17 SUMMARY.md also notes pre-existing failures in cloud-backend tests requiring live Postgres. NOT a phase-17 regression.

## Deferred Follow-ups (Out of Scope per CONTEXT)

- **Vertex AI URL shape** (`*-aiplatform.googleapis.com`, `/projects/.../locations/.../publishers/google/models/{model}:predict`) — tracked separately when a Vertex provider is added.
- **Expanding `DOWNGRADE_MAP`** with newer Gemini models (`gemini-2.0-flash`, `gemini-2.5-pro`) — v1.4 follow-up.
- **Per-request override header** to disable downgrade — Phase 14 deferral carried forward.
- **Downgrading non-generation methods** (`:countTokens`, embeddings) — not a user-facing cost win.

## Final Verdict: PASS

ROUTE-08 is closed. All 8 must-have truths verified. All 6 artifacts present with correct content. All 5 key links wired. All 4 active threat-model mitigations in code. All 10 grep invariants pass. 20/20 must-have tests + 273/273 OSS regression tests pass. The deferred-to-v2 NOTE comment is removed. The CLAUDE.md Provider Routing convention is honored — no `if provider.name == "google":` branch in the polymorphic dispatch. The single unrelated pre-existing failure (`test_cloud_sync_e2e.py`) is not caused by phase 17 changes.

A budget-triggered downgrade for `gemini-1.5-pro → gemini-1.5-flash` now correctly produces an upstream URL of `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent` (not the original `gemini-1.5-pro` path), while preserving the OpenAI/Anthropic body-rewrite behavior unchanged.

---

_Verified: 2026-05-25_
_Verifier: Claude (gsd-verifier)_
