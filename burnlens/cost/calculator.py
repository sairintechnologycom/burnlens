"""Convert token usage from API responses into USD cost."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from burnlens.cost.pricing import get_model_pricing

logger = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    """Token counts extracted from an API response."""

    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0      # OpenAI o-series
    cache_read_tokens: int = 0     # cached/prompt-cache-read tokens
    cache_write_tokens: int = 0    # Anthropic cache-write tokens


def calculate_cost(provider: str, model: str, usage: TokenUsage) -> float:
    """Return total cost in USD for the given token usage.

    Returns 0.0 if model is not in the pricing DB (logs a warning).
    """
    pricing = get_model_pricing(provider, model)
    if pricing is None:
        return 0.0

    per_million = 1_000_000.0

    # Base input cost (exclude cache-read tokens from regular input)
    billable_input = max(0, usage.input_tokens - usage.cache_read_tokens)
    input_cost = billable_input * pricing.get("input_per_million", 0.0) / per_million

    # Output cost (reasoning tokens billed at output rate unless separate entry)
    output_cost = usage.output_tokens * pricing.get("output_per_million", 0.0) / per_million

    # Reasoning tokens — use dedicated rate if present, else output rate
    reasoning_rate = pricing.get("reasoning_per_million", pricing.get("output_per_million", 0.0))
    reasoning_cost = usage.reasoning_tokens * reasoning_rate / per_million

    # Cache costs
    cache_read_cost = (
        usage.cache_read_tokens * pricing.get("cache_read_per_million", 0.0) / per_million
    )
    cache_write_cost = (
        usage.cache_write_tokens * pricing.get("cache_write_per_million", 0.0) / per_million
    )

    total = input_cost + output_cost + reasoning_cost + cache_read_cost + cache_write_cost
    logger.debug(
        "Cost for %s/%s: $%.6f  (in=%d out=%d reason=%d cache_r=%d cache_w=%d)",
        provider,
        model,
        total,
        usage.input_tokens,
        usage.output_tokens,
        usage.reasoning_tokens,
        usage.cache_read_tokens,
        usage.cache_write_tokens,
    )
    return total


def extract_usage_openai(response_json: dict) -> TokenUsage:
    """Extract token counts from an OpenAI-format response body."""
    u = response_json.get("usage") or {}
    details = u.get("completion_tokens_details") or {}
    prompt_details = u.get("prompt_tokens_details") or {}
    return TokenUsage(
        input_tokens=u.get("prompt_tokens", 0),
        output_tokens=u.get("completion_tokens", 0),
        reasoning_tokens=details.get("reasoning_tokens", 0),
        cache_read_tokens=prompt_details.get("cached_tokens", 0),
    )


def extract_usage_anthropic(response_json: dict) -> TokenUsage:
    """Extract token counts from an Anthropic-format response body."""
    u = response_json.get("usage") or {}
    return TokenUsage(
        input_tokens=u.get("input_tokens", 0),
        output_tokens=u.get("output_tokens", 0),
        cache_read_tokens=u.get("cache_read_input_tokens", 0),
        cache_write_tokens=u.get("cache_creation_input_tokens", 0),
    )


def extract_usage_google(response_json: dict) -> TokenUsage:
    """Extract token counts from a Google Gemini-format response body."""
    meta = response_json.get("usageMetadata") or {}
    return TokenUsage(
        input_tokens=meta.get("promptTokenCount", 0),
        output_tokens=meta.get("candidatesTokenCount", 0),
    )
