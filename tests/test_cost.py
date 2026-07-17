"""Tests for cost calculation, pricing lookup, and usage extraction."""
from __future__ import annotations

import pytest

from burnlens.cost.calculator import (
    TokenUsage,
    calculate_cost,
    extract_usage_anthropic,
    extract_usage_google,
    extract_usage_openai,
)
from burnlens.cost.pricing import get_model_pricing


# ---------------------------------------------------------------------------
# Pricing lookup
# ---------------------------------------------------------------------------


class TestPricingLookup:
    def test_exact_match(self):
        p = get_model_pricing("openai", "gpt-4o")
        assert p is not None
        assert p["input_per_million"] == 2.50

    def test_prefix_match(self):
        # versioned model IDs should match base entry
        p = get_model_pricing("openai", "gpt-4o-2024-11-20")
        assert p is not None
        assert p["input_per_million"] == 2.50

    def test_prefix_match_longest_wins(self):
        # "gpt-4o-mini-2024-07-18" should match "gpt-4o-mini" (more specific), not "gpt-4o"
        p = get_model_pricing("openai", "gpt-4o-mini-2024-07-18")
        assert p is not None
        assert p["input_per_million"] == 0.15  # gpt-4o-mini rate, not gpt-4o's 2.50

    def test_unknown_model_returns_none(self):
        assert get_model_pricing("openai", "gpt-99-ultra") is None

    def test_unknown_provider_returns_none(self):
        assert get_model_pricing("fakeprovider", "gpt-4o") is None

    def test_anthropic_pricing(self):
        p = get_model_pricing("anthropic", "claude-3-5-sonnet-20241022")
        assert p is not None
        assert p["output_per_million"] == 15.00
        assert p["cache_write_per_million"] == 3.75

    def test_anthropic_prefix_match(self):
        p = get_model_pricing("anthropic", "claude-3-5-sonnet-20241022-extra")
        assert p is not None
        assert p["input_per_million"] == 3.00

    def test_google_pricing(self):
        p = get_model_pricing("google", "gemini-1.5-flash")
        assert p is not None
        assert p["output_per_million"] == 0.30

    def test_google_prefix_match_versioned(self):
        # "gemini-1.5-pro-002" → "gemini-1.5-pro"
        p = get_model_pricing("google", "gemini-1.5-pro-002")
        assert p is not None
        assert p["input_per_million"] == 1.25

    def test_o1_has_reasoning_rate(self):
        p = get_model_pricing("openai", "o1")
        assert p is not None
        assert "reasoning_per_million" in p
        assert p["reasoning_per_million"] == 60.0

    def test_o3_has_reasoning_rate(self):
        p = get_model_pricing("openai", "o3")
        assert p is not None
        assert p["reasoning_per_million"] == 8.0

    def test_anthropic_opus_exists(self):
        p = get_model_pricing("anthropic", "claude-3-opus-20240229")
        assert p is not None
        assert p["input_per_million"] == 15.0

    def test_gemini_25_pro_exists(self):
        p = get_model_pricing("google", "gemini-2.5-pro")
        assert p is not None
        assert p["output_per_million"] == 10.0

    def test_unknown_model_anthropic_returns_none(self):
        assert get_model_pricing("anthropic", "claude-99-super") is None

    def test_unknown_model_google_returns_none(self):
        assert get_model_pricing("google", "gemini-99-ultra") is None


# ---------------------------------------------------------------------------
# calculate_cost
# ---------------------------------------------------------------------------


class TestCostCalculation:
    @pytest.mark.parametrize(
        ("provider", "model", "expected"),
        [
            ("openai", "gpt-5.2", 15.75),
            ("openai", "gpt-5.2-pro", 189.00),
            ("openai", "gpt-5.4", 17.50),
            ("openai", "gpt-5.4-pro", 210.00),
            ("openai", "gpt-5.4-mini", 5.25),
            ("openai", "gpt-5.4-nano", 1.45),
            ("openai", "gpt-5.5", 35.00),
            ("openai", "gpt-5.5-pro", 210.00),
            ("openai", "gpt-5.6", 35.00),
            ("openai", "gpt-5.6-sol", 35.00),
            ("openai", "gpt-5.6-terra", 17.50),
            ("openai", "gpt-5.6-luna", 7.00),
            ("anthropic", "claude-sonnet-5", 12.00),
            ("anthropic", "claude-mythos-5", 60.00),
            ("google", "gemini-3.1-flash-lite", 1.75),
            ("google", "gemini-3.5-flash", 10.50),
            ("groq", "openai/gpt-oss-20b", 0.375),
            ("mistral", "mistral-large-2512", 2.00),
            ("mistral", "mistral-medium-3-5", 9.00),
            ("mistral", "mistral-small-2603", 0.75),
            ("mistral", "mistral-large-latest", 2.00),
            ("mistral", "mistral-medium-latest", 9.00),
            ("mistral", "mistral-small-latest", 0.75),
            ("together", "openai/gpt-oss-120b", 0.75),
            ("together", "meta-llama/Llama-3.3-70B-Instruct-Turbo", 2.08),
            ("together", "thinkingmachines/Inkling", 5.05),
            ("together", "MiniMaxAI/MiniMax-M3", 1.50),
            ("together", "MiniMaxAI/MiniMax-M2.7", 1.50),
            ("together", "Qwen/Qwen3.7-Max", 5.00),
            ("together", "Qwen/Qwen3.6-Plus", 3.50),
            ("together", "Qwen/Qwen3.5-9B", 0.42),
            ("together", "moonshotai/Kimi-K2.7-Code", 4.95),
            ("together", "moonshotai/Kimi-K2.6", 5.70),
            ("together", "zai-org/GLM-5.2", 5.80),
            ("together", "deepseek-ai/DeepSeek-V4-Pro", 5.22),
            ("together", "nvidia/nemotron-3-ultra-550b-a55b", 4.20),
            ("together", "Qwen/Qwen2.5-7B-Instruct-Turbo", 0.60),
            ("together", "google/gemma-4-31B-it", 1.36),
            ("together", "pearl-ai/gemma-4-31b-it", 1.14),
            ("together", "deepcogito/cogito-v2-1-671b", 2.50),
            ("together", "Qwen/Qwen3.7-Plus", 1.60),
            ("together", "google/gemma-3n-E4B-it", 0.18),
            ("together", "LiquidAI/LFM2.5-8B-A1B", 0.15),
        ],
    )
    def test_refreshed_model_costs(self, provider: str, model: str, expected: float):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        assert calculate_cost(provider, model, usage) == pytest.approx(expected)

    def test_basic_openai_cost(self):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = calculate_cost("openai", "gpt-4o", usage)
        # $2.50 input + $10.00 output = $12.50
        assert abs(cost - 12.50) < 1e-6

    def test_zero_tokens(self):
        usage = TokenUsage()
        cost = calculate_cost("openai", "gpt-4o", usage)
        assert cost == 0.0

    def test_unknown_model_returns_zero(self):
        usage = TokenUsage(input_tokens=100, output_tokens=100)
        cost = calculate_cost("openai", "gpt-99-ultra", usage)
        assert cost == 0.0

    def test_unknown_provider_returns_zero(self):
        usage = TokenUsage(input_tokens=1000, output_tokens=500)
        assert calculate_cost("bogusprovider", "gpt-4o", usage) == 0.0

    def test_cache_read_reduces_input_cost(self):
        # All input tokens are cached → billable_input = 0
        usage = TokenUsage(input_tokens=1000, output_tokens=0, cache_read_tokens=1000)
        cost = calculate_cost("openai", "gpt-4o", usage)
        # Only cache_read cost: 1000 * 1.25 / 1_000_000
        expected = 1000 * 1.25 / 1_000_000
        assert abs(cost - expected) < 1e-9

    def test_cache_read_exceeds_input_clamps_billable_to_zero(self):
        # billable_input = max(0, 100 - 500) = 0, cache_read still charged
        usage = TokenUsage(input_tokens=100, cache_read_tokens=500)
        cost = calculate_cost("openai", "gpt-4o", usage)
        expected = 500 * 1.25 / 1_000_000
        assert abs(cost - expected) < 1e-9

    def test_reasoning_tokens(self):
        usage = TokenUsage(input_tokens=0, output_tokens=0, reasoning_tokens=1_000_000)
        cost = calculate_cost("openai", "o1", usage)
        # reasoning at $60/M
        assert abs(cost - 60.0) < 1e-4

    def test_reasoning_tokens_o3_dedicated_rate(self):
        # o3: reasoning=$8/M
        usage = TokenUsage(reasoning_tokens=1_000_000)
        cost = calculate_cost("openai", "o3", usage)
        assert abs(cost - 8.0) < 1e-4

    def test_reasoning_tokens_fall_back_to_output_rate(self):
        # gpt-4o has no reasoning_per_million — falls back to output_per_million=$10/M
        usage = TokenUsage(reasoning_tokens=1_000_000)
        cost = calculate_cost("openai", "gpt-4o", usage)
        assert abs(cost - 10.0) < 1e-4

    def test_anthropic_cache_write(self):
        usage = TokenUsage(cache_write_tokens=1_000_000)
        cost = calculate_cost("anthropic", "claude-3-5-sonnet-20241022", usage)
        # $3.75/M cache write
        assert abs(cost - 3.75) < 1e-4

    def test_anthropic_cache_read(self):
        # claude-3-5-sonnet: cache_read=$0.30/M
        # 1000 input with 800 cache_read
        # billable_input = 1000 - 800 = 200
        # input_cost = 200 * 3.00/1e6 = 0.0006
        # cache_read_cost = 800 * 0.30/1e6 = 0.00024
        usage = TokenUsage(input_tokens=1000, cache_read_tokens=800)
        cost = calculate_cost("anthropic", "claude-3-5-sonnet-20241022", usage)
        expected = 200 * 3.00 / 1e6 + 800 * 0.30 / 1e6
        assert abs(cost - expected) < 1e-9

    def test_gpt4o_mini_cheap_tier(self):
        # gpt-4o-mini: input=$0.15/M, output=$0.60/M
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = calculate_cost("openai", "gpt-4o-mini", usage)
        assert abs(cost - (0.15 + 0.60)) < 1e-6

    def test_gpt4_turbo_pricing(self):
        # gpt-4-turbo: input=$10/M, output=$30/M
        usage = TokenUsage(input_tokens=100, output_tokens=100)
        cost = calculate_cost("openai", "gpt-4-turbo", usage)
        expected = 100 * 10 / 1e6 + 100 * 30 / 1e6
        assert abs(cost - expected) < 1e-9

    def test_anthropic_opus_pricing(self):
        # claude-3-opus: input=$15/M, output=$75/M
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=0)
        cost = calculate_cost("anthropic", "claude-3-opus-20240229", usage)
        assert abs(cost - 15.0) < 1e-6

    def test_anthropic_haiku_pricing(self):
        # claude-3-5-haiku: input=$0.80/M, output=$4/M
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = calculate_cost("anthropic", "claude-3-5-haiku-20241022", usage)
        assert abs(cost - (0.80 + 4.00)) < 1e-6

    def test_google_flash_basic(self):
        # gemini-2.0-flash: input=$0.10/M, output=$0.40/M
        usage = TokenUsage(input_tokens=1000, output_tokens=500)
        cost = calculate_cost("google", "gemini-2.0-flash", usage)
        expected = 1000 * 0.10 / 1e6 + 500 * 0.40 / 1e6
        assert abs(cost - expected) < 1e-9

    def test_google_pro_pricing(self):
        # gemini-2.5-pro: input=$1.25/M, output=$10/M
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=0)
        cost = calculate_cost("google", "gemini-2.5-pro", usage)
        assert abs(cost - 1.25) < 1e-6

    def test_google_prefix_match_cost(self):
        # "gemini-1.5-pro-002" → "gemini-1.5-pro" ($1.25/M input)
        usage = TokenUsage(input_tokens=1_000_000)
        cost = calculate_cost("google", "gemini-1.5-pro-002", usage)
        assert abs(cost - 1.25) < 1e-6

    def test_o1_full_combined(self):
        # o1: input=$15/M, output=$60/M, cache_read=$7.50/M, reasoning=$60/M
        # 1000 input, 500 output, 200 reasoning, 400 cache_read
        # billable_input = 1000 - 400 = 600
        # input_cost = 600*15/1e6 = 0.009
        # output_cost = 500*60/1e6 = 0.03
        # reasoning_cost = 200*60/1e6 = 0.012
        # cache_read_cost = 400*7.50/1e6 = 0.003
        # total = 0.054
        usage = TokenUsage(
            input_tokens=1000, output_tokens=500,
            reasoning_tokens=200, cache_read_tokens=400,
        )
        cost = calculate_cost("openai", "o1", usage)
        expected = 600 * 15 / 1e6 + 500 * 60 / 1e6 + 200 * 60 / 1e6 + 400 * 7.50 / 1e6
        assert abs(cost - expected) < 1e-9

    def test_gpt35_turbo_pricing(self):
        # gpt-3.5-turbo: input=$0.50/M, output=$1.50/M
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = calculate_cost("openai", "gpt-3.5-turbo", usage)
        assert abs(cost - (0.50 + 1.50)) < 1e-6

    # -- non-token line items ------------------------------------------------

    def test_audio_tokens_billed_at_audio_rate(self):
        # gpt-4o-audio-preview: text in/out $2.50/$10, audio in/out $40/$80.
        # input_tokens counts INCLUDE the audio subset, so audio is repriced,
        # not added on top: 1M input (0.5M audio) + 1M output (0.5M audio).
        usage = TokenUsage(
            input_tokens=1_000_000, output_tokens=1_000_000,
            audio_input_tokens=500_000, audio_output_tokens=500_000,
        )
        cost = calculate_cost("openai", "gpt-4o-audio-preview", usage)
        expected = (
            500_000 * 2.50 / 1e6 + 500_000 * 10.00 / 1e6   # text half
            + 500_000 * 40.00 / 1e6 + 500_000 * 80.00 / 1e6  # audio half
        )
        assert cost == pytest.approx(expected)

    def test_audio_tokens_fall_back_to_text_rate(self):
        # A model with no audio rate must not regress: audio tokens bill at the
        # text rate (same total as before this feature existed).
        usage = TokenUsage(input_tokens=1_000_000, audio_input_tokens=400_000)
        cost = calculate_cost("openai", "gpt-4o", usage)
        assert cost == pytest.approx(1_000_000 * 2.50 / 1e6)

    def test_flat_unit_line_items(self):
        # unit_prices are USD-per-unit flat fees, summed as extra line items.
        from burnlens.cost.pricing import _PRICING_CACHE
        _PRICING_CACHE["_test_units"] = {
            "m": {"input_per_million": 1.0, "unit_prices": {"web_search_calls": 0.01}}
        }
        usage = TokenUsage(input_tokens=1_000_000, units={"web_search_calls": 3})
        cost = calculate_cost("_test_units", "m", usage)
        assert cost == pytest.approx(1.0 + 3 * 0.01)
        del _PRICING_CACHE["_test_units"]

    def test_reasoning_not_double_billed_from_response(self):
        # completion_tokens=1000 already includes reasoning_tokens=200.
        # Correct o1 cost = 1000 * $60/M (reasoning billed at output rate,
        # once), NOT 1200 * $60/M.
        body = {"usage": {
            "prompt_tokens": 0, "completion_tokens": 1000,
            "completion_tokens_details": {"reasoning_tokens": 200},
        }}
        u = extract_usage_openai(body)
        assert u.output_tokens == 800 and u.reasoning_tokens == 200
        cost = calculate_cost("openai", "o1", u)
        assert cost == pytest.approx(1000 * 60.0 / 1e6)

    def test_openai_extracts_audio_tokens(self):
        body = {"usage": {
            "prompt_tokens": 100, "completion_tokens": 50,
            "prompt_tokens_details": {"audio_tokens": 40, "cached_tokens": 10},
            "completion_tokens_details": {"audio_tokens": 30},
        }}
        u = extract_usage_openai(body)
        assert u.audio_input_tokens == 40
        assert u.audio_output_tokens == 30


# ---------------------------------------------------------------------------
# Usage extraction — OpenAI
# ---------------------------------------------------------------------------


class TestUsageExtraction:
    def test_openai_non_streaming(self):
        body = {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "completion_tokens_details": {"reasoning_tokens": 10},
                "prompt_tokens_details": {"cached_tokens": 20},
            }
        }
        u = extract_usage_openai(body)
        assert u.input_tokens == 100
        # completion_tokens (50) includes the 10 reasoning tokens; extractor
        # keeps output disjoint from reasoning (50 - 10 = 40).
        assert u.output_tokens == 40
        assert u.reasoning_tokens == 10
        assert u.cache_read_tokens == 20

    def test_openai_missing_usage_field(self):
        u = extract_usage_openai({})
        assert u.input_tokens == 0
        assert u.output_tokens == 0

    def test_openai_null_usage(self):
        u = extract_usage_openai({"usage": None})
        assert u.input_tokens == 0

    def test_openai_empty_details(self):
        body = {
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "completion_tokens_details": {},
                "prompt_tokens_details": {},
            }
        }
        u = extract_usage_openai(body)
        assert u.reasoning_tokens == 0
        assert u.cache_read_tokens == 0

    def test_anthropic_usage(self):
        body = {
            "usage": {
                "input_tokens": 200,
                "output_tokens": 80,
                "cache_read_input_tokens": 30,
                "cache_creation_input_tokens": 10,
            }
        }
        u = extract_usage_anthropic(body)
        assert u.input_tokens == 200
        assert u.output_tokens == 80
        assert u.cache_read_tokens == 30
        assert u.cache_write_tokens == 10

    def test_anthropic_missing_usage(self):
        u = extract_usage_anthropic({})
        assert u.input_tokens == 0
        assert u.output_tokens == 0

    def test_anthropic_null_usage(self):
        u = extract_usage_anthropic({"usage": None})
        assert u.input_tokens == 0

    def test_anthropic_partial_cache(self):
        body = {"usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50}}
        u = extract_usage_anthropic(body)
        assert u.cache_read_tokens == 50
        assert u.cache_write_tokens == 0

    def test_google_usage(self):
        body = {"usageMetadata": {"promptTokenCount": 150, "candidatesTokenCount": 60}}
        u = extract_usage_google(body)
        assert u.input_tokens == 150
        assert u.output_tokens == 60

    def test_google_missing_usage_field(self):
        u = extract_usage_google({})
        assert u.input_tokens == 0
        assert u.output_tokens == 0

    def test_google_null_metadata(self):
        u = extract_usage_google({"usageMetadata": None})
        assert u.input_tokens == 0

    def test_google_zero_candidates(self):
        body = {"usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 0}}
        u = extract_usage_google(body)
        assert u.input_tokens == 100
        assert u.output_tokens == 0
