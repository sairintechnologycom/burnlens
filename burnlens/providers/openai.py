"""OpenAI provider plugin."""
from __future__ import annotations

import json
from typing import Optional

from burnlens.cost.calculator import TokenUsage, extract_usage_openai
from burnlens.providers.base import Provider, ProviderConfig


class OpenAIProvider(Provider):
    config = ProviderConfig(
        name="openai",
        proxy_path="/proxy/openai",
        upstream_url="https://api.openai.com",
        auth_header="Authorization",
        streaming_format="sse-openai",
        pricing_key="openai",
        env_var="OPENAI_BASE_URL",
    )

    def resolve_upstream_url(self, request_path: str, headers: dict[str, str]) -> str:
        return self.config.upstream_url + request_path

    def extract_model(self, request_body: dict, request_path: str) -> Optional[str]:
        return request_body.get("model")

    def extract_usage(self, response_body: dict) -> TokenUsage:
        return extract_usage_openai(response_body)

    def extract_usage_from_stream_chunk(
        self, chunk: bytes, accumulator: dict
    ) -> Optional[TokenUsage]:
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
                u = data.get("usage")
                if not u:
                    continue
                details = u.get("completion_tokens_details") or {}
                prompt_details = u.get("prompt_tokens_details") or {}
                accumulator["input_tokens"] = u.get("prompt_tokens", 0)
                accumulator["output_tokens"] = u.get("completion_tokens", 0)
                accumulator["reasoning_tokens"] = details.get("reasoning_tokens", 0)
                accumulator["cache_read_tokens"] = prompt_details.get("cached_tokens", 0)
            except Exception:
                pass
        return None

    def should_buffer_chunk(self, chunk: bytes) -> bool:
        return b'"usage"' in chunk


openai_provider = OpenAIProvider()
