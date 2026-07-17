"""Budget-aware model downgrade map for BurnLens proxy routing."""
from __future__ import annotations

import re

DOWNGRADE_MAP: dict[str, str] = {
    # OpenAI
    "gpt-4o":                     "gpt-4o-mini",
    "gpt-4-turbo":                "gpt-4o-mini",
    "o1":                         "gpt-4o-mini",
    "o3":                         "gpt-4o-mini",
    "o1-mini":                    "gpt-4o-mini",
    "gpt-5.2":                    "gpt-5-mini",
    "gpt-5.2-pro":                "gpt-5-mini",
    "gpt-5.6":                    "gpt-5.6-terra",
    "gpt-5.6-sol":                "gpt-5.6-terra",
    "gpt-5.6-terra":              "gpt-5.6-luna",
    # Anthropic
    "claude-opus-4-6":            "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6":          "claude-haiku-4-5-20251001",
    "claude-3-5-sonnet-20241022": "claude-haiku-4-5-20251001",
    "claude-sonnet-5":            "claude-haiku-4-5",
    # Google
    "gemini-1.5-pro":             "gemini-1.5-flash",
    "gemini-2.0-pro":             "gemini-1.5-flash",
    "gemini-3.1-pro-preview":     "gemini-3.1-flash-lite",
}

# Strip trailing version/alias suffixes: -latest, -001, -002, or any -NNN
# (3+ digits). Used for DOWNGRADE_MAP lookup fallback. Linear regex —
# no ReDoS risk on str input.
_SUFFIX_RE = re.compile(r"-(latest|\d{3,})$")


def get_downgrade_model(model: str) -> str | None:
    """Return cheaper alternative model, or None if already cheapest / not mapped.

    Tries exact match first; on miss, strips a trailing -latest / -NNN
    suffix and retries (per phase 17 CONTEXT decision #2). The returned
    value is always the bare downgrade target from DOWNGRADE_MAP
    (e.g. ``gemini-1.5-flash``, never ``gemini-1.5-flash-latest``).
    """
    exact = DOWNGRADE_MAP.get(model)
    if exact is not None:
        return exact
    stripped = _SUFFIX_RE.sub("", model)
    if stripped != model:
        return DOWNGRADE_MAP.get(stripped)
    return None
