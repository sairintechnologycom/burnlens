"""Convert token usage from API responses into USD cost."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

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
    audio_input_tokens: int = 0    # audio-modality input tokens (subset of input_tokens, billed at audio rate)
    audio_output_tokens: int = 0   # audio-modality output tokens (subset of output_tokens)
    # Non-token line items: {unit_name: count}, priced flat via pricing["unit_prices"]
    # (e.g. {"web_search_calls": 3}, {"images": 2}, {"audio_seconds": 30}).
    units: dict[str, float] = field(default_factory=dict)


# Current Sonnet model used to estimate cost for Cursor's 'Auto' mode, which
# hides the underlying model from the user. Anthropic Sonnet pricing has held
# flat across point releases, so the exact dated id matters less than the
# tier — picking the latest dated 4-x sonnet keeps the estimate honest.
_CURSOR_AUTO_UNDERLYING = "claude-sonnet-4-6"


def _cursor_underlying(model: str) -> tuple[str, str] | None:
    """Map a Cursor-reported model name to (provider, underlying_model).

    Returns ``None`` if the model can't be mapped. Cursor's 'Auto' mode is
    relabeled by the scanner as ``cursor-auto-sonnet-est`` upstream of this
    function — we just route it to the current Sonnet pricing entry.
    """
    if model == "cursor-auto-sonnet-est":
        return ("anthropic", _CURSOR_AUTO_UNDERLYING)
    if model.startswith("claude"):
        return ("anthropic", model)
    if model.startswith(("gpt", "o1", "o3", "o4")):
        return ("openai", model)
    return None


def calculate_cost(provider: str, model: str, usage: TokenUsage) -> float:
    """Return total cost in USD for the given token usage.

    Returns 0.0 if model is not in the pricing DB (logs a warning).

    For ``provider='cursor'`` the model is routed to the underlying provider's
    pricing (Anthropic for Claude/Auto, OpenAI for GPT/o-series). Cursor is
    a coding-tool surface, not an LLM provider — its bills are pass-through.
    """
    if provider == "cursor":
        underlying = _cursor_underlying(model)
        if underlying is None:
            logger.warning(
                "Unknown Cursor model %r — cannot route to underlying pricing", model
            )
            return 0.0
        return calculate_cost(underlying[0], underlying[1], usage)

    if provider == "bedrock":
        # Bedrock model IDs carry a geo prefix (us./eu./apac./global.) selecting
        # an inference profile; all geos bill at the global rate, so strip the
        # prefix before pricing. bedrock.json keys start at the `anthropic.`
        # vendor segment. Any leading `<segment>.` before it is stripped, so a
        # new geo prefix Just Works instead of silently costing $0.
        # ponytail: global-only billing; model per-geo (+~10%) rates if AWS diverges.
        model = re.sub(r"^[a-z0-9-]+\.(?=anthropic\.)", "", model)

    pricing = get_model_pricing(provider, model)
    if pricing is None:
        return 0.0

    per_million = 1_000_000.0

    # Base input cost — cache-read and audio tokens are subsets of input_tokens
    # billed at their own rates, so exclude both from the text-input count.
    # ponytail: if a token is both cached and audio the double-subtract under-counts
    # text slightly; max(0, …) floors it. Split by modality if that ever matters.
    billable_input = max(
        0, usage.input_tokens - usage.cache_read_tokens - usage.audio_input_tokens
    )
    input_cost = billable_input * pricing.get("input_per_million", 0.0) / per_million

    # Text output cost (audio-output tokens billed separately below)
    billable_output = max(0, usage.output_tokens - usage.audio_output_tokens)
    output_cost = billable_output * pricing.get("output_per_million", 0.0) / per_million

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

    # Audio-modality tokens billed at their own per-million rate (fall back to
    # the text rate when a model has no separate audio rate).
    audio_input_cost = (
        usage.audio_input_tokens
        * pricing.get("audio_input_per_million", pricing.get("input_per_million", 0.0))
        / per_million
    )
    audio_output_cost = (
        usage.audio_output_tokens
        * pricing.get("audio_output_per_million", pricing.get("output_per_million", 0.0))
        / per_million
    )

    # Non-token line items — flat per-unit fees (per request, per image, per
    # tool call, per audio-second, …). Prices are USD-per-unit, not per-million.
    unit_prices = pricing.get("unit_prices", {})
    units_cost = sum(count * unit_prices.get(name, 0.0) for name, count in usage.units.items())

    total = (
        input_cost + output_cost + reasoning_cost + cache_read_cost + cache_write_cost
        + audio_input_cost + audio_output_cost + units_cost
    )
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
    reasoning = details.get("reasoning_tokens", 0)
    # OpenAI's completion_tokens INCLUDES reasoning tokens; the rest of the
    # codebase treats output_tokens and reasoning_tokens as disjoint (they sum
    # to total). Subtract so reasoning isn't billed twice — once via output,
    # once via reasoning_cost.
    return TokenUsage(
        input_tokens=u.get("prompt_tokens", 0),
        output_tokens=max(0, u.get("completion_tokens", 0) - reasoning),
        reasoning_tokens=reasoning,
        cache_read_tokens=prompt_details.get("cached_tokens", 0),
        audio_input_tokens=prompt_details.get("audio_tokens", 0),
        audio_output_tokens=details.get("audio_tokens", 0),
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
