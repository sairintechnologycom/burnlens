"""Provider signature matching and shadow asset classification.

Core matching logic is in burnlens_core.detection.classifier. This module
adds DB-dependent orchestration (upsert, classify) on top.
"""
from __future__ import annotations

import logging
from datetime import datetime

import aiosqlite

from burnlens_core.detection.classifier import match_provider_from_signatures
from burnlens.storage.database import insert_asset, insert_discovery_event
from burnlens.storage.models import AiAsset, DiscoveryEvent
from burnlens.storage.queries import get_assets, get_provider_signatures

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _update_last_active(db_path: str, asset_id: int) -> None:
    """Update last_active_at (and updated_at) for an existing asset."""
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE ai_assets SET last_active_at = ?, updated_at = ? WHERE id = ?",
            (now, now, asset_id),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def match_provider(endpoint_url: str, db_path: str) -> str | None:
    """Return the provider name for a given endpoint URL, or None if unknown.

    Delegates matching to burnlens_core.detection.classifier.match_provider_from_signatures,
    loading signatures from the local SQLite database.
    """
    signatures = await get_provider_signatures(db_path)
    return match_provider_from_signatures(endpoint_url, signatures)


async def upsert_asset_from_detection(
    db_path: str,
    provider: str,
    model_name: str,
    endpoint_url: str,
    api_key_hash: str | None = None,
) -> None:
    """Insert a new shadow asset or update last_active_at on re-detection."""
    existing = await get_assets(db_path, provider=provider)
    match = next(
        (
            a
            for a in existing
            if a.model_name == model_name and a.endpoint_url == endpoint_url
        ),
        None,
    )

    if match is None:
        # New asset — insert with shadow status
        new_asset = AiAsset(
            provider=provider,
            model_name=model_name,
            endpoint_url=endpoint_url,
            api_key_hash=api_key_hash,
            status="shadow",
        )
        asset_id = await insert_asset(db_path, new_asset)

        # Emit discovery event
        event = DiscoveryEvent(
            event_type="new_asset_detected",
            asset_id=asset_id,
            details={
                "provider": provider,
                "model": model_name,
                "source": "detection",
            },
        )
        await insert_discovery_event(db_path, event)
        logger.info(
            "New shadow asset detected: provider=%s model=%s endpoint=%s",
            provider, model_name, endpoint_url,
        )
    else:
        # Existing asset — only update last_active_at, never demote
        await _update_last_active(db_path, match.id)  # type: ignore[arg-type]
        logger.debug(
            "Re-detected existing asset id=%s (status=%s), updated last_active_at",
            match.id, match.status,
        )


async def classify_new_assets(db_path: str) -> int:
    """Classify shadow assets by re-running provider matching on their endpoint URLs."""
    shadow_assets = await get_assets(db_path, status="shadow", limit=500)
    count = 0

    for asset in shadow_assets:
        provider = await match_provider(asset.endpoint_url, db_path)
        if provider is None:
            logger.warning(
                "Asset id=%s has unknown provider endpoint: %s",
                asset.id, asset.endpoint_url,
            )
        count += 1

    return count
