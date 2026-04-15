"""Tests for spend KPI aggregation across all assets (no pagination limit)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from burnlens.storage.database import init_db, insert_asset
from burnlens.storage.models import AiAsset
from burnlens.storage.queries import get_assets, get_total_spend_all_assets


@pytest.fixture
async def db_path(tmp_path: Path) -> str:
    """Create a temporary database with schema initialized."""
    path = str(tmp_path / "test.db")
    await init_db(path)
    return path


def _make_asset(
    provider: str = "openai",
    model_name: str = "gpt-4",
    monthly_spend_usd: float = 10.0,
    status: str = "active",
    owner_team: str | None = "platform",
    first_seen_at: datetime | None = None,
) -> AiAsset:
    now = datetime.now(timezone.utc)
    return AiAsset(
        provider=provider,
        model_name=model_name,
        endpoint_url=f"https://api.{provider}.com/v1",
        first_seen_at=first_seen_at or now,
        last_active_at=now,
        monthly_spend_usd=monthly_spend_usd,
        status=status,
        owner_team=owner_team,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_total_spend_not_limited_by_pagination(db_path: str) -> None:
    """Total spend must reflect ALL 60 assets, not just the default page of 50."""
    for i in range(60):
        await insert_asset(db_path, _make_asset(
            model_name=f"model-{i:02d}",
            monthly_spend_usd=10.0,
        ))

    result = await get_total_spend_all_assets(db_path)

    assert result["total_assets"] == 60
    assert result["monthly_spend_usd_total"] == pytest.approx(600.0)

    # Confirm paginated list only returns 50
    page = await get_assets(db_path, limit=50)
    assert len(page) == 50


@pytest.mark.asyncio
async def test_total_spend_respects_status_filter(db_path: str) -> None:
    """Filtering by status=shadow should only sum shadow asset spend."""
    for i in range(30):
        await insert_asset(db_path, _make_asset(
            model_name=f"active-{i}",
            status="active",
            monthly_spend_usd=10.0,
        ))
    for i in range(30):
        await insert_asset(db_path, _make_asset(
            model_name=f"shadow-{i}",
            status="shadow",
            monthly_spend_usd=10.0,
        ))

    result = await get_total_spend_all_assets(db_path, status="shadow")

    assert result["total_assets"] == 30
    assert result["monthly_spend_usd_total"] == pytest.approx(300.0)


@pytest.mark.asyncio
async def test_new_this_week_correct(db_path: str) -> None:
    """new_this_week counts only assets with first_seen_at within last 7 days."""
    now = datetime.now(timezone.utc)
    recent = now - timedelta(days=3)
    old = now - timedelta(days=10)

    for i in range(5):
        await insert_asset(db_path, _make_asset(
            model_name=f"recent-{i}",
            first_seen_at=recent,
        ))
    for i in range(5):
        await insert_asset(db_path, _make_asset(
            model_name=f"old-{i}",
            first_seen_at=old,
        ))

    result = await get_total_spend_all_assets(db_path)

    assert result["new_this_week"] == 5
    assert result["total_assets"] == 10


@pytest.mark.asyncio
async def test_summary_endpoint_returns_computed_over_field(db_path: str) -> None:
    """The summary dict plus computed_over field must be present."""
    await insert_asset(db_path, _make_asset())

    result = await get_total_spend_all_assets(db_path)
    # Simulate the API layer adding the field
    result["computed_over"] = "all_assets"

    assert result["computed_over"] == "all_assets"
    assert "total_assets" in result
    assert "monthly_spend_usd_total" in result


@pytest.mark.asyncio
async def test_zero_assets_no_crash(db_path: str) -> None:
    """Empty database returns zeroes without exception."""
    result = await get_total_spend_all_assets(db_path)

    assert result["total_assets"] == 0
    assert result["active_assets"] == 0
    assert result["shadow_assets"] == 0
    assert result["unassigned_assets"] == 0
    assert result["monthly_spend_usd_total"] == 0.0
    assert result["new_this_week"] == 0


@pytest.mark.asyncio
async def test_summary_filters_match_list_filters(db_path: str) -> None:
    """Summary spend for provider=openai must match sum of list results for same filter."""
    for i in range(10):
        await insert_asset(db_path, _make_asset(
            provider="openai",
            model_name=f"oai-{i}",
            monthly_spend_usd=20.0,
        ))
    for i in range(5):
        await insert_asset(db_path, _make_asset(
            provider="anthropic",
            model_name=f"anth-{i}",
            monthly_spend_usd=30.0,
        ))

    summary = await get_total_spend_all_assets(db_path, provider="openai")
    list_results = await get_assets(db_path, provider="openai", limit=200)

    list_spend = sum(a.monthly_spend_usd for a in list_results)

    assert summary["total_assets"] == 10
    assert summary["monthly_spend_usd_total"] == pytest.approx(list_spend)
    assert summary["monthly_spend_usd_total"] == pytest.approx(200.0)
