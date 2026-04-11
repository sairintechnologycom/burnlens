"""Model recommendation engine — pure business logic for cost projections.

The DB-dependent analysis functions (analyse_model_fit) live in the local package.
This module provides the data types and projection functions shared by both.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ModelRecommendation:
    """A single recommendation to switch models or enable caching."""

    current_model: str
    suggested_model: str
    feature_tag: str
    request_count: int
    avg_output_tokens: float
    current_cost: float
    projected_cost: float
    projected_saving: float
    saving_pct: float
    confidence: str   # "high" | "medium" | "low"
    reason: str


# ---------------------------------------------------------------------------
# Model downgrade mapping
# ---------------------------------------------------------------------------

_CHEAPER_EQUIVALENT: dict[str, str] = {
    "gpt-4o": "gpt-4o-mini",
    "claude-3-5-sonnet": "claude-3-haiku",
    "gemini-1.5-pro": "gemini-1.5-flash",
}

_OVERKILL_MODELS = set(_CHEAPER_EQUIVALENT.keys())
_REASONING_MODELS = {"o1", "o3", "o1-mini"}

# Pricing used for cost projections (per million tokens)
_PROJECTION_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o":            {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":       {"input": 0.15,  "output": 0.60},
    "claude-3-5-sonnet":  {"input": 3.00,  "output": 15.00},
    "claude-3-haiku":     {"input": 0.25,  "output": 1.25},
    "gemini-1.5-pro":     {"input": 1.25,  "output": 5.00},
    "gemini-1.5-flash":   {"input": 0.075, "output": 0.30},
    "o1":                 {"input": 15.00, "output": 60.00},
    "o3":                 {"input": 10.00, "output": 40.00},
    "o1-mini":            {"input": 1.10,  "output": 4.40},
}


def get_projection_pricing(model: str) -> dict[str, float] | None:
    """Look up projection pricing for a model (exact or prefix match)."""
    if model in _PROJECTION_PRICING:
        return _PROJECTION_PRICING[model]
    for key in _PROJECTION_PRICING:
        if model.startswith(key):
            return _PROJECTION_PRICING[key]
    return None


def project_cost(
    request_count: int,
    avg_input_tokens: float,
    avg_output_tokens: float,
    model: str,
) -> float | None:
    """Project total cost for a model over the given request volume."""
    pricing = get_projection_pricing(model)
    if pricing is None:
        return None
    return (
        request_count * avg_input_tokens / 1_000_000 * pricing["input"]
        + request_count * avg_output_tokens / 1_000_000 * pricing["output"]
    )


def match_overkill_model(model: str) -> str | None:
    """Return the overkill key that matches ``model``, or None."""
    for key in _OVERKILL_MODELS:
        if model == key or model.startswith(key):
            return key
    return None


def match_reasoning_model(model: str) -> str | None:
    """Return the reasoning model key that matches, or None."""
    for key in _REASONING_MODELS:
        if model == key or model.startswith(key):
            return key
    return None


def cheaper_equivalent(model_key: str) -> str | None:
    """Return the cheaper model for a given overkill model key."""
    return _CHEAPER_EQUIVALENT.get(model_key)
