"""Convert token usage from API responses into USD cost."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from burnlens.cost.pricing import apply_tiered, get_model_pricing

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


def resolve_pricing(provider: str, model: str) -> dict | None:
    """Return the pricing entry for ``(provider, model)``, or ``None``.

    The single place that knows how to get from a wire-level (provider, model)
    pair to a pricing row: Cursor is routed to the underlying vendor, Bedrock's
    geo prefix is stripped, then the pricing table is consulted.

    ``calculate_cost`` and ``is_model_priced`` both go through here so a model
    can never be priced by one and unknown to the other.
    """
    if provider == "cursor":
        underlying = _cursor_underlying(model)
        if underlying is None:
            logger.warning(
                "Unknown Cursor model %r — cannot route to underlying pricing", model
            )
            return None
        return resolve_pricing(underlying[0], underlying[1])

    if provider == "bedrock":
        # Bedrock model IDs carry a geo prefix (us./eu./apac./global.) selecting
        # an inference profile; all geos bill at the global rate, so strip the
        # prefix before pricing. bedrock.json keys start at the `anthropic.`
        # vendor segment. Any leading `<segment>.` before it is stripped, so a
        # new geo prefix Just Works instead of silently costing $0.
        # ponytail: global-only billing; model per-geo (+~10%) rates if AWS diverges.
        model = re.sub(r"^[a-z0-9-]+\.(?=anthropic\.)", "", model)

    return get_model_pricing(provider, model)


def is_model_priced(provider: str, model: str) -> bool:
    """True when BurnLens can compute a real cost for ``(provider, model)``.

    A False here means every request for this model costs $0 as far as
    BurnLens is concerned, so no budget can ever be enforced against it.
    """
    return resolve_pricing(provider, model) is not None


PRICING_UNPRICED = "unpriced"
PRICING_CALCULATED = "calculated"
PRICING_ESTIMATED = "estimated"


def pricing_class_for(provider: str, model: str, source: str = "proxy") -> str:
    """Class recorded on the request at write time.

    ``unpriced`` — no table entry; ``cost_usd`` is a sentinel 0, not a measured
    zero. ``estimated`` — priced, but rebuilt from a coding-agent log (scan).
    ``calculated`` — priced from a live proxy response.

    Reconciled-against-the-bill is a later overlay (cloud Cost Confidence) and
    is never stored here.
    """
    if not is_model_priced(provider, model):
        return PRICING_UNPRICED
    if (source or "").startswith("scan_"):
        return PRICING_ESTIMATED
    return PRICING_CALCULATED


# Every (provider, model) that priced as $0 because we had no entry for it.
# Scans import silently at $0 otherwise — the claude-opus-5 gap cost real money
# before anyone noticed. The proxy has `_reject_unpriced`; this is the read side.
# ponytail: process-global set, fine for a CLI run. Thread it through the scan
# result objects if this ever needs to be per-scan.
_unpriced_seen: set[tuple[str, str]] = set()


def drain_unpriced_models() -> list[tuple[str, str]]:
    """Return and clear the (provider, model) pairs that costed as $0 unpriced."""
    seen = sorted(_unpriced_seen)
    _unpriced_seen.clear()
    return seen


def _includes_cache(provider: str) -> bool:
    """Whether ``provider`` reports input_tokens inclusive of the cached share.

    Imported lazily: burnlens.providers.base imports TokenUsage from this
    module, so a top-level import would be circular. An unregistered provider
    name (scan-only sources such as ``cursor``) is treated as disjoint, which
    is the conservative side — it bills the uncached input rather than
    silently dropping it.
    """
    from burnlens.providers.registry import inclusive_prompt_token_providers

    return provider in inclusive_prompt_token_providers()


def calculate_cost(provider: str, model: str, usage: TokenUsage) -> float:
    """Return total cost in USD for the given token usage.

    Returns 0.0 if model is not in the pricing DB (logs a warning, and records
    the pair for ``drain_unpriced_models``). Callers that need to distinguish
    "genuinely free" from "unknown to us" must ask ``is_model_priced`` — this
    return value cannot tell them apart.

    For ``provider='cursor'`` the model is routed to the underlying provider's
    pricing (Anthropic for Claude/Auto, OpenAI for GPT/o-series). Cursor is
    a coding-tool surface, not an LLM provider — its bills are pass-through.
    """
    pricing = resolve_pricing(provider, model)
    if pricing is None:
        _unpriced_seen.add((provider, model))
        return 0.0

    # Long-context tier keyed on total prompt size. Google/OpenAI report the
    # full prompt as input_tokens (cache is a subset), so input_tokens IS the
    # basis. ponytail: if an Anthropic-style tiered entry is ever added, its
    # cache tokens are DISJOINT from input_tokens — sum them in here first.
    pricing = apply_tiered(pricing, usage.input_tokens)

    per_million = 1_000_000.0

    # Base input cost. Audio tokens are always a subset of input_tokens. Cache
    # reads are a subset only for the providers that report an all-inclusive
    # prompt count (OpenAI, Google); Anthropic reports them separately, and
    # subtracting there under-bills the uncached input — invisibly, because the
    # result is still a plausible number. Claude Code hides this (input_tokens
    # is ~6 when everything is cached) but a partially-cached Anthropic request
    # with input=5000, cache_read=3000 would bill 2000 instead of 5000.
    # ponytail: if a token is both cached and audio the double-subtract under-counts
    # text slightly; max(0, …) floors it. Split by modality if that ever matters.
    cached_is_subset = usage.cache_read_tokens if _includes_cache(provider) else 0
    billable_input = max(
        0, usage.input_tokens - cached_is_subset - usage.audio_input_tokens
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
