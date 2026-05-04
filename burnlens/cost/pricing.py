"""Load and look up model pricing from bundled JSON files."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PRICING_DIR = Path(__file__).parent / "pricing_data"

# provider name → {model_name → pricing dict}
_PRICING_CACHE: dict[str, dict[str, dict[str, Any]]] = {}


def _load_provider(provider: str) -> dict[str, dict[str, Any]]:
    """Load and cache pricing for a provider from its JSON file."""
    if provider not in _PRICING_CACHE:
        path = _PRICING_DIR / f"{provider}.json"
        if not path.exists():
            logger.warning("No pricing file for provider %r", provider)
            _PRICING_CACHE[provider] = {}
        else:
            with open(path) as f:
                data = json.load(f)
            _PRICING_CACHE[provider] = data.get("models", {})
    return _PRICING_CACHE[provider]


def get_model_pricing(provider: str, model: str) -> dict[str, Any] | None:
    """Return pricing dict for a model, or None if not found.

    Tries exact match first, then prefix match to handle versioned model IDs
    (e.g. ``gpt-4o-2024-11-20`` matches ``gpt-4o``).
    """
    models = _load_provider(provider)
    if not models:
        return None

    # Exact match
    if model in models:
        return models[model]

    # Prefix match — longest matching prefix wins
    best: str | None = None
    for known in models:
        if model.startswith(known):
            if best is None or len(known) > len(best):
                best = known

    if best:
        logger.debug("Model %r matched pricing entry %r (prefix)", model, best)
        return models[best]

    logger.warning("No pricing found for provider=%r model=%r — cost will be $0", provider, model)
    return None


def get_pricing(pricing_key: str, model_name: str) -> dict[str, Any] | None:
    """Look up pricing by pricing_key (Provider.config.pricing_key) and model name.

    Thin alias for get_model_pricing — the pricing_key corresponds to the
    JSON file name in pricing_data/ and is the same as the provider name for
    the three built-in providers.  New providers (e.g. azure-openai) can use
    a distinct pricing_key that maps to their own pricing_data/{key}.json.
    """
    return get_model_pricing(pricing_key, model_name)
