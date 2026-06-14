"""Request/response interception: tag extraction, forwarding, logging, cost."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncIterator

import httpx

from burnlens.cost.calculator import (
    TokenUsage,
    calculate_cost,
)
from burnlens.providers.base import Provider
from burnlens.proxy.providers import strip_proxy_prefix
from burnlens.proxy.streaming import extract_usage_from_stream, split_sse_events
from burnlens.storage.database import insert_request
from burnlens.storage.models import RequestRecord

if TYPE_CHECKING:
    from burnlens.alerts.engine import AlertEngine
    from burnlens.config import ApiKeyBudgetsConfig, BurnLensConfig, CustomerBudgetsConfig
    from burnlens.proxy.router import RouteDecision
    from burnlens.storage.wal import WriteAheadLog, SQLitePersistenceWorker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Customer spend cache (60-second TTL to avoid DB hit on every request)
# ---------------------------------------------------------------------------

_customer_spend_cache: dict[str, tuple[float, float]] = {}  # customer -> (spend, timestamp)
_CUSTOMER_CACHE_TTL = 60.0  # seconds


def _get_cached_customer_spend(customer: str) -> float | None:
    """Return cached spend for a customer, or None if cache miss/expired."""
    entry = _customer_spend_cache.get(customer)
    if entry is None:
        return None
    spend, cached_at = entry
    if time.monotonic() - cached_at > _CUSTOMER_CACHE_TTL:
        del _customer_spend_cache[customer]
        return None
    return spend


def _set_cached_customer_spend(customer: str, spend: float) -> None:
    """Cache the spend value for a customer."""
    _customer_spend_cache[customer] = (spend, time.monotonic())


async def check_customer_budget(
    customer: str,
    db_path: str,
    customer_budgets: "CustomerBudgetsConfig",
) -> tuple[bool, float, float]:
    """Check if customer is within budget.

    Returns (allowed, spent, limit). If no budget applies, allowed is True.
    """
    # Determine budget limit for this customer
    limit = customer_budgets.customers.get(customer)
    if limit is None:
        limit = customer_budgets.default
    if limit is None:
        return True, 0.0, 0.0

    # Check cache first
    spent = _get_cached_customer_spend(customer)
    if spent is None:
        from burnlens.storage.database import get_spend_by_customer_this_month
        all_spend = await get_spend_by_customer_this_month(db_path)
        spent = all_spend.get(customer, 0.0)
        _set_cached_customer_spend(customer, spent)

    return spent < limit, spent, limit

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


_ENV_TAG_FALLBACKS: tuple[str, ...] = (
    "feature",
    "team",
    "customer",
    "repo",
    "dev",
    "pr",
    "branch",
)


# Canonical tags allowed for extraction from headers and environment.
# Restricting this prevents "tag injection" where malicious headers spoof budget/org context.
_ALLOWED_TAGS = {
    "team", "feature", "app_id", "env", "repo", "branch", "commit_sha",
    "workspace_id", "org_id", "trace_id", "customer", "key_label", "dev", "pr"
}


def _extract_tags(headers: dict[str, str]) -> dict[str, str]:
    """Pull X-BurnLens-Tag-* headers into a plain dict.

    Only tags in :data:`_ALLOWED_TAGS` are extracted. Values are truncated
    to 100 chars for safety.
    """
    import os

    prefix = "x-burnlens-tag-"
    tags: dict[str, str] = {}
    
    # 1. Extract from headers (case-insensitive keys)
    for key, value in headers.items():
        k_lower = key.lower()
        if k_lower.startswith(prefix):
            tag_name = k_lower[len(prefix):]
            if tag_name in _ALLOWED_TAGS:
                # Basic value sanitization: truncate and strip
                tags[tag_name] = value.strip()[:100]

    # 2. Fall back to environment for missing allowed tags
    for tag in _ALLOWED_TAGS:
        if tag in tags:
            continue
        env_value = os.environ.get(f"BURNLENS_TAG_{tag.upper()}")
        if env_value:
            tags[tag] = env_value.strip()[:100]

    return tags


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
    """Kept for backward compat; new call sites use provider.extract_usage()."""
    from burnlens.providers.registry import get as _get_provider
    try:
        return _get_provider(provider_name).extract_usage(response_json)
    except KeyError:
        return TokenUsage()


async def _log_record(db_path: str, record: RequestRecord) -> None:
    """Insert a RequestRecord into SQLite, logging errors but not raising."""
    try:
        await insert_request(db_path, record)
    except Exception as exc:
        logger.error("Failed to log request: %s", exc)
        return

    # CODE-2: every fresh row for a registered key invalidates the cached
    # daily-spend so the next request re-queries SQLite. Cheap, idempotent.
    label = (record.tags or {}).get("key_label")
    if label:
        try:
            from burnlens.key_budget import spend_cache
            spend_cache.invalidate(label)
        except Exception as exc:
            logger.debug("Spend cache invalidate failed: %s", exc)


def _extract_api_key_hash(headers: dict[str, str]) -> str | None:
    """Return SHA-256 hash of the API key from a known auth header.

    Supports OpenAI-style ``Authorization: Bearer <token>``, Anthropic-style
    ``x-api-key: <token>``, and Google-style ``x-goog-api-key: <token>``.
    Returns None if no recognised auth header is present.

    Args:
        headers: Request headers (keys may be mixed-case).
    """
    lower_headers = {k.lower(): v for k, v in headers.items()}

    auth = lower_headers.get("authorization")
    if auth:
        token = auth.removeprefix("Bearer ").removeprefix("bearer ").strip()
        if token:
            return hashlib.sha256(token.encode()).hexdigest()

    for header_name in ("x-api-key", "x-goog-api-key"):
        api_key = lower_headers.get(header_name)
        if api_key and api_key.strip():
            return hashlib.sha256(api_key.strip().encode()).hexdigest()

    return None


async def _upsert_asset(
    db_path: str,
    provider_name: str,
    model: str,
    endpoint_url: str,
    api_key_hash: str | None,
) -> None:
    """Call upsert_asset_from_detection, logging warnings on failure (fail open).

    Args:
        db_path: Path to the BurnLens SQLite database.
        provider_name: Provider identifier (e.g. "openai").
        model: Model name extracted from the request.
        endpoint_url: Upstream API base URL used for this request.
        api_key_hash: SHA-256 hash of the API key, or None.
    """
    try:
        from burnlens.detection.classifier import upsert_asset_from_detection
        await upsert_asset_from_detection(db_path, provider_name, model, endpoint_url, api_key_hash)
    except Exception as exc:
        logger.warning("Asset upsert failed (non-fatal): %s", exc)


async def handle_request(
    client: httpx.AsyncClient,
    provider: Provider,
    path: str,
    method: str,
    headers: dict[str, str],
    body_bytes: bytes,
    query_string: str,
    db_path: str,
    alert_engine: "AlertEngine | None" = None,
    customer_budgets: "CustomerBudgetsConfig | None" = None,
    api_key_budgets: "ApiKeyBudgetsConfig | None" = None,
    config: "BurnLensConfig | None" = None,
    wal: "WriteAheadLog | None" = None,
    worker: "SQLitePersistenceWorker | None" = None,
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

    # --- CODE-2: resolve the API-key label for this request ---
    # SHA-256 the auth header, look up the matching label in api_keys, and
    # write it to tags["key_label"]. Stored as tag_key_label on the request
    # row so the dashboard and `burnlens keys today` can group by label.
    api_key_hash = _extract_api_key_hash(headers)
    label: str | None = None
    if api_key_hash:
        try:
            from burnlens.keys import get_label_by_hash, touch_last_used
            label = await get_label_by_hash(db_path, api_key_hash)
            if label:
                tags["key_label"] = label
                # Fire-and-forget so we don't add latency to the proxy.
                asyncio.create_task(touch_last_used(db_path, label))
        except Exception as exc:  # fail-open: never break the proxy
            logger.debug("API key label lookup failed: %s", exc)

    # --- CODE-2: per-API-key daily hard cap (BEFORE forwarding) ---
    if label and api_key_budgets is not None:
        try:
            from burnlens.key_budget import enforce_daily_cap
            breach = await enforce_daily_cap(label, db_path, api_key_budgets)
        except Exception as exc:  # fail-open
            logger.debug("Daily cap check failed: %s", exc)
            breach = None
        if breach is not None:
            spent_today, daily_limit, resets_at = breach
            reject_body = json.dumps({
                "error": "daily_budget_exceeded",
                "key": label,
                "spent_today": round(spent_today, 4),
                "daily_limit": round(daily_limit, 4),
                "resets_at": resets_at.isoformat(),
            }).encode()
            return 429, {"content-type": "application/json"}, reject_body, None

    # --- Customer budget enforcement (BEFORE forwarding) ---
    customer = tags.get("customer")
    if customer and customer_budgets:
        allowed, spent, limit = await check_customer_budget(
            customer, db_path, customer_budgets,
        )
        if not allowed:
            reject_body = json.dumps({
                "error": "budget_exceeded",
                "customer": customer,
                "spent": round(spent, 2),
                "limit": round(limit, 2),
            }).encode()
            return 429, {"content-type": "application/json"}, reject_body, None

    clean_headers = _clean_request_headers(headers)
    streaming = _is_streaming(body_bytes, upstream_path)

    model_from_path = _extract_model_from_path(upstream_path, provider.name)
    model = model_from_path or _extract_model(body_bytes, provider.name)
    system_hash = _hash_system_prompt(body_bytes)

    # --- Phase 7: Semantic Cache Check ---
    cache_enabled = config.cache.enabled if config else False
    cache_bypass = False
    if headers:
        cc = headers.get("cache-control") or headers.get("Cache-Control") or ""
        if "no-cache" in cc or "no-store" in cc:
            cache_bypass = True
    if query_string:
        if "nocache=true" in query_string or "nocache=1" in query_string:
            cache_bypass = True

    if cache_enabled and not cache_bypass and method.upper() == "POST":
        try:
            from burnlens.cache.manager import extract_query_text, SemanticCacheManager
            query_text = extract_query_text(body_bytes, provider.name)
            
            import hashlib
            customer_hash = hashlib.sha256(customer.encode()).hexdigest() if customer else None
            
            cache_manager = SemanticCacheManager(db_path, secret_key=config.secret_key)
            
            # Stage 1: Exact Match Check
            cache_hit_res = await cache_manager.lookup_exact(system_hash or "", query_text, customer_hash)
            
            # Stage 2: Semantic Match Check
            if not cache_hit_res:
                try:
                    from burnlens.cache.embeddings import get_embedding
                    query_embedding = await get_embedding(
                        text=query_text,
                        config=config,
                        request_provider=provider.name,
                        request_headers=headers,
                        request_query=query_string
                    )
                    if query_embedding:
                        cache_hit_res = await cache_manager.lookup_semantic(
                            system_prompt_hash=system_hash or "",
                            query_text=query_text,
                            query_embedding=query_embedding,
                            customer_hash=customer_hash,
                            similarity_threshold=config.cache.similarity_threshold,
                        )
                except Exception as emb_exc:
                    logger.debug("Embedding lookup failed (fail-open): %s", emb_exc)

            if cache_hit_res:
                hit_body, hit_provider, hit_model = cache_hit_res
                
                # Async logging task for cache hit
                asyncio.create_task(_log_cache_hit(
                    provider_name=hit_provider,
                    model=hit_model,
                    request_path=path,
                    body_bytes=body_bytes,
                    response_body=hit_body,
                    system_hash=system_hash,
                    customer_hash=customer_hash,
                    tags=tags,
                    db_path=db_path,
                    wal=wal,
                    worker=worker,
                    original_headers=headers
                ))
                
                if streaming:
                    from burnlens.cache.manager import reconstruct_streaming_chunks
                    stream_iter = reconstruct_streaming_chunks(hit_provider, hit_body)
                    return 200, {"content-type": "text/event-stream"}, None, stream_iter
                else:
                    return 200, {"content-type": "application/json"}, hit_body, None
        except Exception as cache_exc:
            logger.warning("Cache pipeline failed (fail-open): %s", cache_exc)

    # --- Budget-aware model downgrade routing (per D-04) ---
    decision: "RouteDecision | None" = None
    if config is not None:
        from burnlens.proxy.router import decide_route  # type: ignore[assignment]
        decision = await decide_route(
            model, tags.get("team"), tags.get("customer"), config, db_path
        )
        if decision.downgraded:
            # 1. URL-path rewrite (polymorphic Provider hook — per ROUTE-08 / phase 17).
            #    No-op for OpenAI/Anthropic (default base implementation); Google
            #    rewrites /v1beta/models/{model}:generateContent. The hook is a
            #    pure regex substitution on str — cannot raise on valid input,
            #    so it sits outside the try/except by design.
            upstream_path = provider.rewrite_path_for_routing(
                upstream_path, decision.routed_model
            )
            # 2. Body rewrite — guarded by 'model' key presence. Google bodies
            #    have no 'model' field so this naturally skips for them; OpenAI
            #    and Anthropic bodies always include it, so behavior is preserved.
            try:
                body_dict = json.loads(body_bytes)
                if "model" in body_dict:
                    body_dict["model"] = decision.routed_model
                    body_bytes = json.dumps(body_dict).encode()
            except Exception:
                pass  # fail open — use original body unmodified
            model = decision.routed_model
            if getattr(config.routing, "log_downgrades", True):
                logger.info(
                    "[BurnLens] Downgraded %s → %s | Budget remaining: $%.4f (%.1f%%)",
                    decision.original_model,
                    decision.routed_model,
                    decision.budget_remaining_usd,
                    decision.budget_remaining_pct,
                )

    # --- Phase 4: Budget Engine v2 Hierarchical Budget Policies ---
    reservation = None
    if config is not None and config.budget_policies:
        meta = _resolve_canonical_metadata(headers, tags)
        request_context = {
            "org_id": meta.get("org_id"),
            "team": meta.get("team") or tags.get("team"),
            "app_id": meta.get("app_id") or tags.get("app_id"),
            "customer": meta.get("customer") or tags.get("customer"),
            "model": model,
        }
        try:
            from burnlens.budget_engine import BudgetEngine
            engine = BudgetEngine(config, db_path)
            allowed, reservation = await engine.check_and_reserve(
                provider.name, model, body_bytes, request_context
            )
            if not allowed:
                violated = reservation["violated_policy"]
                reject_body = json.dumps({
                    "error": "budget_policy_exceeded",
                    "policy_name": violated.name,
                    "scope": violated.scope,
                    "target": violated.target,
                    "limit_usd": violated.limit_usd,
                    "estimated_cost_usd": reservation["estimated_cost"],
                }).encode()
                return 429, {"content-type": "application/json"}, reject_body, None
        except Exception as exc:
            logger.debug("Budget policy check failed (fail-open): %s", exc)

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
            original_headers=headers,
            decision=decision,
            wal=wal,
            worker=worker,
            config=config,
            reservation=reservation,
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
            original_headers=headers,
            decision=decision,
            wal=wal,
            worker=worker,
            config=config,
            reservation=reservation,
        )


async def _handle_non_streaming(
    client: httpx.AsyncClient,
    upstream_url: str,
    method: str,
    headers: dict[str, str],
    body_bytes: bytes,
    provider: Provider,
    model: str,
    tags: dict[str, str],
    system_hash: str | None,
    db_path: str,
    start_ms: float,
    request_path: str,
    alert_engine: "AlertEngine | None" = None,
    original_headers: dict[str, str] | None = None,
    decision: "RouteDecision | None" = None,
    wal: "WriteAheadLog | None" = None,
    worker: "SQLitePersistenceWorker | None" = None,
    config: "BurnLensConfig | None" = None,
    reservation: dict[str, Any] | None = None,
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

    # Save to semantic cache if enabled (Phase 7)
    cache_enabled = config.cache.enabled if config else False
    cache_bypass = False
    if original_headers:
        cc = original_headers.get("cache-control") or original_headers.get("Cache-Control") or ""
        if "no-cache" in cc or "no-store" in cc:
            cache_bypass = True
    if method.upper() == "POST" and response.status_code == 200 and cache_enabled and not cache_bypass:
        try:
            from burnlens.cache.manager import extract_query_text
            query_text = extract_query_text(body_bytes, provider.name)
            import hashlib
            customer = tags.get("customer")
            customer_hash = hashlib.sha256(customer.encode()).hexdigest() if customer else None
            
            asyncio.create_task(_save_to_cache_bg(
                config=config,
                db_path=db_path,
                system_hash=system_hash,
                query_text=query_text,
                provider_name=provider.name,
                model=model,
                response_body=resp_body,
                customer_hash=customer_hash,
                tags=tags,
                request_headers=original_headers or headers,
            ))
        except Exception as cache_exc:
            logger.debug("Failed to start background cache save: %s", cache_exc)

    # Reconcile budget policy counters
    if reservation and config:
        try:
            from burnlens.budget_engine import BudgetEngine
            engine = BudgetEngine(config, db_path)
            reconcile_cost = cost if response.status_code < 400 else 0.0
            await engine.reconcile(reconcile_cost, reservation)
        except Exception as exc:
            logger.debug("Budget reconciliation failed: %s", exc)

    from burnlens.storage.models import uuid7
    from burnlens.cost.pricing import get_pricing_version

    meta = _resolve_canonical_metadata(original_headers or headers, tags)
    pricing_version = get_pricing_version(provider.name)

    # Phase 6: Local tokenization & classification
    try:
        from burnlens.analysis.prompt_analyzer import analyze_request_prompt
        prompt_analysis = analyze_request_prompt(
            provider.name, model, body_bytes, usage.input_tokens
        )
    except Exception as exc:
        logger.debug("Prompt analysis failed (non-fatal): %s", exc)
        prompt_analysis = {
            "prompt_system_tokens": 0,
            "prompt_user_tokens": usage.input_tokens,
            "prompt_tools_tokens": 0,
            "prompt_rag_tokens": 0,
            "prompt_history_tokens": 0,
        }

    record = RequestRecord(
        provider=provider.name,
        model=model,
        request_path=request_path,
        timestamp=datetime.now(timezone.utc),
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
        prompt_system_tokens=prompt_analysis["prompt_system_tokens"],
        prompt_user_tokens=prompt_analysis["prompt_user_tokens"],
        prompt_tools_tokens=prompt_analysis["prompt_tools_tokens"],
        prompt_rag_tokens=prompt_analysis["prompt_rag_tokens"],
        prompt_history_tokens=prompt_analysis["prompt_history_tokens"],
        # Phase 1: Canonical event fields
        event_id=uuid7(),
        request_id=_extract_request_id(provider.name, response.headers, resp_body),
        trace_id=meta["trace_id"],
        workspace_id=meta["workspace_id"],
        org_id=meta["org_id"],
        team=meta["team"],
        feature=meta["feature"],
        customer_hash=meta["customer_hash"],
        app_id=meta["app_id"],
        env=meta["env"],
        repo=meta["repo"],
        branch=meta["branch"],
        commit_sha=meta["commit_sha"],
        pricing_version=pricing_version,
    )
    # Persist routing decision fields (per D-05)
    if decision is not None:
        record.routed_model = decision.routed_model
        record.downgrade_reason = decision.reason if decision.downgraded else None
        record.budget_remaining_usd = decision.budget_remaining_usd if decision.downgraded else None
        record.budget_remaining_pct = decision.budget_remaining_pct if decision.downgraded else None
    else:
        record.routed_model = model  # same as model when no routing
        record.downgrade_reason = None
        record.budget_remaining_usd = None
        record.budget_remaining_pct = None

    # Emit OTEL span and metrics immediately
    try:
        from burnlens.telemetry.otel import emit_span, emit_metrics
        emit_span(record, original_headers or headers)
        emit_metrics(record.to_event())
    except Exception as exc:
        logger.debug("OTEL telemetry emit failed: %s", exc)

    if wal is not None and worker is not None:
        async def _log_via_wal():
            try:
                await wal.append_event(record)
                await worker.enqueue(record)
            except Exception as e:
                logger.error("WAL append/enqueue failed: %s", e)
                # Fallback to direct insertion so we fail open
                asyncio.create_task(_log_record(db_path, record))
        asyncio.create_task(_log_via_wal())
    else:
        asyncio.create_task(_log_record(db_path, record))

    # Async non-blocking asset upsert (runs in same event loop, does not add latency)
    api_key_hash = _extract_api_key_hash(original_headers or headers)
    endpoint_url = provider.upstream_base
    asyncio.create_task(
        _upsert_asset(db_path, provider.name, model, endpoint_url, api_key_hash)
    )

    if alert_engine is not None:
        asyncio.create_task(alert_engine.check_and_dispatch())
        asyncio.create_task(alert_engine.check_and_dispatch_key_budgets())

    if config is not None:
        _run_anomaly_detection(record, config, db_path)


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
    provider: Provider,
    model: str,
    tags: dict[str, str],
    system_hash: str | None,
    db_path: str,
    start_ms: float,
    request_path: str,
    alert_engine: "AlertEngine | None" = None,
    original_headers: dict[str, str] | None = None,
    decision: "RouteDecision | None" = None,
    wal: "WriteAheadLog | None" = None,
    worker: "SQLitePersistenceWorker | None" = None,
    config: "BurnLensConfig | None" = None,
    reservation: dict[str, Any] | None = None,
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
        # Reconcile budget policy counters on failure (refund reservation)
        if reservation and config:
            try:
                from burnlens.budget_engine import BudgetEngine
                engine = BudgetEngine(config, db_path)
                await engine.reconcile(0.0, reservation)
            except Exception as exc:
                logger.debug("Budget reconciliation failed for streaming error: %s", exc)
        return response.status_code, resp_headers, err_body, None
    duration_ref: list[int] = [0]

    api_key_hash = _extract_api_key_hash(original_headers or headers)
    endpoint_url = provider.upstream_base

    from burnlens.storage.models import uuid7
    from burnlens.cost.pricing import get_pricing_version

    meta = _resolve_canonical_metadata(original_headers or headers, tags)
    pricing_version = get_pricing_version(provider.name)
    event_id = uuid7()
    request_id = _extract_request_id(provider.name, response.headers, None)

    async def _stream_generator() -> AsyncIterator[bytes]:
        raw_buffer = ""
        first_chunk_received = False
        ttft_ms = None
        try:
            async for chunk in response.aiter_bytes():
                if not first_chunk_received:
                    first_chunk_received = True
                    ttft_ms = int((time.monotonic() - start_ms) * 1000)
                yield chunk
                raw_buffer += chunk.decode("utf-8", errors="ignore")
        finally:
            duration_ref[0] = int((time.monotonic() - start_ms) * 1000)
            await response.aclose()
            # Split the accumulated buffer into complete SSE events,
            # keeping only those that contain usage data.  This handles
            # TCP chunk fragmentation that previously lost tokens.
            usage_events = split_sse_events(raw_buffer)
            asyncio.create_task(
                _log_streaming_usage(
                    usage_chunks=usage_events,
                    provider=provider,
                    model=model,
                    tags=tags,
                    system_hash=system_hash,
                    db_path=db_path,
                    duration_ms=duration_ref[0],
                    status_code=response.status_code,
                    request_path=request_path,
                    alert_engine=alert_engine,
                    decision=decision,
                    event_id=event_id,
                    request_id=request_id,
                    meta=meta,
                    pricing_version=pricing_version,
                    wal=wal,
                    worker=worker,
                    ttft_ms=ttft_ms,
                    original_headers=original_headers or headers,
                    config=config,
                    reservation=reservation,
                    body_bytes=body_bytes,
                )
            )
            # Async non-blocking asset upsert after stream completes
            asyncio.create_task(
                _upsert_asset(db_path, provider.name, model, endpoint_url, api_key_hash)
            )

    resp_headers = {
        k: v
        for k, v in response.headers.items()
        if k.lower() not in _STRIP_RESPONSE_HEADERS
    }

    return response.status_code, resp_headers, None, _stream_generator()


async def _log_streaming_usage(
    usage_chunks: list[str],
    provider: Provider,
    model: str,
    tags: dict[str, str],
    system_hash: str | None,
    db_path: str,
    duration_ms: int,
    status_code: int,
    request_path: str,
    alert_engine: "AlertEngine | None" = None,
    decision: "RouteDecision | None" = None,
    event_id: str | None = None,
    request_id: str | None = None,
    meta: dict[str, str | None] | None = None,
    pricing_version: str | None = None,
    wal: "WriteAheadLog | None" = None,
    worker: "SQLitePersistenceWorker | None" = None,
    ttft_ms: float | None = None,
    original_headers: dict[str, str] | None = None,
    config: "BurnLensConfig | None" = None,
    reservation: dict[str, Any] | None = None,
    body_bytes: bytes | None = None,
) -> None:
    """Parse usage from accumulated streaming chunks and log to SQLite."""
    usage = extract_usage_from_stream(provider.name, usage_chunks)

    cost = calculate_cost(provider.name, model, usage)

    # Save streaming response to semantic cache (Phase 7)
    cache_enabled = config.cache.enabled if config else False
    cache_bypass = False
    if original_headers:
        cc = original_headers.get("cache-control") or original_headers.get("Cache-Control") or ""
        if "no-cache" in cc or "no-store" in cc:
            cache_bypass = True
    if status_code == 200 and cache_enabled and not cache_bypass:
        try:
            from burnlens.cache.manager import extract_query_text, reconstruct_complete_response_from_chunks
            query_text = extract_query_text(body_bytes, provider.name)
            
            reconstructed_body = reconstruct_complete_response_from_chunks(provider.name, usage_chunks)
            if reconstructed_body:
                import hashlib
                customer = tags.get("customer")
                customer_hash = hashlib.sha256(customer.encode()).hexdigest() if customer else None
                
                asyncio.create_task(_save_to_cache_bg(
                    config=config,
                    db_path=db_path,
                    system_hash=system_hash,
                    query_text=query_text,
                    provider_name=provider.name,
                    model=model,
                    response_body=reconstructed_body,
                    customer_hash=customer_hash,
                    tags=tags,
                    request_headers=original_headers,
                ))
        except Exception as cache_exc:
            logger.debug("Failed to start background cache save for stream: %s", cache_exc)

    # Reconcile budget policy counters
    if reservation and config:
        try:
            from burnlens.budget_engine import BudgetEngine
            engine = BudgetEngine(config, db_path)
            reconcile_cost = cost if status_code < 400 else 0.0
            await engine.reconcile(reconcile_cost, reservation)
        except Exception as exc:
            logger.debug("Budget reconciliation failed: %s", exc)

    if not request_id:
        request_id = _extract_request_id_from_chunks(usage_chunks)

    # Phase 6: Local tokenization & classification
    try:
        from burnlens.analysis.prompt_analyzer import analyze_request_prompt
        prompt_analysis = analyze_request_prompt(
            provider.name, model, body_bytes, usage.input_tokens
        )
    except Exception as exc:
        logger.debug("Prompt analysis failed (non-fatal): %s", exc)
        prompt_analysis = {
            "prompt_system_tokens": 0,
            "prompt_user_tokens": usage.input_tokens,
            "prompt_tools_tokens": 0,
            "prompt_rag_tokens": 0,
            "prompt_history_tokens": 0,
        }

    record = RequestRecord(
        provider=provider.name,
        model=model,
        request_path=request_path,
        timestamp=datetime.now(timezone.utc),
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
        prompt_system_tokens=prompt_analysis["prompt_system_tokens"],
        prompt_user_tokens=prompt_analysis["prompt_user_tokens"],
        prompt_tools_tokens=prompt_analysis["prompt_tools_tokens"],
        prompt_rag_tokens=prompt_analysis["prompt_rag_tokens"],
        prompt_history_tokens=prompt_analysis["prompt_history_tokens"],
        # Phase 1 fields
        event_id=event_id,
        request_id=request_id,
        trace_id=meta.get("trace_id") if meta else None,
        workspace_id=meta.get("workspace_id") if meta else None,
        org_id=meta.get("org_id") if meta else None,
        team=meta.get("team") if meta else None,
        feature=meta.get("feature") if meta else None,
        customer_hash=meta.get("customer_hash") if meta else None,
        app_id=meta.get("app_id") if meta else None,
        env=meta.get("env") if meta else None,
        repo=meta.get("repo") if meta else None,
        branch=meta.get("branch") if meta else None,
        commit_sha=meta.get("commit_sha") if meta else None,
        pricing_version=pricing_version,
        ttft_ms=ttft_ms,
    )
    # Emit OTEL telemetry immediately
    try:
        from burnlens.telemetry.otel import emit_span, emit_metrics
        emit_span(record, original_headers)
        emit_metrics(record.to_event())
    except Exception as exc:
        logger.debug("OTEL telemetry emit failed: %s", exc)

    # Persist routing decision fields (per D-05)
    if decision is not None:
        record.routed_model = decision.routed_model
        record.downgrade_reason = decision.reason if decision.downgraded else None
        record.budget_remaining_usd = decision.budget_remaining_usd if decision.downgraded else None
        record.budget_remaining_pct = decision.budget_remaining_pct if decision.downgraded else None
    else:
        record.routed_model = model  # same as model when no routing
        record.downgrade_reason = None
        record.budget_remaining_usd = None
        record.budget_remaining_pct = None
    if wal is not None and worker is not None:
        async def _log_via_wal():
            try:
                await wal.append_event(record)
                await worker.enqueue(record)
            except Exception as e:
                logger.error("WAL append/enqueue failed: %s", e)
                asyncio.create_task(_log_record(db_path, record))
        asyncio.create_task(_log_via_wal())
    else:
        asyncio.create_task(_log_record(db_path, record))
    if alert_engine is not None:
        asyncio.create_task(alert_engine.check_and_dispatch())
        asyncio.create_task(alert_engine.check_and_dispatch_key_budgets())

    if config is not None:
        _run_anomaly_detection(record, config, db_path)



def _extract_trace_id(headers: dict[str, str], tags: dict[str, str]) -> str | None:
    """Extract OpenTelemetry trace ID from traceparent header or custom headers/tags."""
    headers_lower = {k.lower(): v for k, v in headers.items()}
    traceparent = headers_lower.get("traceparent")
    if traceparent:
        parts = traceparent.split("-")
        if len(parts) >= 2 and len(parts[1]) == 32:
            return parts[1]

    for key in ("x-trace-id", "x-correlation-id", "trace_id", "trace-id"):
        val = headers_lower.get(key)
        if val:
            return val
        val = tags.get(key.replace("-", "_"))
        if val:
            return val
    return None


_cached_git_context: dict[str, str] | None = None


def _get_git_context() -> dict[str, str]:
    """Lazy load and cache git context to avoid subprocess overhead on the hot path."""
    global _cached_git_context
    if _cached_git_context is None:
        try:
            from burnlens.git_context import read_git_context
            _cached_git_context = read_git_context()
        except Exception:
            _cached_git_context = {}
    return _cached_git_context


def _resolve_canonical_metadata(headers: dict[str, str], tags: dict[str, str]) -> dict[str, str | None]:
    """Extract and resolve canonical event metadata fields."""
    import os
    import hashlib

    headers_lower = {k.lower(): v for k, v in headers.items()}

    trace_id = _extract_trace_id(headers, tags)

    workspace_id = (
        headers_lower.get("x-burnlens-workspace-id")
        or tags.get("workspace_id")
        or os.environ.get("BURNLENS_WORKSPACE_ID")
        or os.environ.get("BURNLENS_TAG_WORKSPACE")
    )

    org_id = (
        headers_lower.get("x-burnlens-org-id")
        or tags.get("org_id")
        or os.environ.get("BURNLENS_ORG_ID")
        or os.environ.get("BURNLENS_TAG_ORG_ID")
    )

    team = tags.get("team") or os.environ.get("BURNLENS_TAG_TEAM")
    feature = tags.get("feature") or os.environ.get("BURNLENS_TAG_FEATURE")

    customer = tags.get("customer") or os.environ.get("BURNLENS_TAG_CUSTOMER")
    customer_hash = None
    if customer:
        customer_hash = hashlib.sha256(customer.encode()).hexdigest()

    app_id = (
        headers_lower.get("x-burnlens-app-id")
        or tags.get("app_id")
        or os.environ.get("BURNLENS_APP_ID")
        or os.environ.get("BURNLENS_TAG_APP_ID")
    )
    env = (
        headers_lower.get("x-burnlens-env")
        or tags.get("env")
        or os.environ.get("BURNLENS_ENV")
        or os.environ.get("BURNLENS_TAG_ENV")
    )

    git_ctx = _get_git_context()

    repo = tags.get("repo") or os.environ.get("BURNLENS_TAG_REPO") or git_ctx.get("repo")
    branch = tags.get("branch") or os.environ.get("BURNLENS_TAG_BRANCH") or git_ctx.get("branch")
    commit_sha = (
        tags.get("commit_sha")
        or os.environ.get("BURNLENS_COMMIT_SHA")
        or os.environ.get("BURNLENS_TAG_COMMIT_SHA")
        or git_ctx.get("commit_sha")
    )

    return {
        "trace_id": trace_id,
        "workspace_id": workspace_id,
        "org_id": org_id,
        "team": team,
        "feature": feature,
        "customer_hash": customer_hash,
        "app_id": app_id,
        "env": env,
        "repo": repo,
        "branch": branch,
        "commit_sha": commit_sha,
    }



def _extract_request_id(provider_name: str, response_headers: dict[str, str], response_body_bytes: bytes | None) -> str | None:
    """Extract request ID from response body or response headers."""
    if response_body_bytes:
        try:
            body = json.loads(response_body_bytes)
            if isinstance(body, dict):
                body_id = body.get("id")
                if body_id and isinstance(body_id, str):
                    return body_id
        except Exception:
            pass

    headers_lower = {k.lower(): v for k, v in response_headers.items()}
    for h in ("x-request-id", "request-id", "x-goog-correlation-id", "x-amzn-requestid", "apihdr-request-id"):
        val = headers_lower.get(h)
        if val:
            return val
    return None


def _extract_request_id_from_chunks(chunks: list[str]) -> str | None:
    """Scan SSE chunks to extract the request ID."""
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
                req_id = data.get("id")
                if req_id and isinstance(req_id, str):
                    return req_id
            except Exception:
                pass
    return None


def _run_anomaly_detection(record: RequestRecord, config: Any, db_path: str) -> None:
    try:
        from burnlens.detection.anomaly import AnomalyDetector
        detector = AnomalyDetector(config, db_path)
        asyncio.create_task(detector.check_request(record))
    except Exception as exc:
        logger.debug("Failed to start anomaly detection task: %s", exc)


async def _log_cache_hit(
    provider_name: str,
    model: str,
    request_path: str,
    body_bytes: bytes,
    response_body: bytes,
    system_hash: str | None,
    customer_hash: str | None,
    tags: dict[str, str],
    db_path: str,
    wal: "WriteAheadLog | None",
    worker: "SQLitePersistenceWorker | None",
    original_headers: dict[str, str] | None = None,
):
    try:
        from burnlens.providers.registry import get as _get_provider
        from burnlens.cost.calculator import calculate_cost, TokenUsage
        from burnlens.storage.models import uuid7, RequestRecord
        from burnlens.cost.pricing import get_pricing_version
        
        provider = _get_provider(provider_name)
        usage = TokenUsage()
        try:
            resp_json = json.loads(response_body)
            if provider:
                usage = provider.extract_usage(resp_json)
        except Exception:
            pass

        # Calculate saved cost
        saved_cost = calculate_cost(provider_name, model, usage)

        # Analyze prompt segment tokens (Phase 6)
        try:
            from burnlens.analysis.prompt_analyzer import analyze_request_prompt
            prompt_analysis = analyze_request_prompt(
                provider_name, model, body_bytes, usage.input_tokens
            )
        except Exception:
            prompt_analysis = {
                "prompt_system_tokens": 0,
                "prompt_user_tokens": usage.input_tokens,
                "prompt_tools_tokens": 0,
                "prompt_rag_tokens": 0,
                "prompt_history_tokens": 0,
            }

        pricing_version = get_pricing_version(provider_name)
        meta = _resolve_canonical_metadata(original_headers or {}, tags)

        record = RequestRecord(
            provider=provider_name,
            model=model,
            request_path=request_path,
            timestamp=datetime.now(timezone.utc),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            cost_usd=0.0,  # Actual cost is 0
            duration_ms=0,
            status_code=200,
            tags=tags,
            system_prompt_hash=system_hash,
            prompt_system_tokens=prompt_analysis["prompt_system_tokens"],
            prompt_user_tokens=prompt_analysis["prompt_user_tokens"],
            prompt_tools_tokens=prompt_analysis["prompt_tools_tokens"],
            prompt_rag_tokens=prompt_analysis["prompt_rag_tokens"],
            prompt_history_tokens=prompt_analysis["prompt_history_tokens"],
            cache_hit=1,
            cache_saved_usd=saved_cost,
            event_id=uuid7(),
            trace_id=meta.get("trace_id"),
            workspace_id=meta.get("workspace_id"),
            org_id=meta.get("org_id"),
            team=meta.get("team") or tags.get("team"),
            feature=meta.get("feature") or tags.get("feature"),
            customer_hash=customer_hash,
            app_id=meta.get("app_id") or tags.get("app_id"),
            env=meta.get("env") or tags.get("env"),
            repo=meta.get("repo") or tags.get("repo"),
            branch=meta.get("branch") or tags.get("branch"),
            commit_sha=meta.get("commit_sha") or tags.get("commit_sha"),
            pricing_version=pricing_version,
        )

        # Emit OTEL span and metrics immediately
        try:
            from burnlens.telemetry.otel import emit_span, emit_metrics
            emit_span(record, original_headers or {})
            emit_metrics(record.to_event())
        except Exception as exc:
            logger.debug("OTEL telemetry emit failed for cache hit: %s", exc)

        if wal is not None and worker is not None:
            await wal.append_event(record)
            await worker.enqueue(record)
        else:
            from burnlens.storage.database import insert_request
            await insert_request(db_path, record)

        # Trigger Anomaly Detection on cache hits too
        _run_anomaly_detection(record, None, db_path)

    except Exception as exc:
        logger.warning("Failed to log cache hit (non-fatal): %s", exc)


async def _save_to_cache_bg(
    config: Any,
    db_path: str,
    system_hash: str | None,
    query_text: str,
    provider_name: str,
    model: str,
    response_body: bytes,
    customer_hash: str | None,
    tags: dict[str, str],
    request_headers: dict[str, str] | None = None,
    request_query: str | None = None,
):
    try:
        from burnlens.cache.embeddings import get_embedding
        embedding = await get_embedding(
            text=query_text,
            config=config,
            request_provider=provider_name,
            request_headers=request_headers,
            request_query=request_query
        )
        if embedding:
            from burnlens.cache.manager import SemanticCacheManager
            cache_manager = SemanticCacheManager(db_path, secret_key=config.secret_key)
            await cache_manager.save(
                system_prompt_hash=system_hash or "",
                query_text=query_text,
                provider=provider_name,
                model=model,
                response_body=response_body,
                embedding=embedding,
                customer_hash=customer_hash,
                tags=tags,
                ttl_seconds=config.cache.ttl_seconds
            )
    except Exception as exc:
        logger.debug("Background cache save failed (non-fatal): %s", exc)


