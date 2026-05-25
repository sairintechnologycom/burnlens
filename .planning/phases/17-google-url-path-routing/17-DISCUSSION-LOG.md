# Phase 17 — Discussion Log

**Date:** 2026-05-25
**Mode:** discuss (default)

## Areas Selected for Discussion

All four presented gray areas selected by user (multi-select).

---

## Area 1: URL path patterns to cover

**Options presented:**
1. Generation methods only — `:generateContent` + `:streamGenerateContent` only (recommended)
2. All `:method` suffixes generically
3. All paths containing `/models/{x}/`

**User selection:** Option 1 — generation methods only.

**Rationale captured:** Other methods (`:countTokens`, `:embedContent`) have
different cost characteristics; downgrading them isn't a meaningful win and
risks unexpected behavior.

---

## Area 2: Model name matching with version suffixes

**Context:** Google traffic commonly uses `-latest`, `-001`, `-002` suffixes
(google-genai SDK defaults to `-latest`). DOWNGRADE_MAP only has bare keys.

**Options presented:**
1. Normalize: strip suffix, look up bare name (recommended)
2. Exact-match only
3. Preserve suffix on rewrite

**User selection:** Option 1 — normalize on lookup, rewrite to bare downgrade name.

---

## Area 3: Where the URL rewrite lives

**Options presented:**
1. New `Provider.rewrite_path_for_routing()` hook (recommended)
2. Inline `if provider.name == "google":` in interceptor.py
3. Helper in `burnlens/proxy/router.py`

**User selection:** Option 1 — provider hook with no-op default, Google override.

**Rationale captured:** Matches the documented plugin pattern in CLAUDE.md;
keeps Google-specific logic in `providers/google.py`; makes future providers
(e.g. Vertex) easy to add.

---

## Area 4: Body rewrite behavior for Google

**Options presented:**
1. Only rewrite body when `"model"` key already exists (recommended, provider-agnostic)
2. Skip body rewrite when `provider.name == "google"`
3. Leave as-is (always inject `model` key)

**User selection:** Option 1 — guarded `if "model" in body_dict:`.

**Side effect:** Removes the four-line NOTE comment at
`interceptor.py:445–448` since the limitation it documents will no longer exist.

---

## Deferred Ideas (Out of Scope)

- Vertex AI endpoint URL rewriting — different path shape, needs its own provider.
- Expanding DOWNGRADE_MAP with more Google models — v1.4 follow-up.
- Per-request override header to disable downgrade — Phase 14 deferred.
- Downgrading non-generation methods — not a meaningful cost win.

## Claude's Discretion (Not Asked)

- Logging: kept the existing `[BurnLens] Downgraded …` line; no separate
  log line for URL rewrite (same logical event).
- Streaming compatibility: confirmed by inspection — `_is_streaming()` reads
  `:streamGenerateContent` from the path, which is preserved by the rewrite.
- Regex specifics for suffix stripping: `-(latest|\d{3,})$` — captured as
  decision detail, not asked.
