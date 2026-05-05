"""Budget-aware model downgrade map for BurnLens proxy routing."""
from __future__ import annotations

DOWNGRADE_MAP: dict[str, str] = {
    # OpenAI
    "gpt-4o":                     "gpt-4o-mini",
    "gpt-4-turbo":                "gpt-4o-mini",
    "o1":                         "gpt-4o-mini",
    "o3":                         "gpt-4o-mini",
    "o1-mini":                    "gpt-4o-mini",
    # Anthropic
    "claude-opus-4-6":            "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6":          "claude-haiku-4-5-20251001",
    "claude-3-5-sonnet-20241022": "claude-haiku-4-5-20251001",
    # Google
    "gemini-1.5-pro":             "gemini-1.5-flash",
    "gemini-2.0-pro":             "gemini-1.5-flash",
}


def get_downgrade_model(model: str) -> str | None:
    """Return cheaper alternative model, or None if already cheapest / not mapped."""
    return DOWNGRADE_MAP.get(model)
