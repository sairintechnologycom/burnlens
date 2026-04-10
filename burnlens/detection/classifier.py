"""Provider signature matching and shadow asset classification.

This module is the intelligence layer of the BurnLens detection engine.
It connects raw detection data to provider identification and shadow
classification, writing structured ai_asset and discovery_event records.
"""
from __future__ import annotations

import fnmatch
import logging
from datetime import datetime

import aiosqlite

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

    Matching uses fnmatch glob patterns stored in the provider_signatures table.
    The URL scheme (https://) is stripped before matching.
    Matching is case-insensitive.

    Args:
        endpoint_url: The AI API endpoint URL to identify.
        db_path: Path to the BurnLens SQLite database.

    Returns:
        The provider name string (e.g. "openai") or None if no match found.
    """
    # Strip scheme (https:// or http://)
    url_host_path = endpoint_url.split("://", 1)[-1]
    url_lower = url_host_path.lower()

    signatures = await get_provider_signatures(db_path)
    for sig in signatures:
        if fnmatch.fnmatch(url_lower, sig.endpoint_pattern.lower()):
            return sig.provider

    return None


async def upsert_asset_from_detection(
    db_path: str,
    provider: str,
    model_name: str,
    endpoint_url: str,
    api_key_hash: str | None = None,
) -> None:
    """Insert a new shadow asset or update last_active_at on re-detection.

    Rules:
    - If no asset with matching (model_name, endpoint_url) exists under the
      given provider: insert a new AiAsset with status="shadow" and emit a
      "new_asset_detected" discovery event.
    - If a matching asset exists: update last_active_at only.
    - NEVER demote an approved asset back to shadow.

    Args:
        db_path: Path to the BurnLens SQLite database.
        provider: Identified provider name (e.g. "openai").
        model_name: Model identifier (e.g. "gpt-4o").
        endpoint_url: Full API endpoint URL.
        api_key_hash: Optional SHA-256 hash of the API key (never raw key).
    """
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
    """Classify shadow assets by re-running provider matching on their endpoint URLs.

    For each shadow asset:
    - If its endpoint_url matches a known provider signature: it is
      "known but unregistered" — remains shadow (no action needed).
    - If it does NOT match any signature: it is truly unknown — a secondary
      "unknown_provider" flag is noted in logs (asset stays shadow).

    This function is designed to be run periodically (e.g. hourly) after
    upsert_asset_from_detection has populated raw detections.

    Args:
        db_path: Path to the BurnLens SQLite database.

    Returns:
        Count of shadow assets that were examined.
    """
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
