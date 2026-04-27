"""SDK transport interceptor for BurnLens shadow AI detection.

This module provides a second detection path beyond the proxy server.
Users who want SDK-level interception without routing through localhost:8420
can wrap their async client directly::

    import burnlens
    from openai import AsyncOpenAI

    client = AsyncOpenAI()
    burnlens.wrap(client)   # mutates in place, returns same object

The wrap() function replaces the client's internal httpx transport with
BurnLensTransport, which logs model, latency, and HTTP status code to the
ai_assets table without ever storing request or response payloads.

Scope notes (Phase 2):
- Async clients only (AsyncOpenAI, AsyncAnthropic). Sync clients emit a warning.
- Token counts are NOT available via this path — they come from the proxy path
  (DETC-08). Model is extracted from the URL path only (best-effort).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from burnlens.detection.classifier import upsert_asset_from_detection

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = str(Path.home() / ".burnlens" / "burnlens.db")


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def _infer_provider_from_host(host: str) -> str:
    """Infer a provider name from a hostname (best-effort)."""
    host_lower = host.lower()
    if "openai.com" in host_lower or "openai.azure.com" in host_lower:
        return "openai"
    if "anthropic.com" in host_lower:
        return "anthropic"
    if "generativelanguage.googleapis.com" in host_lower:
        return "google"
    if "bedrock" in host_lower:
        return "aws_bedrock"
    if "cohere" in host_lower:
        return "cohere"
    return host_lower.split(".")[0]  # fallback: first label of hostname


def _extract_model_from_path(path: str) -> str:
    """Extract a model hint from the URL path (best-effort).

    Rules:
    - /v1/models/{model-id}  ->  "{model-id}"  (model explicitly in path)
    - /v1/chat/completions   ->  "chat/completions"
    - /v1/messages           ->  "messages"
    - Any other path         ->  last two non-empty segments joined with "/"

    Token counts and the real model name come from the proxy path (DETC-08).
    """
    # Strip leading slash and split
    segments = [s for s in path.split("/") if s]

    # Strip version prefix like "v1" or "v1beta"
    if segments and segments[0].startswith("v"):
        segments = segments[1:]

    # Known pattern: /v1/models/{model-id}
    if len(segments) >= 2 and segments[0] == "models":
        return segments[1]

    # General: join remaining segments (up to 2) as model hint
    return "/".join(segments[:2]) if len(segments) >= 2 else "/".join(segments)


def _hash_auth_header(authorization: str | None) -> str | None:
    """SHA-256 hash the Bearer token from an Authorization header.

    Raw API keys are NEVER stored — only the hash.
    """
    if not authorization:
        return None
    # Expected format: "Bearer sk-..."
    parts = authorization.strip().split(" ", 1)
    token = parts[-1]  # works whether prefix is present or not
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# BurnLensTransport
# ---------------------------------------------------------------------------


class BurnLensTransport(httpx.AsyncBaseTransport):
    """httpx async transport that logs AI API call metadata to BurnLens.

    Wraps another AsyncBaseTransport (the real one). Forwards the request
    unchanged, records metadata asynchronously after the inner transport
    returns. The response body is NEVER read or consumed.

    Args:
        inner: The original transport to delegate to.
        db_path: Absolute path to the BurnLens SQLite database.
    """

    def __init__(self, inner: httpx.AsyncBaseTransport, db_path: str) -> None:
        self._inner = inner
        self._db_path = db_path

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Forward request to inner transport and log metadata asynchronously.

        The response is returned immediately after the inner transport
        completes. Logging is fire-and-forget (asyncio.create_task) and
        never delays the response to the caller.

        CRITICAL: This method MUST NOT call response.aread(), response.read(),
        or iterate response.stream. Doing so would consume the body before
        the SDK can read it, breaking streaming.
        """
        start = time.monotonic()
        response = await self._inner.handle_async_request(request)
        duration_ms = int((time.monotonic() - start) * 1000)

        # Fire-and-forget — never await in the hot path
        asyncio.create_task(self._log_metadata(request, response, duration_ms))

        return response

    async def _log_metadata(
        self,
        request: httpx.Request,
        response: httpx.Response,
        duration_ms: int,
    ) -> None:
        """Log model/latency/status metadata to ai_assets (best-effort).

        Errors are caught and logged as warnings — this method must NEVER
        raise, because a failure here should not surface to the caller.

        CRITICAL: Do NOT call response.aread(), response.read(), or iterate
        response.stream — that would consume the response body before the
        SDK reads it. response.status_code is a header-level attribute that
        is safe to read without touching the body.
        """
        try:
            url = request.url
            host = url.host
            path = url.path

            provider = _infer_provider_from_host(host)
            model = _extract_model_from_path(path)
            endpoint_url = str(url)

            auth_header = request.headers.get("authorization")
            api_key_hash = _hash_auth_header(auth_header)

            # status_code is a header-level attribute — safe to read
            _ = response.status_code  # noqa: F841 (recorded for future use)

            await upsert_asset_from_detection(
                self._db_path,
                provider,
                model,
                endpoint_url,
                api_key_hash,
            )

            logger.debug(
                "BurnLensTransport logged: provider=%s model=%s duration_ms=%d status=%d",
                provider,
                model,
                duration_ms,
                response.status_code,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "BurnLensTransport: failed to log metadata (swallowed)",
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def wrap(client: Any, db_path: str | None = None) -> Any:
    """Wrap an async OpenAI/Anthropic client to log AI API calls to BurnLens.

    Mutates the client in place by replacing its internal httpx transport
    with a BurnLensTransport. Returns the same client object so the call
    can be chained::

        client = burnlens.wrap(AsyncOpenAI())

    This is a Phase 2 SDK detection path. Limitations:
    - Async clients only (AsyncOpenAI, AsyncAnthropic). Sync clients receive
      a warning and are returned unmodified.
    - Token counts are NOT available via this path. Model is extracted from
      the URL path only (best-effort). For full cost tracking, use the proxy.
    - Request and response payloads are NEVER stored — only model, latency,
      and HTTP status code metadata.

    Args:
        client: An async OpenAI or Anthropic SDK client instance.
        db_path: Path to the BurnLens SQLite database. Defaults to
            ~/.burnlens/burnlens.db.

    Returns:
        The same client object (mutated in place).
    """
    resolved_db_path = db_path if db_path is not None else _DEFAULT_DB_PATH

    inner_client = getattr(client, "_client", None)
    if inner_client is None:
        logger.warning(
            "burnlens.wrap(): client has no ._client attribute — "
            "only async clients (AsyncOpenAI, AsyncAnthropic) are supported. "
            "Client returned unmodified."
        )
        return client

    original_transport = getattr(inner_client, "_transport", None)
    if original_transport is None:
        logger.warning(
            "burnlens.wrap(): client._client has no ._transport attribute. "
            "Client returned unmodified."
        )
        return client

    new_transport = BurnLensTransport(inner=original_transport, db_path=resolved_db_path)
    inner_client._transport = new_transport

    logger.debug(
        "burnlens.wrap(): transport replaced with BurnLensTransport (db=%s)",
        resolved_db_path,
    )
    return client
