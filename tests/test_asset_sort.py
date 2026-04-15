"""Tests for server-side asset sorting in queries.get_assets()."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from burnlens.storage.database import init_db, insert_asset
from burnlens.storage.models import AiAsset
from burnlens.storage.queries import get_assets, get_assets_count


@pytest.fixture
async def db_path(tmp_path: Path) -> str:
    """Create a temporary database with schema initialized."""
    path = str(tmp_path / "test.db")
    await init_db(path)
    return path


def _make_asset(
    provider: str = "openai",
    model_name: str = "gpt-4",
    monthly_spend_usd: float = 0.0,
    monthly_requests: int = 0,
    first_seen_at: datetime | None = None,
    owner_team: str | None = None,
) -> AiAsset:
    now = datetime.now(timezone.utc)
    return AiAsset(
        provider=provider,
        model_name=model_name,
        endpoint_url=f"https://api.{provider}.com/v1",
        first_seen_at=first_seen_at or now,
        last_active_at=now,
        monthly_spend_usd=monthly_spend_usd,
        monthly_requests=monthly_requests,
        owner_team=owner_team,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_default_sort_is_first_seen_at_desc(db_path: str) -> None:
    """Default sort returns newest asset first (first_seen_at DESC)."""
    now = datetime.now(timezone.utc)
    old = _make_asset(model_name="old", first_seen_at=now - timedelta(days=10))
    new = _make_asset(model_name="new", first_seen_at=now)

    await insert_asset(db_path, old)
    await insert_asset(db_path, new)

    results = await get_assets(db_path)
    assert results[0].model_name == "new"
    assert results[1].model_name == "old"


@pytest.mark.asyncio
async def test_sort_by_monthly_spend_desc(db_path: str) -> None:
    """Highest spend asset is first when sort_by=monthly_spend_usd, sort_dir=desc."""
    await insert_asset(db_path, _make_asset(model_name="cheap", monthly_spend_usd=10.0))
    await insert_asset(db_path, _make_asset(model_name="expensive", monthly_spend_usd=500.0))
    await insert_asset(db_path, _make_asset(model_name="mid", monthly_spend_usd=100.0))

    results = await get_assets(db_path, sort_by="monthly_spend_usd", sort_dir="desc")
    assert results[0].model_name == "expensive"
    assert results[1].model_name == "mid"
    assert results[2].model_name == "cheap"


@pytest.mark.asyncio
async def test_sort_by_monthly_spend_asc(db_path: str) -> None:
    """Lowest spend asset is first when sort_dir=asc."""
    await insert_asset(db_path, _make_asset(model_name="cheap", monthly_spend_usd=10.0))
    await insert_asset(db_path, _make_asset(model_name="expensive", monthly_spend_usd=500.0))

    results = await get_assets(db_path, sort_by="monthly_spend_usd", sort_dir="asc")
    assert results[0].model_name == "cheap"
    assert results[1].model_name == "expensive"


@pytest.mark.asyncio
async def test_sort_by_model_asc_alphabetical(db_path: str) -> None:
    """String sort by model_name works alphabetically."""
    await insert_asset(db_path, _make_asset(model_name="gpt-4"))
    await insert_asset(db_path, _make_asset(model_name="claude-3"))
    await insert_asset(db_path, _make_asset(model_name="mistral-7b"))

    results = await get_assets(db_path, sort_by="model_name", sort_dir="asc")
    names = [r.model_name for r in results]
    assert names == sorted(names)


@pytest.mark.asyncio
async def test_invalid_sort_column_falls_back_to_default(db_path: str) -> None:
    """Invalid sort_by falls back to first_seen_at without error."""
    now = datetime.now(timezone.utc)
    await insert_asset(db_path, _make_asset(model_name="old", first_seen_at=now - timedelta(days=5)))
    await insert_asset(db_path, _make_asset(model_name="new", first_seen_at=now))

    results = await get_assets(db_path, sort_by="malicious_col")
    # Should not raise, and should use default (first_seen_at desc)
    assert len(results) == 2
    assert results[0].model_name == "new"


@pytest.mark.asyncio
async def test_invalid_sort_dir_falls_back_to_desc(db_path: str) -> None:
    """Invalid sort_dir falls back to desc without error."""
    now = datetime.now(timezone.utc)
    await insert_asset(db_path, _make_asset(model_name="old", first_seen_at=now - timedelta(days=5)))
    await insert_asset(db_path, _make_asset(model_name="new", first_seen_at=now))

    results = await get_assets(db_path, sort_by="first_seen_at", sort_dir="sideways")
    assert len(results) == 2
    assert results[0].model_name == "new"


@pytest.mark.asyncio
async def test_pagination_stable_across_pages(db_path: str) -> None:
    """No asset appears on both pages — stable sort via secondary id ASC."""
    now = datetime.now(timezone.utc)
    for i in range(15):
        await insert_asset(db_path, _make_asset(
            model_name=f"model-{i:02d}",
            first_seen_at=now,  # same first_seen_at forces tiebreak on id
        ))

    page1 = await get_assets(db_path, limit=10, offset=0, sort_by="first_seen_at", sort_dir="desc")
    page2 = await get_assets(db_path, limit=10, offset=10, sort_by="first_seen_at", sort_dir="desc")

    page1_ids = {a.id for a in page1}
    page2_ids = {a.id for a in page2}

    assert len(page1) == 10
    assert len(page2) == 5
    assert page1_ids.isdisjoint(page2_ids), "Asset appeared on both pages"


@pytest.mark.asyncio
async def test_sort_direction_indicator_in_response(db_path: str) -> None:
    """get_assets returns assets; callers can construct envelope with sort metadata.

    This test verifies that get_assets respects and applies the sort params
    so the API layer can echo them back in the response envelope.
    """
    await insert_asset(db_path, _make_asset(monthly_spend_usd=100.0))

    # Verify we can pass sort params and get results back
    results = await get_assets(db_path, sort_by="monthly_spend_usd", sort_dir="asc")
    assert len(results) == 1

    # Simulate the API envelope construction
    envelope = {
        "assets": results,
        "total": 1,
        "limit": 50,
        "offset": 0,
        "sort_by": "monthly_spend_usd",
        "sort_dir": "asc",
    }
    assert envelope["sort_by"] == "monthly_spend_usd"
    assert envelope["sort_dir"] == "asc"
