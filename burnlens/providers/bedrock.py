"""AWS Bedrock provider plugin.

Bedrock differs from the other providers in three ways:

* **Endpoint** — per-region (``https://bedrock-runtime.{region}.amazonaws.com``),
  so it can't be hardcoded. The proxy reads the region from
  ``BURNLENS_BEDROCK_REGION`` at request time. (The client-side
  ``AWS_ENDPOINT_URL_BEDROCK_RUNTIME`` that boto3 reads is repointed at BurnLens
  by the CLI wrapper — a *different* var, so the two never collide.)
* **Auth** — a Bedrock API key sent as ``Authorization: Bearer <key>``
  (``AWS_BEARER_TOKEN_BEDROCK``), forwarded upstream untouched.

  BurnLens does **not** support SigV4-signed requests. SigV4 signs over the
  ``host`` header; the proxy replaces ``host`` when forwarding, which
  invalidates the signature. Supporting it would mean re-signing at the proxy
  with the caller's AWS credentials. Use a Bedrock API key instead.
* **Model in the path** — ``/model/{modelId}/converse``. The ID is
  percent-encoded by the SDKs (inference-profile IDs contain ``.`` and ``:``)
  and carries a geo prefix: ``us.``/``eu.``/``au.``/``jp.``/``global.``. Many
  models are not available for in-region inference at all, so the prefixed form
  is the norm, not an edge case — pricing keys are stored WITH the prefix.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional
from urllib.parse import unquote

from burnlens.cost.calculator import TokenUsage
from burnlens.providers.base import Provider, ProviderConfig

REGION_ENV = "BURNLENS_BEDROCK_REGION"

# /model/{modelId}/converse | converse-stream | invoke | invoke-with-response-stream
_MODEL_IN_PATH_RE = re.compile(r"(/model/)([^/]+)(/[A-Za-z-]+)")

# Operations that return a stream. Bedrock signals this with a distinct
# operation, not a body flag.
_STREAM_OPS = ("/converse-stream", "/invoke-with-response-stream")


class BedrockProvider(Provider):
    config = ProviderConfig(
        name="bedrock",
        proxy_path="/proxy/bedrock",
        upstream_url="",  # per-region; resolved from BURNLENS_BEDROCK_REGION
        auth_header="Authorization",
        streaming_format="aws-eventstream",
        pricing_key="bedrock",
        env_var="AWS_ENDPOINT_URL_BEDROCK_RUNTIME",  # SDK var the CLI wrapper repoints
    )

    @property
    def upstream_base(self) -> str:
        region = os.environ.get(REGION_ENV, "").strip()
        if not region:
            raise RuntimeError(
                f"Bedrock provider requires {REGION_ENV} to be set to your AWS "
                "region, e.g. us-east-1"
            )
        return f"https://bedrock-runtime.{region}.amazonaws.com"

    def resolve_upstream_url(self, request_path: str, headers: dict[str, str]) -> str:
        return self.upstream_base + request_path

    def extract_model(self, request_body: dict, request_path: str) -> Optional[str]:
        """Model ID from /model/{modelId}/<op>, percent-decoded.

        The prefix (``us.``) and version suffix (``:0``) are preserved — they are
        part of the pricing key. Deliberately NOT normalized: prefix-matching a
        model name is what produced the v1.7.0 GPT-5.6 mispricing, and a wrong
        nonzero cost is worse than no cost.
        """
        path = request_path.split("?", 1)[0]
        parts = path.split("/")
        for i, part in enumerate(parts):
            if part == "model" and i + 1 < len(parts):
                return unquote(parts[i + 1])
        return request_body.get("modelId") or request_body.get("model")

    def rewrite_path_for_routing(self, path: str, routed_model: str) -> str:
        """Rewrite the {modelId} segment for a downgraded model.

        URL-injection invariant: ``routed_model`` is sourced exclusively from
        ``DOWNGRADE_MAP`` (a hardcoded dict in ``burnlens/providers/downgrade.py``),
        never from user input, so the substitution string is fully trusted.
        """
        return _MODEL_IN_PATH_RE.sub(rf"\g<1>{routed_model}\g<3>", path, count=1)

    def is_streaming(self, request_body: dict, request_path: str) -> bool:
        return any(op in request_path for op in _STREAM_OPS)

    def extract_usage(self, response_body: dict) -> TokenUsage:
        """Converse returns camelCase usage; InvokeModel passes the vendor's body through."""
        u = response_body.get("usage") or {}
        if "inputTokens" in u or "outputTokens" in u:  # Converse
            return TokenUsage(
                input_tokens=u.get("inputTokens", 0),
                output_tokens=u.get("outputTokens", 0),
                cache_read_tokens=u.get("cacheReadInputTokens", 0) or 0,
                cache_write_tokens=u.get("cacheWriteInputTokens", 0) or 0,
            )
        # InvokeModel with an Anthropic-format body (snake_case).
        return TokenUsage(
            input_tokens=u.get("input_tokens", 0),
            output_tokens=u.get("output_tokens", 0),
            cache_read_tokens=u.get("cache_read_input_tokens", 0) or 0,
            cache_write_tokens=u.get("cache_creation_input_tokens", 0) or 0,
        )

    def extract_usage_from_stream_chunk(
        self, chunk: bytes, accumulator: dict
    ) -> Optional[TokenUsage]:
        """Scan raw eventstream bytes for the Converse metadata event's usage blob.

        ponytail: byte-scan, not a vnd.amazon.eventstream frame decoder. The
        Converse metadata event carries plain JSON in its frame payload, so
        locating `{"usage":{...}}` needs no prelude/CRC parsing. Upgrade to a real
        framing decoder if AWS ever compresses payloads or splits the JSON across
        frames. Callers accumulate raw bytes across chunks before calling this, so
        an event split across TCP reads is already handled.
        """
        idx = chunk.find(b'"usage"')
        while idx != -1:
            obj = _scan_json_object(chunk, chunk.find(b"{", idx + len(b'"usage"')))
            if obj is not None:
                try:
                    u = json.loads(obj)
                except Exception:
                    u = None
                if isinstance(u, dict) and (
                    "inputTokens" in u or "outputTokens" in u
                ):
                    accumulator["input_tokens"] = u.get("inputTokens", 0)
                    accumulator["output_tokens"] = u.get("outputTokens", 0)
                    if u.get("cacheReadInputTokens"):
                        accumulator["cache_read_tokens"] = u["cacheReadInputTokens"]
                    if u.get("cacheWriteInputTokens"):
                        accumulator["cache_write_tokens"] = u["cacheWriteInputTokens"]
            idx = chunk.find(b'"usage"', idx + 1)
        return None

    def should_buffer_chunk(self, chunk: bytes) -> bool:
        return b"inputTokens" in chunk or b'"usage"' in chunk


def _scan_json_object(buf: bytes, start: int) -> Optional[bytes]:
    """Return the brace-balanced JSON object starting at ``start``, or None.

    The payload is raw JSON inside a binary frame, so we can't just take the rest
    of the buffer — we track depth and stop at the matching close brace. Strings
    are skipped so a brace inside a value can't unbalance the count.
    """
    if start < 0 or start >= len(buf) or buf[start : start + 1] != b"{":
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(buf)):
        c = buf[i : i + 1]
        if in_str:
            if esc:
                esc = False
            elif c == b"\\":
                esc = True
            elif c == b'"':
                in_str = False
            continue
        if c == b'"':
            in_str = True
        elif c == b"{":
            depth += 1
        elif c == b"}":
            depth -= 1
            if depth == 0:
                return buf[start : i + 1]
    return None  # truncated — the object straddles a chunk boundary


bedrock_provider = BedrockProvider()
