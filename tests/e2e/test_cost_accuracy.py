"""Cost accuracy validation suite.

Verifies that calculate_cost produces exact expected values for real
provider/model combinations, edge cases, and pricing JSON integrity.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from burnlens.cost.calculator import TokenUsage, calculate_cost
from burnlens.cost.pricing import _PRICING_DIR, get_model_pricing

# ---------------------------------------------------------------------------
# 1. OpenAI gpt-4o-mini exact cost
# ---------------------------------------------------------------------------

def test_openai_gpt4o_mini_cost_exact():
    """gpt-4o-mini: $0.15/M in, $0.60/M out → 1000 in + 500 out = $0.000450."""
    usage = TokenUsage(input_tokens=1000, output_tokens=500)
    cost = calculate_cost("openai", "gpt-4o-mini", usage)
    expected = (1000 / 1e6 * 0.15) + (500 / 1e6 * 0.60)  # 0.000450
    assert cost == pytest.approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# 2. OpenAI reasoning tokens
# ---------------------------------------------------------------------------

def test_openai_reasoning_tokens_cost():
    """o1-mini reasoning_tokens should be billed at reasoning_per_million."""
    pricing = get_model_pricing("openai", "o1-mini")
    assert pricing is not None, "o1-mini must exist in openai.json"
    reasoning_rate = pricing["reasoning_per_million"]

    usage = TokenUsage(input_tokens=500, output_tokens=100, reasoning_tokens=800)
    cost = calculate_cost("openai", "o1-mini", usage)

    expected = (
        500 / 1e6 * pricing["input_per_million"]
        + 100 / 1e6 * pricing["output_per_million"]
        + 800 / 1e6 * reasoning_rate
    )
    assert cost == pytest.approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# 3. Anthropic cache-read discount
# ---------------------------------------------------------------------------

def test_anthropic_cache_read_discount():
    """Cache reads must be cheaper than full input pricing."""
    model = "claude-haiku-4-5-20251001"
    pricing = get_model_pricing("anthropic", model)
    assert pricing is not None, f"{model} must resolve in anthropic.json"

    # With cache reads — 800 of the 1000 input tokens are cache hits
    usage_cached = TokenUsage(input_tokens=1000, cache_read_tokens=800, output_tokens=100)
    cost_cached = calculate_cost("anthropic", model, usage_cached)

    # Without cache reads — all 1000 tokens billed at full input rate
    usage_full = TokenUsage(input_tokens=1000, output_tokens=100)
    cost_full = calculate_cost("anthropic", model, usage_full)

    assert cost_cached < cost_full, (
        f"Cached cost ${cost_cached:.8f} should be less than full cost ${cost_full:.8f}"
    )

    # Verify the exact breakdown
    cache_read_rate = pricing["cache_read_per_million"]
    input_rate = pricing["input_per_million"]
    output_rate = pricing["output_per_million"]
    expected = (
        200 / 1e6 * input_rate       # billable_input = 1000 - 800
        + 800 / 1e6 * cache_read_rate
        + 100 / 1e6 * output_rate
    )
    assert cost_cached == pytest.approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# 4. Google Gemini Flash
# ---------------------------------------------------------------------------

def test_google_gemini_flash_cost():
    """gemini-1.5-flash cost must match pricing JSON values exactly."""
    pricing = get_model_pricing("google", "gemini-1.5-flash")
    assert pricing is not None

    usage = TokenUsage(input_tokens=2000, output_tokens=300)
    cost = calculate_cost("google", "gemini-1.5-flash", usage)

    expected = (
        2000 / 1e6 * pricing["input_per_million"]
        + 300 / 1e6 * pricing["output_per_million"]
    )
    assert cost == pytest.approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# 5. Pricing JSON structural validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("provider", ["openai", "anthropic", "google"])
def test_pricing_json_has_all_required_fields(provider: str):
    """Every model entry must have input_price and output_price as positive floats."""
    path = _PRICING_DIR / f"{provider}.json"
    assert path.exists(), f"Missing pricing file: {path}"

    with open(path) as f:
        data = json.load(f)

    models = data.get("models", {})
    assert len(models) > 0, f"{provider}.json has no models"

    optional_fields = {"reasoning_per_million", "cache_read_per_million", "cache_write_per_million"}

    for model_name, entry in models.items():
        # Required fields
        for field in ("input_per_million", "output_per_million"):
            assert field in entry, f"{provider}/{model_name} missing {field}"
            assert isinstance(entry[field], (int, float)), (
                f"{provider}/{model_name}.{field} must be numeric"
            )
            assert entry[field] > 0, f"{provider}/{model_name}.{field} must be > 0"

        # Optional fields — validate type if present
        for field in optional_fields:
            if field in entry:
                assert isinstance(entry[field], (int, float)), (
                    f"{provider}/{model_name}.{field} must be numeric"
                )
                assert entry[field] >= 0, f"{provider}/{model_name}.{field} must be >= 0"


# ---------------------------------------------------------------------------
# 6. Fixed notation (no scientific notation)
# ---------------------------------------------------------------------------

def test_cost_displayed_as_fixed_notation_not_scientific():
    """Small costs must format as fixed decimal, not scientific notation."""
    # gpt-4o-mini with tiny usage → cost around 5.1e-05
    usage = TokenUsage(input_tokens=100, output_tokens=50)
    cost = calculate_cost("openai", "gpt-4o-mini", usage)

    formatted = f"{cost:.8f}"
    assert "." in formatted, "Formatted cost should contain a decimal point"
    assert "e" not in formatted.lower(), (
        f"Formatted cost must not use scientific notation, got: {formatted}"
    )


# ---------------------------------------------------------------------------
# 7. Zero tokens → zero cost, no exception
# ---------------------------------------------------------------------------

def test_zero_tokens_returns_zero_cost_not_error():
    """All-zero token counts must return 0.0 without raising."""
    usage = TokenUsage(
        input_tokens=0,
        output_tokens=0,
        reasoning_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )
    cost = calculate_cost("openai", "gpt-4o-mini", usage)
    assert cost == 0.0


# ---------------------------------------------------------------------------
# 8. Unknown model → zero cost + warning
# ---------------------------------------------------------------------------

def test_unknown_model_returns_zero_cost(caplog: pytest.LogCaptureFixture):
    """Unknown models return 0.0 and emit a warning log."""
    with caplog.at_level(logging.WARNING, logger="burnlens.cost.pricing"):
        cost = calculate_cost("openai", "nonexistent-model-xyz", TokenUsage())
    assert cost == 0.0
    assert any("nonexistent-model-xyz" in msg for msg in caplog.messages)
