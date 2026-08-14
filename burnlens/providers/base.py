"""Provider plugin interface — base class and config dataclass."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from burnlens.cost.calculator import TokenUsage

# Substrings that mark an SSE line as possibly carrying a tool call. Used to skip
# JSON-parsing the (overwhelmingly common) tool-free line.
_STREAM_TOOL_MARKERS: tuple[str, ...] = ('"tool_calls"', '"tool_use"', '"functionCall"')


@dataclass(frozen=True)
class ProviderConfig:
    name: str            # "openai", "anthropic", "google", etc.
    proxy_path: str      # "/proxy/openai"
    upstream_url: str    # base upstream URL, no trailing slash
    auth_header: str     # "Authorization", "x-api-key", "x-goog-api-key"
    streaming_format: str  # "sse-openai", "sse-anthropic", "sse-google"
    pricing_key: str     # matches pricing_data/{pricing_key}.json
    env_var: str = ""    # SDK env var, e.g. "OPENAI_BASE_URL"; "" if unsupported
    # Does this provider's reported input-token count already INCLUDE the
    # cached tokens? OpenAI and Google report the whole prompt as
    # `prompt_tokens`/`promptTokenCount` with the cached share as a subset of
    # it; Anthropic reports `input_tokens` and `cache_read_input_tokens` as
    # DISJOINT counts. Getting this wrong is silent in both directions: summing
    # the columns double-counts the cache for the inclusive providers, and
    # subtracting it under-bills the uncached input for the disjoint ones.
    prompt_tokens_include_cache: bool = False


class Provider(ABC):
    config: ProviderConfig

    # ------------------------------------------------------------------
    # Backward-compat properties so Provider instances can be used
    # wherever the old ProviderConfig dataclass was expected.
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def proxy_prefix(self) -> str:
        """Alias for config.proxy_path — keeps strip_proxy_prefix working."""
        return self.config.proxy_path

    @property
    def upstream_base(self) -> str:
        """Alias for config.upstream_url — keeps interceptor URL building working."""
        return self.config.upstream_url

    @property
    def env_var(self) -> str:
        return self.config.env_var

    # ------------------------------------------------------------------
    # Abstract interface — every provider must implement these
    # ------------------------------------------------------------------

    @abstractmethod
    def resolve_upstream_url(self, request_path: str, headers: dict[str, str]) -> str:
        """Return the full upstream URL for the given stripped request path."""

    @abstractmethod
    def extract_model(self, request_body: dict, request_path: str) -> Optional[str]:
        """Return model name from request body or path, or None if not found."""

    @abstractmethod
    def extract_usage(self, response_body: dict) -> TokenUsage:
        """Extract token counts from a non-streaming response body."""

    @abstractmethod
    def extract_usage_from_stream_chunk(
        self, chunk: bytes, accumulator: dict
    ) -> Optional[TokenUsage]:
        """Accumulate usage from one SSE chunk into accumulator dict.

        Mutates accumulator in-place.  Returns a complete TokenUsage only
        when this chunk is the definitive final usage event; otherwise None.
        The caller builds the final TokenUsage from the accumulator after
        all chunks are consumed.
        """

    @abstractmethod
    def should_buffer_chunk(self, chunk: bytes) -> bool:
        """Return True if this raw chunk may contain usage data."""

    # ------------------------------------------------------------------
    # Optional overrides
    # ------------------------------------------------------------------

    def headers_to_strip(self) -> set[str]:
        """BurnLens tag headers to remove before forwarding upstream."""
        return {
            "x-burnlens-tag-feature",
            "x-burnlens-tag-team",
            "x-burnlens-tag-customer",
            "x-burnlens-key",
        }

    def rewrite_path_for_routing(self, path: str, routed_model: str) -> str:
        """Rewrite upstream URL path to reflect a downgraded model.

        Default no-op. Override for providers that encode the model in the URL
        path (e.g. Google: /v1beta/models/{model}:generateContent).
        """
        return path

    def is_streaming(self, request_body: dict, request_path: str) -> bool:
        """Return True if this request will produce a streaming response.

        Default: OpenAI/Anthropic-style ``"stream": true`` in the body. Override
        for providers that signal streaming via the URL instead (Google's
        ``:streamGenerateContent``, Bedrock's ``/converse-stream``).
        """
        return bool(request_body.get("stream", False))

    def count_tool_calls(self, response_body: dict) -> int:
        """Return the number of tool/function calls in a non-streaming response.

        The default handles all three wire shapes in use today, so no provider
        currently overrides it:

        * OpenAI-compatible — ``choices[].message.tool_calls`` (also covers
          Azure OpenAI, Groq, Together, Mistral, xAI, DeepSeek).
        * Anthropic — ``content[]`` blocks with ``type == "tool_use"`` (also
          covers Bedrock's Claude responses).
        * Google — ``candidates[].content.parts[]`` entries with ``functionCall``.

        Best-effort telemetry, never load-bearing for cost: any unexpected shape
        returns 0 rather than raising.
        """
        if not isinstance(response_body, dict):
            return 0
        count = 0
        try:
            for choice in response_body.get("choices") or []:
                calls = (choice or {}).get("message", {}).get("tool_calls")
                if isinstance(calls, list):
                    count += len(calls)

            for block in response_body.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    count += 1

            for candidate in response_body.get("candidates") or []:
                parts = (candidate or {}).get("content", {}).get("parts")
                for part in parts or []:
                    if isinstance(part, dict) and part.get("functionCall"):
                        count += 1
        except (AttributeError, TypeError):
            return 0
        return count

    def count_tool_calls_in_stream(self, raw_buffer: str) -> int:
        """Return the number of tool/function calls in a complete SSE response.

        Streaming fragments each call across many deltas, so ``count_tool_calls``
        — a single body parse — cannot see them, and every streaming request used
        to record ``tool_calls=0``. One default covers each SSE shape in use, so
        no provider currently overrides it:

        * OpenAI-compatible — ``choices[].delta.tool_calls[]``, deduped by
          ``index`` (or ``id``) because the argument fragments repeat it.
        * Anthropic — ``content_block_start`` events whose block is ``tool_use``.
        * Google — ``candidates[].content.parts[].functionCall``.

        Takes the *whole* stream buffer, not the usage-gated subset: tool events
        carry no usage, so ``should_buffer_chunk`` discards them. Only lines
        carrying a tool marker are parsed, so a tool-free stream costs one
        substring scan.

        ⚠️ Bedrock's binary event frames are NOT covered — its ``toolUse`` blocks
        still count 0.

        Best-effort telemetry, never load-bearing for cost: any unexpected shape
        returns 0 rather than raising.
        """
        if not raw_buffer or not any(m in raw_buffer for m in _STREAM_TOOL_MARKERS):
            return 0

        openai_calls: set = set()  # deduped: many deltas per call
        count = 0                  # Anthropic/Google: one event per call
        for line in raw_buffer.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
            elif line.startswith("{"):
                payload = line  # Google raw-NDJSON fallback
            else:
                continue
            if not any(m in payload for m in _STREAM_TOOL_MARKERS):
                continue
            try:
                data = json.loads(payload)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            try:
                for choice in data.get("choices") or []:
                    delta = (choice or {}).get("delta") or {}
                    for entry in delta.get("tool_calls") or []:
                        if not isinstance(entry, dict):
                            continue
                        # index identifies the call; id only rides the first delta
                        key = entry.get("index", entry.get("id"))
                        if key is not None:
                            openai_calls.add(key)

                if data.get("type") == "content_block_start":
                    block = data.get("content_block") or {}
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        count += 1

                for candidate in data.get("candidates") or []:
                    parts = ((candidate or {}).get("content") or {}).get("parts") or []
                    for part in parts:
                        if isinstance(part, dict) and part.get("functionCall"):
                            count += 1
            except (AttributeError, TypeError):
                continue

        return len(openai_calls) + count
