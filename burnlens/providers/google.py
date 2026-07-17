"""Google Gemini provider plugin."""
from __future__ import annotations

import json
import re
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

    # Compiled once at module import. Linear regex (no nested quantifiers,
    # no greedy alternation that backtracks) — no ReDoS risk on str input.
    # Restricted to the two generation methods; :countTokens, :embedContent,
    # :batchEmbedContents, and /tunedModels/ paths fall outside the pattern
    # and pass through unmodified (per phase 17 CONTEXT decision #1).
    _MODEL_IN_PATH_RE = re.compile(
        r"(/(?:v1|v1beta)/models/)([^:/]+)(:(?:generateContent|streamGenerateContent))"
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

    def rewrite_path_for_routing(self, path: str, routed_model: str) -> str:
        """Rewrite the {model} segment for :generateContent / :streamGenerateContent.

        Other methods (:countTokens, :embedContent, :batchEmbedContents, tuning
        paths) pass through unmodified — downgrading them is not in scope
        (per phase 17 CONTEXT decision #1).

        URL-injection invariant: ``routed_model`` is sourced exclusively from
        ``DOWNGRADE_MAP`` (a hardcoded dict in ``burnlens/providers/downgrade.py``),
        never from user input. The substitution string is fully trusted.
        """
        return self._MODEL_IN_PATH_RE.sub(
            rf"\g<1>{routed_model}\g<3>", path, count=1
        )

    def is_streaming(self, request_body: dict, request_path: str) -> bool:
        """Google signals streaming via the URL endpoint, not the body."""
        return ":streamGenerateContent" in request_path or super().is_streaming(
            request_body, request_path
        )

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
