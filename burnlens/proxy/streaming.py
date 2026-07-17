"""SSE streaming: usage extraction from provider-specific streaming formats."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from burnlens.cost.calculator import TokenUsage

if TYPE_CHECKING:
    from burnlens.providers.base import Provider

# Strings that indicate a *complete* SSE event may contain usage data.
# Applied to whole events (after reassembly), not raw TCP chunks.
USAGE_EVENT_INDICATORS: tuple[str, ...] = (
    '"usage"',        # OpenAI final chunk + Anthropic message_delta
    "usageMetadata",  # Google SSE data lines
    "message_start",  # Anthropic: input tokens live in message.usage
    "message_delta",  # Anthropic: output tokens live in .usage
)

# Keep old name as alias for backwards compat (tests, external callers)
USAGE_CHUNK_INDICATORS = USAGE_EVENT_INDICATORS


def split_sse_events(raw_buffer: str, provider: "Provider | None" = None) -> list[str]:
    """Split a raw SSE buffer into complete events, keeping the usage-bearing ones.

    SSE events are delimited by ``\\n\\n``.

    Which events carry usage is per-provider, so the decision belongs to
    ``provider.should_buffer_chunk()``. ``USAGE_EVENT_INDICATORS`` is the legacy
    fallback for callers with no provider in hand (and for providers absent from
    the registry, e.g. in tests): it is the *union* of every bundled provider's
    indicators, so it over-matches rather than under-matches.

    Passing the provider matters for any provider whose usage key isn't in that
    hardcoded union — without it, usage is silently dropped and the request
    costs $0.
    """
    gate = (
        (lambda e: provider.should_buffer_chunk(e.encode("utf-8", errors="ignore")))
        if provider is not None
        else (lambda e: any(i in e for i in USAGE_EVENT_INDICATORS))
    )
    events: list[str] = []
    for event in raw_buffer.split("\n\n"):
        event = event.strip()
        if not event:
            continue
        if gate(event):
            events.append(event + "\n\n")
    return events


def extract_usage_from_stream(
    provider_name: str,
    usage_chunks: list[str],
    provider: "Provider | None" = None,
) -> TokenUsage:
    """Parse token usage from buffered streaming chunks for a given provider.

    Prefers the ``provider`` instance when the caller has one (the proxy always
    does) — re-resolving it from the registry by name would discard the very
    object being asked to do the work. Falls back to a registry lookup by name,
    then to the built-in private extractors when the registry isn't populated
    (e.g. tests that don't trigger registration).

    Args:
        provider_name: "openai", "anthropic", or "google"
        usage_chunks: complete SSE event strings (reassembled from raw chunks)
        provider: the Provider instance, when the caller already holds one

    Returns:
        TokenUsage with whatever counts could be extracted (zeros if none found)
    """
    from burnlens.providers.registry import get as _get_provider
    try:
        provider = provider if provider is not None else _get_provider(provider_name)
    except KeyError:
        # Registry not populated — fall back to built-in extractors
        if provider_name == "openai":
            return _extract_openai_stream(usage_chunks)
        if provider_name == "anthropic":
            return _extract_anthropic_stream(usage_chunks)
        if provider_name == "google":
            return _extract_google_stream(usage_chunks)
        return TokenUsage()

    acc: dict = {}
    for chunk_str in usage_chunks:
        provider.extract_usage_from_stream_chunk(chunk_str.encode("utf-8"), acc)
    return TokenUsage(
        input_tokens=acc.get("input_tokens", 0),
        output_tokens=acc.get("output_tokens", 0),
        reasoning_tokens=acc.get("reasoning_tokens", 0),
        cache_read_tokens=acc.get("cache_read_tokens", 0),
        cache_write_tokens=acc.get("cache_write_tokens", 0),
        audio_input_tokens=acc.get("audio_input_tokens", 0),
        audio_output_tokens=acc.get("audio_output_tokens", 0),
    )


def _extract_openai_stream(chunks: list[str]) -> TokenUsage:
    """OpenAI SSE format: data: {...}\\n\\n

    Usage appears in the final data chunk when the caller sets
    stream_options={"include_usage": true}.  Each chunk is one SSE event.
    """
    usage = TokenUsage()
    for chunk_str in chunks:
        for line in chunk_str.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                data = json.loads(payload)
                u = data.get("usage")
                if not u:
                    continue
                details = u.get("completion_tokens_details") or {}
                prompt_details = u.get("prompt_tokens_details") or {}
                reasoning = details.get("reasoning_tokens", 0)
                usage = TokenUsage(
                    input_tokens=u.get("prompt_tokens", 0),
                    # completion_tokens includes reasoning; keep them disjoint
                    output_tokens=max(0, u.get("completion_tokens", 0) - reasoning),
                    reasoning_tokens=reasoning,
                    cache_read_tokens=prompt_details.get("cached_tokens", 0),
                    audio_input_tokens=prompt_details.get("audio_tokens", 0),
                    audio_output_tokens=details.get("audio_tokens", 0),
                )
            except Exception:
                pass
    return usage


def _extract_anthropic_stream(chunks: list[str]) -> TokenUsage:
    """Anthropic SSE format: event: <type>\\ndata: {...}\\n\\n

    Usage is split across two event types:
    - message_start  → input tokens in data.message.usage
    - message_delta  → output tokens in data.usage

    We accumulate both rather than replacing so neither is lost.
    """
    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0
    cache_write_tokens = 0

    for chunk_str in chunks:
        for line in chunk_str.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                data = json.loads(payload)
                event_type = data.get("type")

                if event_type == "message_start":
                    # Input tokens are nested: data.message.usage
                    u = (data.get("message") or {}).get("usage") or {}
                    input_tokens = u.get("input_tokens", input_tokens)
                    cache_read_tokens = u.get("cache_read_input_tokens", cache_read_tokens)
                    cache_write_tokens = u.get("cache_creation_input_tokens", cache_write_tokens)
                    # Anthropic may include an initial output_tokens estimate here too
                    if u.get("output_tokens"):
                        output_tokens = u["output_tokens"]

                elif event_type == "message_delta":
                    # Final output token count is in data.usage
                    u = data.get("usage") or {}
                    if u.get("output_tokens"):
                        output_tokens = u["output_tokens"]

            except Exception:
                pass

    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
    )


def _extract_google_stream(chunks: list[str]) -> TokenUsage:
    """Google streaming: SSE format (data: {...}), one JSON object per event.

    usageMetadata appears in each chunk but later chunks have the
    cumulative totals, so the last one seen wins.
    """
    usage = TokenUsage()
    for chunk_str in chunks:
        for line in chunk_str.splitlines():
            line = line.strip()
            # Google streaming uses SSE format like OpenAI: "data: {...}"
            if line.startswith("data:"):
                payload = line[5:].strip()
            elif line.startswith("{"):
                # Fallback: raw NDJSON (older API versions)
                payload = line
            else:
                continue
            if not payload or payload == "[DONE]":
                continue
            try:
                data = json.loads(payload)
                meta = data.get("usageMetadata") or {}
                if "promptTokenCount" in meta or "candidatesTokenCount" in meta:
                    usage = TokenUsage(
                        input_tokens=meta.get("promptTokenCount", 0),
                        output_tokens=meta.get("candidatesTokenCount", 0),
                    )
            except Exception:
                pass
    return usage
