"""Billing API parsers for OpenAI, Anthropic, and Google.

These parsers query provider admin/billing APIs to discover AI assets
(model/key combinations) that may not be routed through the BurnLens proxy.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from burnlens.config import BurnLensConfig
from burnlens.storage.database import insert_asset, insert_discovery_event
from burnlens.storage.models import AiAsset, DiscoveryEvent
from burnlens.storage.queries import get_assets

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared pagination helper
# ---------------------------------------------------------------------------


async def _paginate_usage(
    url: str,
    headers: dict[str, str],
    params: dict[str, Any],
    data_extractor: Any = None,
) -> list[dict]:
    """Follow has_more / next_page pagination, collecting all results.

    Args:
        url: API endpoint URL.
        headers: Request headers (auth, version, etc.).
        params: Initial query parameters.
        data_extractor: Optional callable(response_json) -> list[dict].
                        If None, uses response_json["data"] directly.

    Returns:
        Flat list of all result dicts across all pages.
    """
    all_results: list[dict] = []
    current_params = dict(params)

    async with httpx.AsyncClient() as client:
        while True:
            try:
                response = await client.get(url, headers=headers, params=current_params)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "HTTP error fetching billing data from %s: %s %s",
                    url,
                    exc.response.status_code,
                    exc.response.text[:200],
                )
                break
            except httpx.RequestError as exc:
                logger.error("Request error fetching billing data from %s: %s", url, exc)
                break

            payload = response.json()

            if data_extractor is not None:
                page_results = data_extractor(payload)
            else:
                page_results = payload.get("data", [])

            all_results.extend(page_results)

            if not payload.get("has_more"):
                break

            next_page = payload.get("next_page")
            if not next_page:
                break
            current_params["page"] = next_page

    return all_results


# ---------------------------------------------------------------------------
# OpenAI billing parser
# ---------------------------------------------------------------------------


async def fetch_openai_usage(
    admin_key: str | None,
    since_hours: int = 24,
) -> list[dict]:
    """Fetch usage data from the OpenAI organization billing API.

    Calls POST /v1/organization/usage/completions with group_by model and
    api_key_id. Paginates via has_more + next_page.

    Args:
        admin_key: OpenAI admin API key (sk-... with org admin scope).
        since_hours: How many hours back to query.

    Returns:
        List of result dicts with model, api_key_id, input_tokens, output_tokens,
        num_model_requests fields. Empty list if admin_key is None.
    """
    if admin_key is None:
        logger.warning(
            "openai_admin_key not configured — skipping OpenAI billing API detection. "
            "Set openai_admin_key in config or OPENAI_ADMIN_KEY env var."
        )
        return []

    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    start_time = int(since.timestamp())

    headers = {
        "Authorization": f"Bearer {admin_key}",
        "Content-Type": "application/json",
    }
    params = {
        "start_time": start_time,
        "group_by[]": ["model", "api_key_id"],
    }

    url = "https://api.openai.com/v1/organization/usage/completions"

    def _extract_openai(payload: dict) -> list[dict]:
        results = []
        for bucket in payload.get("data", []):
            results.extend(bucket.get("results", []))
        return results

    return await _paginate_usage(url, headers, params, data_extractor=_extract_openai)


# ---------------------------------------------------------------------------
# Anthropic billing parser
# ---------------------------------------------------------------------------


async def fetch_anthropic_usage(
    admin_key: str | None,
    since_hours: int = 24,
) -> list[dict]:
    """Fetch usage data from the Anthropic organization billing API.

    Calls GET /v1/organizations/usage_report/messages with group_by model.
    Paginates via has_more + next_page.

    Args:
        admin_key: Anthropic admin API key (x-api-key header).
        since_hours: How many hours back to query.

    Returns:
        List of result dicts with model, input_tokens, output_tokens,
        num_model_requests. Empty list if admin_key is None.
    """
    if admin_key is None:
        logger.warning(
            "anthropic_admin_key not configured — skipping Anthropic billing API detection. "
            "Set anthropic_admin_key in config or ANTHROPIC_ADMIN_KEY env var."
        )
        return []

    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    start_time = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    headers = {
        "x-api-key": admin_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    params = {
        "start_time": start_time,
        "group_by[]": "model",
    }

    url = "https://api.anthropic.com/v1/organizations/usage_report/messages"

    return await _paginate_usage(url, headers, params)


# ---------------------------------------------------------------------------
# Google billing parser (stub — proxy-only detection)
# ---------------------------------------------------------------------------


async def fetch_google_usage(
    admin_key: str | None = None,
    since_hours: int = 24,
) -> list[dict]:
    """Google billing API detection stub.

    Google Generative AI does not expose a billing/usage admin API with
    per-model breakdown suitable for this detection pattern. Detection for
    Google happens through proxy traffic analysis instead.

    Returns:
        Always returns empty list.
    """
    logger.info(
        "Google detection uses proxy traffic only (no billing API available). "
        "Google AI usage will be captured automatically via the BurnLens proxy."
    )
    return []


# ---------------------------------------------------------------------------
# run_all_parsers — orchestrator
# ---------------------------------------------------------------------------


async def run_all_parsers(db_path: str, config: BurnLensConfig) -> None:
    """Run all provider billing parsers and upsert discovered ai_asset records.

    For each result returned by a provider parser:
    - If the asset (provider + model + endpoint) already exists, update last_active_at.
    - If it is new, insert with status=shadow and write a new_asset_detected event.

    Args:
        db_path: Path to the SQLite database.
        config: BurnLensConfig with admin key fields populated.
    """
    provider_results: list[tuple[str, dict]] = []

    # --- OpenAI ---
    openai_data = await fetch_openai_usage(config.openai_admin_key)
    for item in openai_data:
        provider_results.append(("openai", item))

    # --- Anthropic ---
    anthropic_data = await fetch_anthropic_usage(config.anthropic_admin_key)
    for item in anthropic_data:
        provider_results.append(("anthropic", item))

    # --- Google ---
    google_data = await fetch_google_usage()
    for item in google_data:
        provider_results.append(("google", item))

    # --- Upsert assets ---
    for provider, result in provider_results:
        model_name = result.get("model", "unknown")
        endpoint_url = _endpoint_url(provider)
        api_key_id = result.get("api_key_id")
        api_key_hash = (
            hashlib.sha256(api_key_id.encode()).hexdigest() if api_key_id else None
        )

        # Check for existing asset (same provider + model + endpoint)
        existing = await get_assets(db_path, provider=provider)
        match = next(
            (a for a in existing if a.model_name == model_name and a.endpoint_url == endpoint_url),
            None,
        )

        if match is None:
            # New asset — insert with shadow status
            asset = AiAsset(
                provider=provider,
                model_name=model_name,
                endpoint_url=endpoint_url,
                api_key_hash=api_key_hash,
                status="shadow",
            )
            asset_id = await insert_asset(db_path, asset)

            # Write discovery event
            event = DiscoveryEvent(
                event_type="new_asset_detected",
                asset_id=asset_id,
                details={
                    "provider": provider,
                    "model": model_name,
                    "source": "billing_api",
                },
            )
            await insert_discovery_event(db_path, event)
            logger.info("New shadow asset detected via billing API: %s / %s", provider, model_name)
        else:
            # Existing asset — update last_active_at
            import aiosqlite

            now = datetime.now(timezone.utc).isoformat()
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    "UPDATE ai_assets SET last_active_at = ?, updated_at = ? WHERE id = ?",
                    (now, now, match.id),
                )
                await db.commit()


def _endpoint_url(provider: str) -> str:
    """Return the canonical API endpoint URL for a provider."""
    _URLS = {
        "openai": "https://api.openai.com",
        "anthropic": "https://api.anthropic.com",
        "google": "https://generativelanguage.googleapis.com",
        "azure_openai": "https://openai.azure.com",
        "bedrock": "https://bedrock-runtime.amazonaws.com",
        "cohere": "https://api.cohere.com",
        "mistral": "https://api.mistral.ai",
    }
    return _URLS.get(provider, f"https://{provider}.api")
