"""Google Gemini provider plugin."""
from __future__ import annotations

import json
from typing import Optional

from burnlens.cost.calculator import TokenUsage, extract_usage_google
from burnlens.providers.base import Provider, ProviderConfig


class GoogleProvider(Provider):
    config = ProviderConfig(
        name="google",
        proxy_path="/proxy/google",
        upstream_url="https://generativelanguage.googleapis.com",
        auth_header="x-goog-api-key",
        streaming_format="sse-google",
        pricing_key="google",
        env_var="",  # Google SDK does not support a base-URL env var; use burnlens.patch
    )

    def resolve_upstream_url(self, request_path: str, headers: dict[str, str]) -> str:
        return self.config.upstream_url + request_path

    def extract_model(self, request_body: dict, request_path: str) -> Optional[str]:
        # Model is encoded in the path: /v1beta/models/{model}:generateContent
        parts = request_path.split("/")
        for i, part in enumerate(parts):
            if part == "models" and i + 1 < len(parts):
                return parts[i + 1].split(":")[0]
        return request_body.get("model")

    def extract_usage(self, response_body: dict) -> TokenUsage:
        return extract_usage_google(response_body)

    def extract_usage_from_stream_chunk(
        self, chunk: bytes, accumulator: dict
    ) -> Optional[TokenUsage]:
        """Last usageMetadata seen across chunks wins (Google includes cumulative counts)."""
        chunk_str = chunk.decode("utf-8", errors="ignore")
        for line in chunk_str.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
            elif line.startswith("{"):
                payload = line  # fallback: raw NDJSON (older API versions)
            else:
                continue
            if not payload or payload == "[DONE]":
                continue
            try:
                data = json.loads(payload)
                meta = data.get("usageMetadata") or {}
                if "promptTokenCount" in meta or "candidatesTokenCount" in meta:
                    accumulator["input_tokens"] = meta.get("promptTokenCount", 0)
                    accumulator["output_tokens"] = meta.get("candidatesTokenCount", 0)
            except Exception:
                pass
        return None

    def should_buffer_chunk(self, chunk: bytes) -> bool:
        return b"usageMetadata" in chunk


google_provider = GoogleProvider()
