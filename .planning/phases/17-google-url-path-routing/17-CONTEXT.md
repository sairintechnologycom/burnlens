# Phase 17 — Google URL-Path Routing — CONTEXT

**Date:** 2026-05-25
**Phase:** 17 — Google URL-Path Routing
**Milestone:** v1.3
**Requirements:** ROUTE-08

## Domain

Make `decide_route()`'s downgrade selection actually take effect for Google
Generative Language API requests by rewriting the outbound URL path's model
segment. Today only `body["model"]` is rewritten, which Google ignores —
Google encodes the model in `/v1beta/models/{model}:method`. This is the
deferred follow-up explicitly called out in `14-CONTEXT.md` (lines 278–283,
311) and in the inline comment in `burnlens/proxy/interceptor.py:445–448`.

Tightly scoped, single-file behavior change in the OSS proxy. No cloud,
no UI, no schema, no new pricing.

## Carried Forward From Earlier Phases

- **DOWNGRADE_MAP** (Phase 14) already contains Google entries:
  `gemini-1.5-pro → gemini-1.5-flash`, `gemini-2.0-pro → gemini-1.5-flash`.
  Do not extend the map in this phase — that's a v1.4 follow-up.
- **`decide_route()`** signature, `RouteDecision` shape, and the
  `if decision.downgraded:` call site in `interceptor.py` are locked
  from Phase 14. This phase only changes what happens *inside* that block.
- **Provider plugin architecture** (M-1, project_m1_shipped): adding a
  hook to `Provider` base + overriding in `providers/google.py` is the
  established pattern. Honor it.
- **Body rewrite NOTE comment** at `interceptor.py:445–448` is removed by
  this phase.

## Decisions

### 1. URL path patterns covered
Rewrite when path matches `/<version>/models/{model}:generateContent` or
`/<version>/models/{model}:streamGenerateContent`. Both `v1beta` and `v1`
prefixes covered (match on the `:method` suffix, not the version).
`:countTokens`, `:embedContent`, `:batchEmbedContents`, tuning paths,
etc. pass through unmodified — they have different cost characteristics
and downgrading them is not in scope.

### 2. Model name normalization for DOWNGRADE_MAP lookup
- Try exact match first.
- On miss: strip a trailing `-latest`, `-001`, `-002`, `-NNN` suffix (regex
  `-(latest|\d{3,})$`) and retry lookup.
- The rewritten URL uses the downgrade target's **bare** name from the map
  (e.g. `gemini-1.5-flash`, never `gemini-1.5-flash-latest`).
- This applies to lookup only; non-Google providers keep exact-match.

### 3. Code location — new Provider hook
Add to `burnlens/providers/base.py`:
```python
def rewrite_path_for_routing(self, path: str, routed_model: str) -> str:
    """Default no-op. Override for providers that encode model in URL path."""
    return path
```
Override in `burnlens/providers/google.py` with the actual regex substitution
restricted to the two generation methods above. `interceptor.py` calls
`upstream_path = provider.rewrite_path_for_routing(upstream_path, decision.routed_model)`
inside the existing `if decision.downgraded:` block, immediately before the
body-rewrite step.

### 4. Body rewrite behavior
Replace the unconditional `body_dict["model"] = decision.routed_model` with a
guarded `if "model" in body_dict:`. Provider-agnostic; preserves
OpenAI/Anthropic behavior unchanged; naturally skips Google (whose body has
no `model` field). Remove the four-line NOTE comment at
`interceptor.py:445–448` — the limitation it documents no longer exists.

### Logging
The existing `logger.info("[BurnLens] Downgraded %s → %s | …")` line stays
as-is. No new log line for the URL rewrite — it's an implementation detail
of the same logical event.

## Out of Scope (Deferred Ideas)

- Vertex AI endpoint (`*-aiplatform.googleapis.com`) — different URL shape
  (`/projects/.../locations/.../publishers/google/models/{model}:predict`).
  Tracked separately if/when a Vertex provider is added.
- Expanding `DOWNGRADE_MAP` with more Google models (e.g. `gemini-2.0-flash`,
  `gemini-2.5-pro` entries) — already noted as a v1.4 follow-up.
- Per-request override header to disable downgrade — Phase 14 deferred.
- Downgrading non-generation methods (`:countTokens`, embeddings) — not a
  user-facing cost win.

## Canonical Refs

- `.planning/ROADMAP.md` (lines 94–102) — Phase 17 entry and success criteria
- `.planning/REQUIREMENTS.md` (line 33) — ROUTE-08
- `.planning/milestones/v1.2-phases/14-budget-aware-model-downgrade/14-CONTEXT.md`
  (lines 57–60, 278–283, 311) — locked DOWNGRADE_MAP and deferral note
- `.planning/phases/14-budget-aware-model-downgrade/14-04-SUMMARY.md`
  (lines 39, 55) — current body-rewrite call site and the documented limitation
- `burnlens/proxy/interceptor.py` (lines 211–222, 437–463) — current model
  extraction from path, current `if decision.downgraded:` block
- `burnlens/providers/base.py` — site for new `rewrite_path_for_routing()`
  hook
- `burnlens/providers/google.py` — site for Google-specific override
- `burnlens/proxy/router.py` — `decide_route()` / `RouteDecision`
  (consumed, not modified)

## Code Context

- **Reusable:** `_extract_model_from_path()` (interceptor.py:211) already
  parses the `/v1beta/models/{model}:method` shape — the new override can
  share its parsing approach (or import a small shared helper).
- **Streaming detection** (`_is_streaming()`, interceptor.py:250) checks for
  `:streamGenerateContent` in the path — confirms streaming continues to work
  after the rewrite because the `:streamGenerateContent` suffix is preserved.
- **Provider plugin pattern:** `providers/{name}.py` + `pricing_data/{name}.json`
  with no core changes required (CLAUDE.md "Provider Routing" section).
- **Test fixtures:** existing Google tests live in
  `tests/test_proxy.py` / `tests/providers/test_google.py` (verify with grep
  during research).
