"""SSE streaming: usage extraction from provider-specific streaming formats."""
from __future__ import annotations

import json

from burnlens.cost.calculator import TokenUsage

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


def should_buffer_chunk(chunk_str: str) -> bool:
    """Return True if this chunk should be saved for usage extraction.

    Avoids storing every SSE chunk in memory — only the subset that
    contains token counts.

    .. note::
       This checks raw TCP chunks and may miss usage data split across
       chunk boundaries.  Prefer :func:`split_sse_events` for robust
       extraction.
    """
    return any(indicator in chunk_str for indicator in USAGE_EVENT_INDICATORS)


def split_sse_events(raw_buffer: str) -> list[str]:
    """Split a raw SSE buffer into complete events.

    SSE events are delimited by ``\\n\\n``.  Returns only events that
    contain usage-related data (per USAGE_EVENT_INDICATORS).
    """
    events: list[str] = []
    for event in raw_buffer.split("\n\n"):
        event = event.strip()
        if not event:
            continue
        if any(indicator in event for indicator in USAGE_EVENT_INDICATORS):
            events.append(event + "\n\n")
    return events


def extract_usage_from_stream(provider_name: str, usage_chunks: list[str]) -> TokenUsage:
    """Parse token usage from buffered streaming chunks for a given provider.

    Args:
        provider_name: "openai", "anthropic", or "google"
        usage_chunks: complete SSE event strings (reassembled from raw chunks)

    Returns:
        TokenUsage with whatever counts could be extracted (zeros if none found)
    """
    if provider_name == "openai":
        return _extract_openai_stream(usage_chunks)
    if provider_name == "anthropic":
        return _extract_anthropic_stream(usage_chunks)
    if provider_name == "google":
        return _extract_google_stream(usage_chunks)
    return TokenUsage()


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
                usage = TokenUsage(
                    input_tokens=u.get("prompt_tokens", 0),
                    output_tokens=u.get("completion_tokens", 0),
                    reasoning_tokens=details.get("reasoning_tokens", 0),
                    cache_read_tokens=prompt_details.get("cached_tokens", 0),
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
