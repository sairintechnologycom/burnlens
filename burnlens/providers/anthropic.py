"""Anthropic provider plugin."""
from __future__ import annotations

import json
from typing import Optional

from burnlens.cost.calculator import TokenUsage, extract_usage_anthropic
from burnlens.providers.base import Provider, ProviderConfig


class AnthropicProvider(Provider):
    config = ProviderConfig(
        name="anthropic",
        proxy_path="/proxy/anthropic",
        upstream_url="https://api.anthropic.com",
        auth_header="x-api-key",
        streaming_format="sse-anthropic",
        pricing_key="anthropic",
        env_var="ANTHROPIC_BASE_URL",
    )

    def resolve_upstream_url(self, request_path: str, headers: dict[str, str]) -> str:
        return self.config.upstream_url + request_path

    def extract_model(self, request_body: dict, request_path: str) -> Optional[str]:
        return request_body.get("model")

    def extract_usage(self, response_body: dict) -> TokenUsage:
        return extract_usage_anthropic(response_body)

    def extract_usage_from_stream_chunk(
        self, chunk: bytes, accumulator: dict
    ) -> Optional[TokenUsage]:
        """Accumulate usage from message_start (input) and message_delta (output)."""
        chunk_str = chunk.decode("utf-8", errors="ignore")
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
                    u = (data.get("message") or {}).get("usage") or {}
                    accumulator["input_tokens"] = u.get(
                        "input_tokens", accumulator.get("input_tokens", 0)
                    )
                    accumulator["cache_read_tokens"] = u.get(
                        "cache_read_input_tokens", accumulator.get("cache_read_tokens", 0)
                    )
                    accumulator["cache_write_tokens"] = u.get(
                        "cache_creation_input_tokens",
                        accumulator.get("cache_write_tokens", 0),
                    )
                    if u.get("output_tokens"):
                        accumulator["output_tokens"] = u["output_tokens"]

                elif event_type == "message_delta":
                    u = data.get("usage") or {}
                    if u.get("output_tokens"):
                        accumulator["output_tokens"] = u["output_tokens"]

            except Exception:
                pass
        return None

    def should_buffer_chunk(self, chunk: bytes) -> bool:
        return any(
            ind in chunk
            for ind in (b'"usage"', b"message_start", b"message_delta")
        )


anthropic_provider = AnthropicProvider()
