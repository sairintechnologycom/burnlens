---
phase: 17-google-url-path-routing
plan: 01
subsystem: proxy
tags:
  - proxy
  - routing
  - google
  - provider-plugin
  - route-08
requirements:
  - ROUTE-08
dependency-graph:
  requires:
    - 14-budget-aware-model-downgrade  # DOWNGRADE_MAP, RouteDecision, decide_route()
    - M-1                              # Provider plugin architecture
  provides:
    - Provider.rewrite_path_for_routing(path, routed_model) -> str
    - GoogleProvider._MODEL_IN_PATH_RE (compiled regex)
    - burnlens.providers.downgrade._SUFFIX_RE (compiled regex)
    - "Google URL-path downgrade now actually takes effect upstream"
  affects:
    - burnlens/proxy/interceptor.py  # downgrade block now polymorphic
tech-stack:
  added: []
  patterns:
    - "Polymorphic Provider hook (no `if provider.name == \"google\":` branch)"
    - "Module-level compiled regex (one parse, repeated use)"
    - "Named backreferences (\\g<1>/\\g<3>) to avoid digit ambiguity in substitution"
    - "Guarded body mutation (`if \"model\" in body_dict:`)"
key-files:
  created: []
  modified:
    - burnlens/providers/base.py
    - burnlens/providers/google.py
    - burnlens/providers/downgrade.py
    - burnlens/proxy/interceptor.py
    - tests/test_providers_plugin.py
    - tests/test_router.py
decisions:
  - "Polymorphic Provider.rewrite_path_for_routing() hook — no provider-name branching in interceptor"
  - "Regex restricted to /v1/ and /v1beta/ for :generateContent and :streamGenerateContent only — :countTokens / :embedContent / :batchEmbedContents / tuning paths pass through"
  - "DOWNGRADE_MAP normalization regex `-(latest|\\d{3,})$` applies to all providers (not just Google); safe because non-Google entries have no `-latest` collisions"
  - "Body rewrite stays inside try/except (fail-open); URL rewrite is pure-str regex with no I/O so sits outside by design"
metrics:
  duration-min: 21
  completed: 2026-05-25T11:06:43Z
  tasks: 3
  files-modified: 6
  lines-added: 189
  lines-removed: 8
  tests-added: 19
---

# Phase 17 Plan 01: Google URL-Path Routing Summary

**One-liner:** Made `decide_route()`'s downgrade decision actually take effect for Google Generative Language API requests by rewriting `/v1beta/models/{model}:method` URL paths via a polymorphic Provider hook — closes ROUTE-08 and removes the v2-deferred limitation from Phase 14.

## What Was Built

### New public interface

```python
# burnlens/providers/base.py
class Provider(ABC):
    def rewrite_path_for_routing(self, path: str, routed_model: str) -> str:
        """Default no-op. Override for providers that encode model in URL path."""
        return path
```

Optional override on `Provider` base class — sibling of the existing
`normalize_model_name()` and `headers_to_strip()` hooks.

### Google override

```python
# burnlens/providers/google.py
class GoogleProvider(Provider):
    _MODEL_IN_PATH_RE = re.compile(
        r"(/(?:v1|v1beta)/models/)([^:/]+)(:(?:generateContent|streamGenerateContent))"
    )

    def rewrite_path_for_routing(self, path: str, routed_model: str) -> str:
        return self._MODEL_IN_PATH_RE.sub(
            rf"\g<1>{routed_model}\g<3>", path, count=1
        )
```

Linear regex with no nested quantifiers — no ReDoS risk (T-17-01 mitigated).
Restricted to `:generateContent` / `:streamGenerateContent` only;
`:countTokens`, `:embedContent`, `:batchEmbedContents`, and `/tunedModels/`
paths all fall outside the pattern and pass through unmodified.

### DOWNGRADE_MAP normalization

```python
# burnlens/providers/downgrade.py
_SUFFIX_RE = re.compile(r"-(latest|\d{3,})$")

def get_downgrade_model(model: str) -> str | None:
    exact = DOWNGRADE_MAP.get(model)
    if exact is not None:
        return exact
    stripped = _SUFFIX_RE.sub("", model)
    if stripped != model:
        return DOWNGRADE_MAP.get(stripped)
    return None
```

Exact-match first, then strip `-latest` / `-001` / `-002` / `-NNN` (3+ digits)
and retry. Returns the bare downgrade target (e.g. `gemini-1.5-flash`,
never `gemini-1.5-flash-latest`).

### Interceptor wiring

`burnlens/proxy/interceptor.py` downgrade block now:

1. Calls `upstream_path = provider.rewrite_path_for_routing(upstream_path, decision.routed_model)` **before** the body rewrite.
2. Wraps body mutation with `if "model" in body_dict:` so Google bodies (no `model` field) are forwarded byte-exact.
3. The four-line `NOTE: Google URL-path model rewrite is deferred to v2` comment is gone.
4. No new log lines, no `if provider.name == "google":` branch.
5. URL rewrite sits outside the `try/except` (pure regex, no I/O); body rewrite stays inside (fail-open preserved).

## Files Modified

| File | Lines +/− | Purpose |
|------|-----------|---------|
| `burnlens/providers/base.py` | +8 / −0 | Default no-op `rewrite_path_for_routing` |
| `burnlens/providers/google.py` | +25 / −0 | `_MODEL_IN_PATH_RE` + override |
| `burnlens/providers/downgrade.py` | +20 / −3 | `_SUFFIX_RE` + exact-then-stripped lookup |
| `burnlens/proxy/interceptor.py` | +14 / −6 | Polymorphic hook call + body-rewrite guard + NOTE removal |
| `tests/test_providers_plugin.py` | +89 / −0 | `TestRewritePathForRouting` (9) + `TestDowngradeMapNormalization` (9) |
| `tests/test_router.py` | +32 / −0 | `test_google_body_without_model_not_mutated_on_downgrade` |
| **TOTAL** | **+189 / −9** | 4 production files, 2 test files |

## Tests Added

- **TestRewritePathForRouting (9 tests):**
  - `test_google_rewrites_generate_content`
  - `test_google_rewrites_stream_generate_content` (asserts `:streamGenerateContent` suffix preserved verbatim for `_is_streaming()`)
  - `test_google_rewrites_v1_prefix`
  - `test_google_passes_through_count_tokens`
  - `test_google_passes_through_embed_content`
  - `test_google_passes_through_batch_embed`
  - `test_google_passes_through_tuning_path`
  - `test_openai_default_no_op`
  - `test_anthropic_default_no_op`
- **TestDowngradeMapNormalization (9 tests):**
  - `test_exact_match_wins`, `test_strips_latest_suffix`, `test_strips_001_suffix`, `test_strips_002_suffix`, `test_strips_arbitrary_nnn_suffix`
  - `test_does_not_strip_short_numeric_suffix` (regex requires `\d{3,}`)
  - `test_unmapped_returns_none`
  - `test_openai_exact_match_still_works`
  - `test_openai_normalization_no_false_positive`
- **test_router.py (+1):**
  - `test_google_body_without_model_not_mutated_on_downgrade` — locks in the `if "model" in body_dict:` guard.

**Test count delta: +19 tests added. All pass.**

## Commits

| # | Hash | Title |
|---|------|-------|
| 1 | `fad0d0e` | test(17-01): add failing tests for Google URL-path rewrite hook, downgrade normalization, and body-rewrite guard (RED) |
| 2 | `86368d2` | feat(17-01): add rewrite_path_for_routing Provider hook + Google override + DOWNGRADE_MAP suffix normalization (GREEN) |
| 3 | `c5b9124` | feat(17-01): wire URL-path rewrite into downgrade block, guard body rewrite, remove deferred-to-v2 NOTE (closes ROUTE-08) |

## Verification

### Grep invariants — all PASS

```
[1] base.py rewrite hook:       PASS
[2] google.py rewrite hook:     PASS
[3] interceptor.py call:        PASS  (provider.rewrite_path_for_routing × 1)
[4] body-rewrite guard:         PASS  (if "model" in body_dict:)
[5] NOTE removed:               PASS  (deferred-to-v2 comment gone)
[6] no provider.name branch:    PASS  (polymorphic hook honored)
[7] _SUFFIX_RE present:         PASS
```

### Targeted unit tests — all PASS

```
pytest tests/test_providers_plugin.py::TestRewritePathForRouting \
       tests/test_providers_plugin.py::TestDowngradeMapNormalization \
       tests/test_router.py::test_google_body_without_model_not_mutated_on_downgrade \
       tests/test_router.py::test_request_body_rewritten_with_routed_model
→ 20 passed in 0.17s
```

### Wider test surface — all PASS

```
pytest tests/test_proxy.py tests/test_providers_plugin.py tests/test_router.py
       tests/test_streaming.py tests/test_cost.py tests/test_storage.py
       tests/test_analysis.py tests/test_proxy_env_fallback.py tests/test_alerts.py
       tests/test_billing_usage.py tests/test_billing_google.py
       tests/test_key_label_interceptor.py tests/test_otel.py tests/test_otel_forwarder.py
       tests/test_patch.py tests/test_recommender.py tests/test_reports.py
→ 418 passed in 22.48s
```

### Pre-existing failures (out of scope)

Cloud-backend tests requiring a live Postgres database (`test_audit_log`,
`test_archival`, `test_billing_webhook_phase7`, `test_phase*`, etc.) fail
in the worktree environment because there is no Postgres reachable. These
failures are **identical with and without this plan's changes** —
explicitly verified by running `test_archival` + `test_audit_log` on the
parent commit (`757a1f5`) and on `HEAD`: both produce the same 9 failures.
These are pre-existing environment-level issues, not regressions.

## Threat Model Status

| Threat | Mitigation | Status |
|--------|-----------|--------|
| T-17-01 (ReDoS) | Linear regex, no nested quantifiers, compiled at module load | mitigated |
| T-17-02 (URL injection / path traversal) | `routed_model` sourced only from hardcoded `DOWNGRADE_MAP`; named backreferences (`\g<1>`, `\g<3>`); invariant documented in docstring | mitigated |
| T-17-03 (Log leakage) | No new `logger.info` lines added; existing `[BurnLens] Downgraded` line unchanged | mitigated |
| T-17-04 (Failure to fail-open) | URL rewrite is pure-str regex (cannot raise); body rewrite still in `try/except` | mitigated |
| T-17-05 (Future provider misroute) | Base-class docstring explicit; per-provider test class convention established | accepted |

## Success Criteria — Met

1. ROADMAP success #1 (Google downgrade rewrites URL path) — verified by 3 rewrite tests.
2. ROADMAP success #2 (v1.2 body-rewrite preserved) — verified by `test_request_body_rewritten_with_routed_model` (still green) + `test_google_body_without_model_not_mutated_on_downgrade`.
3. CONTEXT #1 (pass-through for non-generation methods) — verified by 4 pass-through tests.
4. CONTEXT #2 (DOWNGRADE_MAP normalization) — verified by 9 normalization tests.
5. CONTEXT #3 (polymorphic Provider hook) — verified by grep invariants #1, #2, #3, #6.
6. CONTEXT #4 (body guard + NOTE removed) — verified by grep invariants #4 and #5.
7. Streaming preservation (`:streamGenerateContent` retained) — verified by `test_google_rewrites_stream_generate_content`.
8. Fail-open preserved — verified by code structure (URL rewrite outside try/except documented; body rewrite still inside).
9. No regressions on the relevant test surface — 418 passed.

## ROUTE-08 Status: CLOSED

The deferred-to-v2 limitation documented in
`burnlens/proxy/interceptor.py:445-448` (now removed) and in Phase 14
CONTEXT (lines 278-283) no longer exists. A budget-triggered downgrade
for `gemini-1.5-pro → gemini-1.5-flash` now produces an upstream URL of
`https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent`
(not the original `gemini-1.5-pro` path).

## Deviations from Plan

None — plan executed exactly as written. All three tasks completed in
order; test count and grep invariants match the plan's acceptance
criteria verbatim.

## Deferred Follow-ups (out of scope, tracked elsewhere)

- **Vertex AI URL shape** (`*-aiplatform.googleapis.com`,
  `/projects/.../locations/.../publishers/google/models/{model}:predict`)
  — tracked separately when a Vertex provider is added.
- **Expanding `DOWNGRADE_MAP`** with newer Gemini models
  (`gemini-2.0-flash`, `gemini-2.5-pro`) — v1.4 follow-up per Phase 17
  CONTEXT.
- **Per-request override header** to disable downgrade — Phase 14 deferral
  carried forward.
- **Downgrading non-generation methods** (`:countTokens`, embeddings) —
  not a user-facing cost win, deferred indefinitely.

## Self-Check: PASSED

**Files claimed exist:**

- `burnlens/providers/base.py` — FOUND (modified)
- `burnlens/providers/google.py` — FOUND (modified)
- `burnlens/providers/downgrade.py` — FOUND (modified)
- `burnlens/proxy/interceptor.py` — FOUND (modified)
- `tests/test_providers_plugin.py` — FOUND (modified)
- `tests/test_router.py` — FOUND (modified)

**Commits claimed exist:**

- `fad0d0e` — FOUND (`test(17-01): add failing tests...`)
- `86368d2` — FOUND (`feat(17-01): add rewrite_path_for_routing...`)
- `c5b9124` — FOUND (`feat(17-01): wire URL-path rewrite...closes ROUTE-08`)
