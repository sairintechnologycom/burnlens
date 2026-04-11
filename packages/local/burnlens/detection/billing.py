"""Billing API parsers for OpenAI, Anthropic, and Google.

Provider fetch logic is in burnlens_core.providers.*. This module provides
backward-compatible wrapper functions and the DB-dependent run_all_parsers
orchestrator.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any

import aiosqlite

from burnlens_core.providers.base import _CANONICAL_URLS
from burnlens_core.providers.openai import OpenAIUsageProvider
from burnlens_core.providers.anthropic import AnthropicUsageProvider
from burnlens_core.providers.google import GoogleUsageProvider

from burnlens.config import BurnLensConfig
from burnlens.storage.database import insert_asset, insert_discovery_event
from burnlens.storage.models import AiAsset, DiscoveryEvent
from burnlens.storage.queries import get_assets

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Backward-compatible wrapper functions
# ---------------------------------------------------------------------------


async def fetch_openai_usage(
    admin_key: str | None,
    since_hours: int = 24,
) -> list[dict]:
    """Fetch usage data from the OpenAI organization billing API."""
    provider = OpenAIUsageProvider(admin_key=admin_key)
    return await provider.fetch_usage(since_hours=since_hours)


async def fetch_anthropic_usage(
    admin_key: str | None,
    since_hours: int = 24,
) -> list[dict]:
    """Fetch usage data from the Anthropic organization billing API."""
    provider = AnthropicUsageProvider(admin_key=admin_key)
    return await provider.fetch_usage(since_hours=since_hours)


async def fetch_google_usage(
    admin_key: str | None = None,
    since_hours: int = 24,
) -> list[dict]:
    """Google billing API detection stub."""
    provider = GoogleUsageProvider(admin_key=admin_key)
    return await provider.fetch_usage(since_hours=since_hours)


# ---------------------------------------------------------------------------
# run_all_parsers — orchestrator (DB-dependent, local only)
# ---------------------------------------------------------------------------


async def run_all_parsers(db_path: str, config: BurnLensConfig) -> None:
    """Run all provider billing parsers and upsert discovered ai_asset records."""
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
            now = datetime.utcnow().isoformat()
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    "UPDATE ai_assets SET last_active_at = ?, updated_at = ? WHERE id = ?",
                    (now, now, match.id),
                )
                await db.commit()


def _endpoint_url(provider: str) -> str:
    """Return the canonical API endpoint URL for a provider."""
    return _CANONICAL_URLS.get(provider, f"https://{provider}.api")
