"""Request/response interception: tag extraction, forwarding, logging, cost."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, AsyncIterator

import httpx

from burnlens.cost.calculator import (
    TokenUsage,
    calculate_cost,
    extract_usage_anthropic,
    extract_usage_google,
    extract_usage_openai,
)
from burnlens.proxy.providers import ProviderConfig, strip_proxy_prefix
from burnlens.proxy.streaming import extract_usage_from_stream, should_buffer_chunk
from burnlens.storage.database import insert_request
from burnlens.storage.models import RequestRecord

if TYPE_CHECKING:
    from burnlens.alerts.engine import AlertEngine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known upstream error patterns → human-readable hints
# ---------------------------------------------------------------------------

_ERROR_HINTS: list[tuple[str, str]] = [
    # Billing / credits
    ("credit balance is too low", "Add credits at console.anthropic.com/settings/billing"),
    ("your account is not active", "Activate your Anthropic account at console.anthropic.com"),
    ("exceeded your current quota", "Quota exceeded — check your plan at platform.openai.com/account/limits"),
    ("billing_not_enabled", "Enable billing for this Google Cloud project at console.cloud.google.com/billing"),
    ("generate_content_free_tier_requests", "Free tier quota exhausted — enable billing at console.cloud.google.com/billing"),
    # Auth
    ("invalid x-api-key", "Invalid Anthropic API key — check ANTHROPIC_API_KEY"),
    ("invalid api key", "Invalid API key — check your provider's key env var"),
    ("api key not valid", "Invalid Google API key — check GOOGLE_AI_STUDIO_KEY"),
    ("authentication_error", "Authentication failed — verify your API key is correct"),
    # Rate limits
    ("rate limit", "Rate limited — back off and retry, or upgrade your plan"),
    ("too many requests", "Too many requests — reduce concurrency or upgrade your plan"),
]


def _log_upstream_error_hint(status_code: int, body_bytes: bytes, provider: str) -> None:
    """Log a clear, actionable hint when the upstream returns an error."""
    if status_code < 400:
        return
    try:
        text = body_bytes.decode("utf-8", errors="ignore").lower()
    except Exception:
        return

    for pattern, hint in _ERROR_HINTS:
        if pattern.lower() in text:
            logger.warning(
                "BurnLens [%s] %d — %s", provider.upper(), status_code, hint
            )
            return

    # Generic fallback for unrecognised errors
    if status_code == 401:
        logger.warning("BurnLens [%s] 401 — Unauthorized: check your API key", provider.upper())
    elif status_code == 403:
        logger.warning("BurnLens [%s] 403 — Forbidden: key may lack permissions", provider.upper())
    elif status_code == 429:
        logger.warning("BurnLens [%s] 429 — Rate limited: slow down or upgrade your plan", provider.upper())
    elif status_code >= 500:
        logger.warning("BurnLens [%s] %d — Provider error (upstream is down or degraded)", provider.upper(), status_code)


# Headers BurnLens adds that must NOT be forwarded upstream
_BURNLENS_HEADER_PREFIX = "x-burnlens-"

# Headers that should never be forwarded (hop-by-hop + host).
# accept-encoding is stripped so upstreams never compress streaming responses:
# httpx in stream=True mode yields raw bytes without auto-decompression, so
# a gzip SSE response would produce undecodable chunks and zero usage extraction.
_STRIP_REQUEST_HEADERS = frozenset(
    ["host", "content-length", "transfer-encoding", "connection", "keep-alive", "te", "trailers",
     "upgrade", "accept-encoding"]
)

# Extra headers to strip from responses: httpx auto-decompresses, so forwarding
# content-encoding would cause the client to try to decompress again.
_STRIP_RESPONSE_HEADERS = _STRIP_REQUEST_HEADERS | frozenset(["content-encoding"])


def _extract_tags(headers: dict[str, str]) -> dict[str, str]:
    """Pull X-BurnLens-Tag-* headers into a plain dict."""
    prefix = "x-burnlens-tag-"
    return {
        key[len(prefix):]: value
        for key, value in headers.items()
        if key.lower().startswith(prefix)
    }


def _clean_request_headers(headers: dict[str, str]) -> dict[str, str]:
    """Remove BurnLens-specific and hop-by-hop headers before forwarding."""
    return {
        k: v
        for k, v in headers.items()
        if k.lower() not in _STRIP_REQUEST_HEADERS
        and not k.lower().startswith(_burnlens_header_prefix_check())
    }


def _burnlens_header_prefix_check() -> str:
    return _BURNLENS_HEADER_PREFIX


def _extract_model(body_bytes: bytes, provider_name: str) -> str:
    """Best-effort extraction of model name from request body."""
    try:
        data = json.loads(body_bytes)
        if provider_name == "google":
            # Google: model is in the URL path, not the body.
            # We fall back to the model field if present.
            return data.get("model", "unknown")
        return data.get("model", "unknown")
    except Exception:
        return "unknown"


def _extract_model_from_path(path: str, provider_name: str) -> str | None:
    """Extract model from URL path for Google (models/gemini-1.5-pro/...)."""
    if provider_name != "google":
        return None
    # Google path: /v1beta/models/{model}:generateContent
    parts = path.split("/")
    for i, part in enumerate(parts):
        if part == "models" and i + 1 < len(parts):
            model_part = parts[i + 1]
            # Strip method suffix like :generateContent
            return model_part.split(":")[0]
    return None


def _hash_system_prompt(body_bytes: bytes) -> str | None:
    """Return SHA-256 hex of the first system message content, or None."""
    try:
        data = json.loads(body_bytes)
        messages = data.get("messages") or []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return hashlib.sha256(content.encode()).hexdigest()
                if isinstance(content, list):
                    text = "".join(
                        part.get("text", "") for part in content if isinstance(part, dict)
                    )
                    return hashlib.sha256(text.encode()).hexdigest()
        # Anthropic uses top-level "system" field
        system = data.get("system")
        if system:
            text = system if isinstance(system, str) else json.dumps(system)
            return hashlib.sha256(text.encode()).hexdigest()
    except Exception:
        pass
    return None


def _is_streaming(body_bytes: bytes, upstream_path: str = "") -> bool:
    """Return True if this request will produce a streaming response.

    OpenAI/Anthropic signal streaming via ``"stream": true`` in the request body.
    Google signals streaming via the URL endpoint (`:streamGenerateContent`), not
    the body, so we check the upstream path as well.
    """
    if ":streamGenerateContent" in upstream_path:
        return True
    try:
        return bool(json.loads(body_bytes).get("stream", False))
    except Exception:
        return False


def _extract_usage_for_provider(
    provider_name: str, response_json: dict[str, Any]
) -> TokenUsage:
    if provider_name == "openai":
        return extract_usage_openai(response_json)
    if provider_name == "anthropic":
        return extract_usage_anthropic(response_json)
    if provider_name == "google":
        return extract_usage_google(response_json)
    return TokenUsage()


async def _log_record(db_path: str, record: RequestRecord) -> None:
    """Insert a RequestRecord into SQLite, logging errors but not raising."""
    try:
        await insert_request(db_path, record)
    except Exception as exc:
        logger.error("Failed to log request: %s", exc)


async def handle_request(
    client: httpx.AsyncClient,
    provider: ProviderConfig,
    path: str,
    method: str,
    headers: dict[str, str],
    body_bytes: bytes,
    query_string: str,
    db_path: str,
    alert_engine: "AlertEngine | None" = None,
) -> tuple[int, dict[str, str], bytes | None, AsyncIterator[bytes] | None]:
    """Forward a request upstream and return (status, headers, body, stream).

    Exactly one of body or stream will be non-None.
    Logging happens asynchronously so it never delays the caller.

    Returns:
        (status_code, response_headers, body_bytes_or_None, stream_or_None)
    """
    upstream_path = strip_proxy_prefix(path, provider)
    if query_string:
        upstream_path = f"{upstream_path}?{query_string}"

    tags = _extract_tags(headers)
    clean_headers = _clean_request_headers(headers)
    streaming = _is_streaming(body_bytes, upstream_path)

    model_from_path = _extract_model_from_path(upstream_path, provider.name)
    model = model_from_path or _extract_model(body_bytes, provider.name)
    system_hash = _hash_system_prompt(body_bytes)

    upstream_url = f"{provider.upstream_base}{upstream_path}"
    start_ms = time.monotonic()

    if streaming:
        return await _handle_streaming(
            client=client,
            upstream_url=upstream_url,
            method=method,
            headers=clean_headers,
            body_bytes=body_bytes,
            provider=provider,
            model=model,
            tags=tags,
            system_hash=system_hash,
            db_path=db_path,
            start_ms=start_ms,
            request_path=path,
            alert_engine=alert_engine,
        )
    else:
        return await _handle_non_streaming(
            client=client,
            upstream_url=upstream_url,
            method=method,
            headers=clean_headers,
            body_bytes=body_bytes,
            provider=provider,
            model=model,
            tags=tags,
            system_hash=system_hash,
            db_path=db_path,
            start_ms=start_ms,
            request_path=path,
            alert_engine=alert_engine,
        )


async def _handle_non_streaming(
    client: httpx.AsyncClient,
    upstream_url: str,
    method: str,
    headers: dict[str, str],
    body_bytes: bytes,
    provider: ProviderConfig,
    model: str,
    tags: dict[str, str],
    system_hash: str | None,
    db_path: str,
    start_ms: float,
    request_path: str,
    alert_engine: "AlertEngine | None" = None,
) -> tuple[int, dict[str, str], bytes, None]:
    """Forward a non-streaming request and log asynchronously."""
    response = await client.request(
        method=method,
        url=upstream_url,
        headers=headers,
        content=body_bytes,
    )
    duration_ms = int((time.monotonic() - start_ms) * 1000)

    resp_body = response.content
    _log_upstream_error_hint(response.status_code, resp_body, provider.name)
    usage = TokenUsage()
    try:
        resp_json = response.json()
        usage = _extract_usage_for_provider(provider.name, resp_json)
    except Exception:
        pass

    cost = calculate_cost(provider.name, model, usage)

    record = RequestRecord(
        provider=provider.name,
        model=model,
        request_path=request_path,
        timestamp=datetime.utcnow(),
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cost_usd=cost,
        duration_ms=duration_ms,
        status_code=response.status_code,
        tags=tags,
        system_prompt_hash=system_hash,
    )
    asyncio.create_task(_log_record(db_path, record))
    if alert_engine is not None:
        asyncio.create_task(alert_engine.check_and_dispatch())

    # Pass through response headers, stripping hop-by-hop and encoding headers
    # (httpx auto-decompresses, so content-encoding must not be forwarded).
    resp_headers = {
        k: v
        for k, v in response.headers.items()
        if k.lower() not in _STRIP_RESPONSE_HEADERS
    }

    return response.status_code, resp_headers, resp_body, None


async def _handle_streaming(
    client: httpx.AsyncClient,
    upstream_url: str,
    method: str,
    headers: dict[str, str],
    body_bytes: bytes,
    provider: ProviderConfig,
    model: str,
    tags: dict[str, str],
    system_hash: str | None,
    db_path: str,
    start_ms: float,
    request_path: str,
    alert_engine: "AlertEngine | None" = None,
) -> tuple[int, dict[str, str], None, AsyncIterator[bytes]]:
    """Forward a streaming request; log usage after stream ends."""
    req = client.build_request(
        method=method,
        url=upstream_url,
        headers=headers,
        content=body_bytes,
    )
    # httpx adds connection: keep-alive automatically; strip it so the proxy
    # never forwards hop-by-hop headers that belong to the client↔proxy leg.
    req = httpx.Request(
        req.method,
        req.url,
        headers={k: v for k, v in req.headers.items() if k.lower() not in _STRIP_REQUEST_HEADERS},
        content=req.content,
    )
    response = await client.send(req, stream=True)
    if response.status_code >= 400:
        err_body = await response.aread()
        _log_upstream_error_hint(response.status_code, err_body, provider.name)
        # Re-wrap as a plain response so the error body is forwarded correctly
        resp_headers = {
            k: v for k, v in response.headers.items()
            if k.lower() not in _STRIP_RESPONSE_HEADERS
        }
        await response.aclose()
        return response.status_code, resp_headers, err_body, None
    duration_ref: list[int] = [0]

    async def _stream_generator() -> AsyncIterator[bytes]:
        usage_chunk_data: list[str] = []
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
                chunk_str = chunk.decode("utf-8", errors="ignore")
                if should_buffer_chunk(chunk_str):
                    usage_chunk_data.append(chunk_str)
        finally:
            duration_ref[0] = int((time.monotonic() - start_ms) * 1000)
            await response.aclose()
            asyncio.create_task(
                _log_streaming_usage(
                    usage_chunks=usage_chunk_data,
                    provider=provider,
                    model=model,
                    tags=tags,
                    system_hash=system_hash,
                    db_path=db_path,
                    duration_ms=duration_ref[0],
                    status_code=response.status_code,
                    request_path=request_path,
                    alert_engine=alert_engine,
                )
            )

    resp_headers = {
        k: v
        for k, v in response.headers.items()
        if k.lower() not in _STRIP_RESPONSE_HEADERS
    }

    return response.status_code, resp_headers, None, _stream_generator()


async def _log_streaming_usage(
    usage_chunks: list[str],
    provider: ProviderConfig,
    model: str,
    tags: dict[str, str],
    system_hash: str | None,
    db_path: str,
    duration_ms: int,
    status_code: int,
    request_path: str,
    alert_engine: "AlertEngine | None" = None,
) -> None:
    """Parse usage from accumulated streaming chunks and log to SQLite."""
    usage = extract_usage_from_stream(provider.name, usage_chunks)

    cost = calculate_cost(provider.name, model, usage)

    record = RequestRecord(
        provider=provider.name,
        model=model,
        request_path=request_path,
        timestamp=datetime.utcnow(),
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cost_usd=cost,
        duration_ms=duration_ms,
        status_code=status_code,
        tags=tags,
        system_prompt_hash=system_hash,
    )
    await _log_record(db_path, record)
    if alert_engine is not None:
        asyncio.create_task(alert_engine.check_and_dispatch())
