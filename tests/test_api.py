"""Tests for Phase 3: API Layer — extended queries and Pydantic schema validation."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from burnlens.storage.database import init_db, insert_asset, insert_discovery_event
from burnlens.storage.models import AiAsset, DiscoveryEvent

# --- Phase 3: API Layer ---


def _make_asset(
    provider: str = "openai",
    model_name: str = "gpt-4o",
    endpoint_url: str = "https://api.openai.com",
    status: str = "shadow",
    risk_tier: str = "unclassified",
    first_seen_at: datetime | None = None,
    owner_team: str | None = None,
) -> AiAsset:
    """Helper to create a test AiAsset with sensible defaults."""
    now = datetime.utcnow()
    return AiAsset(
        provider=provider,
        model_name=model_name,
        endpoint_url=endpoint_url,
        status=status,
        risk_tier=risk_tier,
        owner_team=owner_team,
        first_seen_at=first_seen_at or now,
        last_active_at=now,
        created_at=now,
        updated_at=now,
    )


class TestQueryExtensions:
    """Tests for extended get_assets(), get_asset_summary(), update_asset_fields(), and get_assets_count()."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_db(self, tmp_path):
        """Create and seed a fresh database for each test."""
        self.db_path = str(tmp_path / "test.db")
        await init_db(self.db_path)

    @pytest.mark.asyncio
    async def test_get_assets_risk_tier_filter(self):
        """Test 1: get_assets(risk_tier='high') returns only high risk assets."""
        from burnlens.storage.queries import get_assets

        high_asset = _make_asset(risk_tier="high", model_name="gpt-4o")
        low_asset = _make_asset(risk_tier="low", model_name="claude-3")
        await insert_asset(self.db_path, high_asset)
        await insert_asset(self.db_path, low_asset)

        results = await get_assets(self.db_path, risk_tier="high")
        assert len(results) == 1
        assert results[0].risk_tier == "high"
        assert results[0].model_name == "gpt-4o"

    @pytest.mark.asyncio
    async def test_get_assets_date_since_filter(self):
        """Test 2: get_assets(date_since='2026-01-01') returns only assets with first_seen_at >= date."""
        from burnlens.storage.queries import get_assets

        old_date = datetime(2025, 6, 1)
        new_date = datetime(2026, 2, 1)

        old_asset = _make_asset(first_seen_at=old_date, model_name="old-model")
        new_asset = _make_asset(first_seen_at=new_date, model_name="new-model")
        await insert_asset(self.db_path, old_asset)
        await insert_asset(self.db_path, new_asset)

        results = await get_assets(self.db_path, date_since="2026-01-01")
        assert len(results) == 1
        assert results[0].model_name == "new-model"

    @pytest.mark.asyncio
    async def test_get_asset_summary_keys(self):
        """Test 3: get_asset_summary() returns dict with expected keys."""
        from burnlens.storage.queries import get_asset_summary

        await insert_asset(self.db_path, _make_asset(provider="openai", status="shadow", risk_tier="high"))
        await insert_asset(self.db_path, _make_asset(provider="anthropic", status="active", risk_tier="low"))

        summary = await get_asset_summary(self.db_path)
        assert "total" in summary
        assert "by_provider" in summary
        assert "by_status" in summary
        assert "by_risk_tier" in summary
        assert "new_this_week" in summary

    @pytest.mark.asyncio
    async def test_get_asset_summary_new_this_week(self):
        """Test 4: get_asset_summary() new_this_week count reflects assets with first_seen_at in last 7 days."""
        from burnlens.storage.queries import get_asset_summary

        recent = datetime.utcnow() - timedelta(days=2)
        old = datetime.utcnow() - timedelta(days=10)

        await insert_asset(self.db_path, _make_asset(first_seen_at=recent, model_name="recent-model"))
        await insert_asset(self.db_path, _make_asset(first_seen_at=old, model_name="old-model"))

        summary = await get_asset_summary(self.db_path)
        assert summary["total"] == 2
        assert summary["new_this_week"] == 1

    @pytest.mark.asyncio
    async def test_update_asset_fields_persists_changes(self):
        """Test 5: update_asset_fields persists owner_team, risk_tier, tags, status."""
        from burnlens.storage.queries import update_asset_fields

        asset_id = await insert_asset(self.db_path, _make_asset())
        updated = await update_asset_fields(
            self.db_path,
            asset_id,
            owner_team="ML",
            risk_tier="high",
            tags={"env": "prod"},
            status="active",
        )

        assert updated.owner_team == "ML"
        assert updated.risk_tier == "high"
        assert updated.tags == {"env": "prod"}
        assert updated.status == "active"

    @pytest.mark.asyncio
    async def test_update_asset_fields_raises_on_missing_asset(self):
        """Test 6: update_asset_fields raises ValueError for nonexistent asset_id."""
        from burnlens.storage.queries import update_asset_fields

        with pytest.raises(ValueError, match="not found"):
            await update_asset_fields(self.db_path, 9999, owner_team="ML")

    @pytest.mark.asyncio
    async def test_get_assets_count_returns_filtered_total(self):
        """Test 7: get_assets_count() returns total matching assets for pagination metadata."""
        from burnlens.storage.queries import get_assets_count

        await insert_asset(self.db_path, _make_asset(risk_tier="high", model_name="m1"))
        await insert_asset(self.db_path, _make_asset(risk_tier="high", model_name="m2"))
        await insert_asset(self.db_path, _make_asset(risk_tier="low", model_name="m3"))

        total_high = await get_assets_count(self.db_path, risk_tier="high")
        total_all = await get_assets_count(self.db_path)
        assert total_high == 2
        assert total_all == 3
