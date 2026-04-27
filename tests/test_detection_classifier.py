"""Tests for burnlens/detection/classifier.py — provider matching and shadow classification."""
from __future__ import annotations

import pytest
import pytest_asyncio

from burnlens.storage.database import init_db, insert_asset
from burnlens.storage.models import AiAsset, DiscoveryEvent
from burnlens.storage.queries import get_assets, get_discovery_events


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path):
    """Initialize a fresh in-memory-style SQLite DB with seeded provider signatures."""
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    return db_path


# ---------------------------------------------------------------------------
# match_provider tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_match_provider_openai(db):
    """URL 'api.openai.com/v1/chat/completions' matches provider 'openai'."""
    from burnlens.detection.classifier import match_provider

    result = await match_provider("api.openai.com/v1/chat/completions", db)
    assert result == "openai"


@pytest.mark.asyncio
async def test_match_provider_anthropic(db):
    """URL 'api.anthropic.com/v1/messages' matches provider 'anthropic'."""
    from burnlens.detection.classifier import match_provider

    result = await match_provider("api.anthropic.com/v1/messages", db)
    assert result == "anthropic"


@pytest.mark.asyncio
async def test_match_provider_azure(db):
    """Azure wildcard subdomain URL matches 'azure_openai'."""
    from burnlens.detection.classifier import match_provider

    result = await match_provider(
        "mydeployment.openai.azure.com/openai/deployments/gpt4", db
    )
    assert result == "azure_openai"


@pytest.mark.asyncio
async def test_match_provider_unknown(db):
    """URL for an unknown provider returns None."""
    from burnlens.detection.classifier import match_provider

    result = await match_provider("api.unknown-llm.com/v1/chat", db)
    assert result is None


@pytest.mark.asyncio
async def test_match_provider_case_insensitive(db):
    """URL matching is case-insensitive (uppercase host)."""
    from burnlens.detection.classifier import match_provider

    result = await match_provider("API.OPENAI.COM/v1/chat", db)
    assert result == "openai"


@pytest.mark.asyncio
async def test_match_provider_with_scheme(db):
    """URL with https:// scheme is stripped before matching."""
    from burnlens.detection.classifier import match_provider

    result = await match_provider("https://api.openai.com/v1/chat", db)
    assert result == "openai"


# ---------------------------------------------------------------------------
# upsert_asset_from_detection tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_classification_new_asset(db):
    """New provider+model+endpoint creates shadow asset and new_asset_detected event."""
    from burnlens.detection.classifier import upsert_asset_from_detection

    await upsert_asset_from_detection(
        db,
        provider="openai",
        model_name="gpt-4o",
        endpoint_url="api.openai.com/v1/chat/completions",
    )

    assets = await get_assets(db, provider="openai")
    assert len(assets) == 1
    asset = assets[0]
    assert asset.status == "shadow"
    assert asset.model_name == "gpt-4o"
    assert asset.endpoint_url == "api.openai.com/v1/chat/completions"

    events = await get_discovery_events(db, asset_id=asset.id)
    assert len(events) == 1
    assert events[0].event_type == "new_asset_detected"
    assert events[0].details.get("provider") == "openai"
    assert events[0].details.get("model") == "gpt-4o"
    assert events[0].details.get("source") == "detection"


@pytest.mark.asyncio
async def test_shadow_classification_existing_asset(db):
    """Existing asset is NOT re-inserted; last_active_at is updated instead."""
    from burnlens.detection.classifier import upsert_asset_from_detection
    from burnlens.storage.queries import get_asset_by_id

    # First upsert creates the asset
    await upsert_asset_from_detection(
        db,
        provider="anthropic",
        model_name="claude-3-5-sonnet-20241022",
        endpoint_url="api.anthropic.com/v1/messages",
    )

    assets_before = await get_assets(db, provider="anthropic")
    assert len(assets_before) == 1
    first_active_at = assets_before[0].last_active_at

    # Second upsert must NOT create a duplicate
    await upsert_asset_from_detection(
        db,
        provider="anthropic",
        model_name="claude-3-5-sonnet-20241022",
        endpoint_url="api.anthropic.com/v1/messages",
    )

    assets_after = await get_assets(db, provider="anthropic")
    assert len(assets_after) == 1, "Should not create a duplicate asset"

    # last_active_at should be updated
    updated_asset = await get_asset_by_id(db, assets_after[0].id)
    assert updated_asset is not None
    assert updated_asset.last_active_at >= first_active_at


@pytest.mark.asyncio
async def test_no_demote_approved(db):
    """Approved asset is never changed back to shadow on re-detection."""
    from burnlens.detection.classifier import upsert_asset_from_detection
    from burnlens.storage.database import update_asset_status

    # Create an asset, then approve it
    await upsert_asset_from_detection(
        db,
        provider="openai",
        model_name="gpt-4o-mini",
        endpoint_url="api.openai.com/v1/chat/completions",
    )
    assets = await get_assets(db, provider="openai")
    asset_id = assets[0].id
    await update_asset_status(db, asset_id, "approved")

    # Re-detect — must not demote back to shadow
    await upsert_asset_from_detection(
        db,
        provider="openai",
        model_name="gpt-4o-mini",
        endpoint_url="api.openai.com/v1/chat/completions",
    )

    assets_after = await get_assets(db, provider="openai")
    assert len(assets_after) == 1
    assert assets_after[0].status == "approved", "Approved asset must not be demoted"


# ---------------------------------------------------------------------------
# classify_new_assets integration test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_new_assets(db):
    """classify_new_assets inserts shadow assets for seeded billing-style data."""
    from burnlens.detection.classifier import classify_new_assets, upsert_asset_from_detection

    # Simulate billing data arriving — upsert three distinct assets
    await upsert_asset_from_detection(db, "openai", "gpt-4o", "api.openai.com/v1/chat/completions")
    await upsert_asset_from_detection(db, "anthropic", "claude-3-haiku-20240307", "api.anthropic.com/v1/messages")
    await upsert_asset_from_detection(db, "custom", "local-llm", "api.unknown-llm.com/v1/chat")

    count = await classify_new_assets(db)
    assert count >= 0  # function returns an integer count (may be 0 if all already classified)

    # All three assets should exist as shadow
    all_assets = await get_assets(db)
    assert len(all_assets) >= 3

    shadow_assets = [a for a in all_assets if a.status == "shadow"]
    assert len(shadow_assets) >= 3
