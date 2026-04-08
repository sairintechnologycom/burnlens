"""Tests for cost calculator and pricing lookup."""
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

    def test_unknown_model_returns_none(self):
        assert get_model_pricing("openai", "gpt-99-ultra") is None

    def test_unknown_provider_returns_none(self):
        assert get_model_pricing("fakeprovider", "gpt-4o") is None

    def test_anthropic_pricing(self):
        p = get_model_pricing("anthropic", "claude-3-5-sonnet-20241022")
        assert p is not None
        assert p["output_per_million"] == 15.00

    def test_google_pricing(self):
        p = get_model_pricing("google", "gemini-1.5-flash")
        assert p is not None


class TestCostCalculation:
    def test_basic_openai_cost(self):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = calculate_cost("openai", "gpt-4o", usage)
        # $2.50 input + $10.00 output = $12.50
        assert abs(cost - 12.50) < 0.001

    def test_zero_tokens(self):
        usage = TokenUsage()
        cost = calculate_cost("openai", "gpt-4o", usage)
        assert cost == 0.0

    def test_unknown_model_returns_zero(self):
        usage = TokenUsage(input_tokens=100, output_tokens=100)
        cost = calculate_cost("openai", "gpt-99-ultra", usage)
        assert cost == 0.0

    def test_cache_read_reduces_input_cost(self):
        # All input tokens are cached → billable_input = 0
        usage = TokenUsage(input_tokens=1000, output_tokens=0, cache_read_tokens=1000)
        cost = calculate_cost("openai", "gpt-4o", usage)
        # Only cache_read cost: 1000 * 1.25 / 1_000_000
        expected = 1000 * 1.25 / 1_000_000
        assert abs(cost - expected) < 1e-9

    def test_reasoning_tokens(self):
        usage = TokenUsage(input_tokens=0, output_tokens=0, reasoning_tokens=1_000_000)
        cost = calculate_cost("openai", "o1", usage)
        # reasoning at $60/M
        assert abs(cost - 60.0) < 0.001

    def test_anthropic_cache_write(self):
        usage = TokenUsage(cache_write_tokens=1_000_000)
        cost = calculate_cost("anthropic", "claude-3-5-sonnet-20241022", usage)
        # $3.75/M cache write
        assert abs(cost - 3.75) < 0.001


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
        assert u.output_tokens == 50
        assert u.reasoning_tokens == 10
        assert u.cache_read_tokens == 20

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

    def test_google_usage(self):
        body = {"usageMetadata": {"promptTokenCount": 150, "candidatesTokenCount": 60}}
        u = extract_usage_google(body)
        assert u.input_tokens == 150
        assert u.output_tokens == 60

    def test_missing_usage_field(self):
        u = extract_usage_openai({})
        assert u.input_tokens == 0
        assert u.output_tokens == 0
