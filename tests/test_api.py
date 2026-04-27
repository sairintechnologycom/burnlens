"""Tests for Phase 3: API Layer — extended queries and Pydantic schema validation."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

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


# ---------------------------------------------------------------------------
# Phase 3 Plan 03: Discovery events and provider signatures API routers
# ---------------------------------------------------------------------------


def _make_event(
    event_type: str = "new_asset_detected",
    asset_id: int | None = None,
    details: dict | None = None,
    detected_at: datetime | None = None,
) -> DiscoveryEvent:
    """Helper to create a test DiscoveryEvent with sensible defaults."""
    return DiscoveryEvent(
        event_type=event_type,
        asset_id=asset_id,
        details=details or {},
        detected_at=detected_at or datetime.utcnow(),
    )


@pytest.fixture
def discovery_app(tmp_path):
    """Create a FastAPI test app with discovery and provider routers mounted."""
    from fastapi import FastAPI
    from burnlens.api.discovery import router as discovery_router
    from burnlens.api.providers import router as providers_router

    app = FastAPI()
    db_path = str(tmp_path / "test_discovery.db")
    app.state.db_path = db_path
    app.include_router(discovery_router, prefix="/api/v1")
    app.include_router(providers_router, prefix="/api/v1")
    return app, db_path


class TestDiscoveryAPI:
    """Integration tests for GET /api/v1/discovery/events."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, tmp_path):
        """Seed a fresh DB and build app for each test."""
        import httpx
        from fastapi import FastAPI
        from httpx import AsyncClient, ASGITransport
        from burnlens.api.discovery import router as discovery_router
        from burnlens.api.providers import router as providers_router

        self.db_path = str(tmp_path / "test.db")
        await init_db(self.db_path)

        app = FastAPI()
        app.state.db_path = self.db_path
        app.include_router(discovery_router, prefix="/api/v1")
        app.include_router(providers_router, prefix="/api/v1")
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        yield
        await self.client.aclose()

    @pytest.mark.asyncio
    async def test_get_events_returns_200_with_items_and_total(self):
        """Test 1: GET /api/v1/discovery/events returns 200 with items list and total."""
        asset_id = await insert_asset(self.db_path, _make_asset())
        await insert_discovery_event(self.db_path, _make_event(asset_id=asset_id))

        resp = await self.client.get("/api/v1/discovery/events")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert len(data["items"]) >= 1

    @pytest.mark.asyncio
    async def test_get_events_filter_by_event_type(self):
        """Test 2: GET /api/v1/discovery/events?event_type=new_asset_detected filters by type."""
        asset_id = await insert_asset(self.db_path, _make_asset())
        await insert_discovery_event(self.db_path, _make_event(event_type="new_asset_detected", asset_id=asset_id))
        await insert_discovery_event(self.db_path, _make_event(event_type="asset_inactive", asset_id=asset_id))

        resp = await self.client.get("/api/v1/discovery/events?event_type=new_asset_detected")
        assert resp.status_code == 200
        data = resp.json()
        assert all(item["event_type"] == "new_asset_detected" for item in data["items"])

    @pytest.mark.asyncio
    async def test_get_events_filter_by_asset_id(self):
        """Test 3: GET /api/v1/discovery/events?asset_id=1 filters by asset."""
        asset_id1 = await insert_asset(self.db_path, _make_asset(model_name="gpt-4o"))
        asset_id2 = await insert_asset(self.db_path, _make_asset(model_name="claude-3"))
        await insert_discovery_event(self.db_path, _make_event(asset_id=asset_id1))
        await insert_discovery_event(self.db_path, _make_event(asset_id=asset_id2))

        resp = await self.client.get(f"/api/v1/discovery/events?asset_id={asset_id1}")
        assert resp.status_code == 200
        data = resp.json()
        assert all(item["asset_id"] == asset_id1 for item in data["items"])
        assert len(data["items"]) == 1

    @pytest.mark.asyncio
    async def test_get_events_filter_by_date_range(self):
        """Test 4: GET /api/v1/discovery/events?since=2026-01-01&until=2026-12-31 filters by date range."""
        asset_id = await insert_asset(self.db_path, _make_asset())
        old = datetime(2025, 6, 15)
        recent = datetime(2026, 3, 10)
        future = datetime(2027, 1, 5)

        await insert_discovery_event(self.db_path, _make_event(asset_id=asset_id, detected_at=old))
        await insert_discovery_event(self.db_path, _make_event(asset_id=asset_id, detected_at=recent))
        await insert_discovery_event(self.db_path, _make_event(asset_id=asset_id, detected_at=future))

        resp = await self.client.get("/api/v1/discovery/events?since=2026-01-01&until=2026-12-31")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert "2026" in data["items"][0]["detected_at"]


class TestProviderAPI:
    """Integration tests for GET/POST /api/v1/providers/signatures."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, tmp_path):
        """Seed a fresh DB and build app for each test."""
        from fastapi import FastAPI
        from httpx import AsyncClient, ASGITransport
        from burnlens.api.discovery import router as discovery_router
        from burnlens.api.providers import router as providers_router

        self.db_path = str(tmp_path / "test.db")
        await init_db(self.db_path)

        app = FastAPI()
        app.state.db_path = self.db_path
        app.include_router(discovery_router, prefix="/api/v1")
        app.include_router(providers_router, prefix="/api/v1")
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        yield
        await self.client.aclose()

    @pytest.mark.asyncio
    async def test_get_signatures_returns_200_list(self):
        """Test 5: GET /api/v1/providers/signatures returns 200 with list of all signatures."""
        resp = await self.client.get("/api/v1/providers/signatures")
        assert resp.status_code == 200
        data = resp.json()
        # Seed data has 7 providers
        assert len(data) >= 7
        assert all("provider" in s for s in data)

    @pytest.mark.asyncio
    async def test_get_signatures_filter_by_provider(self):
        """Test 6: GET /api/v1/providers/signatures?provider=openai filters by provider."""
        resp = await self.client.get("/api/v1/providers/signatures?provider=openai")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_post_signature_creates_and_returns_201(self):
        """Test 7: POST /api/v1/providers/signatures with valid body returns 201 with created signature."""
        payload = {
            "provider": "custom_llm",
            "endpoint_pattern": "api.custom-llm.com/*",
            "header_signature": {"keys": ["authorization"]},
            "model_field_path": "body.model",
        }
        resp = await self.client.post("/api/v1/providers/signatures", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["provider"] == "custom_llm"
        assert data["endpoint_pattern"] == "api.custom-llm.com/*"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_post_signature_visible_in_subsequent_get(self):
        """Test 8: POST /api/v1/providers/signatures and subsequent GET includes the new signature."""
        payload = {
            "provider": "my_custom_provider",
            "endpoint_pattern": "api.myco.io/*",
            "header_signature": {},
            "model_field_path": "body.model",
        }
        post_resp = await self.client.post("/api/v1/providers/signatures", json=payload)
        assert post_resp.status_code == 201

        get_resp = await self.client.get("/api/v1/providers/signatures?provider=my_custom_provider")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert len(data) == 1
        assert data[0]["provider"] == "my_custom_provider"

    @pytest.mark.asyncio
    async def test_post_signature_missing_provider_returns_422(self):
        """Test 9: POST /api/v1/providers/signatures with missing provider field returns 422."""
        payload = {
            "endpoint_pattern": "api.example.com/*",
        }
        resp = await self.client.post("/api/v1/providers/signatures", json=payload)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# TestAssetAPI — asset management router (burnlens/api/assets.py)
# ---------------------------------------------------------------------------


async def _insert_test_assets(db_path: str) -> list[int]:
    """Insert 4 test assets with varied provider/status/risk_tier. Return their IDs."""
    now = datetime.utcnow()

    assets = [
        AiAsset(
            provider="openai",
            model_name="gpt-4o",
            endpoint_url="https://api.openai.com/v1/chat/completions",
            status="shadow",
            risk_tier="high",
            owner_team="ML",
            first_seen_at=datetime(2026, 3, 1),
            last_active_at=now,
            created_at=now,
            updated_at=now,
        ),
        AiAsset(
            provider="anthropic",
            model_name="claude-3-5-sonnet",
            endpoint_url="https://api.anthropic.com/v1/messages",
            status="approved",
            risk_tier="low",
            owner_team="Platform",
            first_seen_at=datetime(2026, 3, 15),
            last_active_at=now,
            created_at=now,
            updated_at=now,
        ),
        AiAsset(
            provider="openai",
            model_name="gpt-3.5-turbo",
            endpoint_url="https://api.openai.com/v1/chat/completions",
            status="shadow",
            risk_tier="medium",
            owner_team="Data",
            first_seen_at=datetime(2026, 1, 1),
            last_active_at=now,
            created_at=now,
            updated_at=now,
        ),
        AiAsset(
            provider="google",
            model_name="gemini-pro",
            endpoint_url="https://generativelanguage.googleapis.com/v1beta/models",
            status="active",
            risk_tier="unclassified",
            first_seen_at=datetime(2026, 4, 8),
            last_active_at=now,
            created_at=now,
            updated_at=now,
        ),
    ]

    ids: list[int] = []
    for a in assets:
        row_id = await insert_asset(db_path, a)
        ids.append(row_id)
    return ids


class TestAssetAPI:
    """Integration tests for all 5 asset management endpoints (burnlens/api/assets.py)."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, tmp_path):
        """Create a fresh DB and mount the asset router on a test FastAPI app."""
        from fastapi import FastAPI
        from burnlens.api.assets import router as assets_router

        self.db_path = str(tmp_path / "test_assets.db")
        await init_db(self.db_path)

        app = FastAPI()
        app.state.db_path = self.db_path
        app.include_router(assets_router, prefix="/api/v1/assets")

        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        yield
        await self.client.aclose()

    @pytest.mark.asyncio
    async def test_list_assets_returns_paginated_response(self):
        """Test 1: GET /api/v1/assets returns 200 with AssetListResponse shape."""
        await _insert_test_assets(self.db_path)

        resp = await self.client.get("/api/v1/assets")

        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert data["total"] == 4
        assert len(data["items"]) == 4
        assert data["limit"] == 50
        assert data["offset"] == 0

    @pytest.mark.asyncio
    async def test_list_assets_filter_by_provider(self):
        """Test 2: GET /api/v1/assets?provider=openai filters correctly."""
        await _insert_test_assets(self.db_path)

        resp = await self.client.get("/api/v1/assets?provider=openai")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert all(item["provider"] == "openai" for item in data["items"])

    @pytest.mark.asyncio
    async def test_list_assets_combined_filters(self):
        """Test 3: GET /api/v1/assets?status=shadow&risk_tier=high combines filters."""
        await _insert_test_assets(self.db_path)

        resp = await self.client.get("/api/v1/assets?status=shadow&risk_tier=high")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["provider"] == "openai"
        assert data["items"][0]["model_name"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_list_assets_filter_by_date_since(self):
        """Test 4: GET /api/v1/assets?date_since=2026-04-01 filters by first_seen_at."""
        await _insert_test_assets(self.db_path)

        resp = await self.client.get("/api/v1/assets?date_since=2026-04-01")

        assert resp.status_code == 200
        data = resp.json()
        # Only 'gemini-pro' has first_seen_at >= 2026-04-01
        assert data["total"] == 1
        assert data["items"][0]["model_name"] == "gemini-pro"

    @pytest.mark.asyncio
    async def test_get_asset_detail_returns_200(self):
        """Test 5: GET /api/v1/assets/{id} returns 200 with asset + events list."""
        ids = await _insert_test_assets(self.db_path)
        asset_id = ids[0]

        resp = await self.client.get(f"/api/v1/assets/{asset_id}")

        assert resp.status_code == 200
        data = resp.json()
        assert "asset" in data
        assert "events" in data
        assert data["asset"]["id"] == asset_id
        assert data["asset"]["provider"] == "openai"
        assert isinstance(data["events"], list)

    @pytest.mark.asyncio
    async def test_get_asset_detail_404_for_nonexistent(self):
        """Test 6: GET /api/v1/assets/{id} returns 404 for nonexistent id."""
        resp = await self.client.get("/api/v1/assets/99999")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_patch_asset_updates_owner_team(self):
        """Test 7: PATCH /api/v1/assets/{id} with owner_team returns updated asset."""
        ids = await _insert_test_assets(self.db_path)
        asset_id = ids[0]

        resp = await self.client.patch(
            f"/api/v1/assets/{asset_id}",
            json={"owner_team": "ML-Platform"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["owner_team"] == "ML-Platform"
        assert data["id"] == asset_id

    @pytest.mark.asyncio
    async def test_patch_asset_status_creates_discovery_event(self):
        """Test 8: PATCH /api/v1/assets/{id} with status change also creates discovery_event."""
        ids = await _insert_test_assets(self.db_path)
        asset_id = ids[0]

        # First verify current status
        detail_resp = await self.client.get(f"/api/v1/assets/{asset_id}")
        assert detail_resp.json()["asset"]["status"] == "shadow"

        # Patch the status
        patch_resp = await self.client.patch(
            f"/api/v1/assets/{asset_id}",
            json={"status": "approved"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["status"] == "approved"

        # Verify event was created
        detail_after = await self.client.get(f"/api/v1/assets/{asset_id}")
        events = detail_after.json()["events"]
        assert len(events) >= 1
        assert any(e["event_type"] == "model_changed" for e in events)

    @pytest.mark.asyncio
    async def test_patch_asset_404_for_nonexistent(self):
        """Test 9: PATCH /api/v1/assets/999 returns 404."""
        resp = await self.client.patch(
            "/api/v1/assets/999",
            json={"owner_team": "ML"},
        )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_approve_asset_returns_200_with_event(self):
        """Test 10: POST /api/v1/assets/{id}/approve returns 200 with asset and event_id."""
        ids = await _insert_test_assets(self.db_path)
        # ids[0] is shadow status
        asset_id = ids[0]

        resp = await self.client.post(f"/api/v1/assets/{asset_id}/approve")

        assert resp.status_code == 200
        data = resp.json()
        assert "asset" in data
        assert "event_id" in data
        assert data["asset"]["status"] == "approved"
        assert isinstance(data["event_id"], int)

    @pytest.mark.asyncio
    async def test_approve_already_approved_returns_409(self):
        """Test 11: POST /api/v1/assets/{id}/approve on already-approved returns 409."""
        ids = await _insert_test_assets(self.db_path)
        # ids[1] is already approved
        asset_id = ids[1]

        resp = await self.client.post(f"/api/v1/assets/{asset_id}/approve")

        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_get_summary_returns_correct_counts(self):
        """Test 12: GET /api/v1/assets/summary returns AssetSummaryResponse shape with correct counts."""
        await _insert_test_assets(self.db_path)

        resp = await self.client.get("/api/v1/assets/summary")

        assert resp.status_code == 200
        data = resp.json()

        # Verify shape
        assert "total" in data
        assert "by_provider" in data
        assert "by_status" in data
        assert "by_risk_tier" in data
        assert "new_this_week" in data

        # Verify counts
        assert data["total"] == 4
        assert data["by_provider"]["openai"] == 2
        assert data["by_provider"]["anthropic"] == 1
        assert data["by_provider"]["google"] == 1
        assert data["by_status"]["shadow"] == 2
        assert data["by_status"]["approved"] == 1
        assert data["by_status"]["active"] == 1
        assert data["by_risk_tier"]["high"] == 1
        assert data["by_risk_tier"]["low"] == 1


# ---------------------------------------------------------------------------
# Phase 5 Plan 02: TestAssetSearch — search_query parameter on get_assets and API
# ---------------------------------------------------------------------------


async def _insert_search_test_assets(db_path: str) -> list[int]:
    """Insert assets with varied model names, providers, teams, endpoints, and tags."""
    now = datetime.utcnow()

    assets = [
        AiAsset(
            provider="openai",
            model_name="gpt-4o",
            endpoint_url="https://api.openai.com/v1/chat/completions",
            status="approved",
            risk_tier="high",
            owner_team="ml-team",
            first_seen_at=now,
            last_active_at=now,
            created_at=now,
            updated_at=now,
            tags={"env": "prod"},
        ),
        AiAsset(
            provider="anthropic",
            model_name="claude-3-5-sonnet",
            endpoint_url="https://api.anthropic.com/v1/messages",
            status="approved",
            risk_tier="low",
            owner_team="platform-team",
            first_seen_at=now,
            last_active_at=now,
            created_at=now,
            updated_at=now,
            tags={"env": "staging"},
        ),
        AiAsset(
            provider="google",
            model_name="gemini-pro",
            endpoint_url="https://generativelanguage.googleapis.com/v1beta/models",
            status="shadow",
            risk_tier="unclassified",
            owner_team=None,
            first_seen_at=now,
            last_active_at=now,
            created_at=now,
            updated_at=now,
            tags={"env": "dev"},
        ),
        AiAsset(
            provider="openai",
            model_name="gpt-3.5-turbo",
            endpoint_url="https://api.openai.com/v1/completions",
            status="shadow",
            risk_tier="medium",
            owner_team="data-team",
            first_seen_at=now,
            last_active_at=now,
            created_at=now,
            updated_at=now,
            tags={"env": "prod"},
        ),
    ]

    ids: list[int] = []
    for a in assets:
        row_id = await insert_asset(db_path, a)
        ids.append(row_id)
    return ids


class TestAssetSearch:
    """Tests for search_query parameter on get_assets, get_assets_count, and GET /api/v1/assets?search=."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, tmp_path):
        """Create a fresh DB and mount the asset router on a test FastAPI app."""
        from fastapi import FastAPI
        from burnlens.api.assets import router as assets_router

        self.db_path = str(tmp_path / "test_search.db")
        await init_db(self.db_path)
        await _insert_search_test_assets(self.db_path)

        app = FastAPI()
        app.state.db_path = self.db_path
        app.include_router(assets_router, prefix="/api/v1/assets")

        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        yield
        await self.client.aclose()

    @pytest.mark.asyncio
    async def test_search_by_model_name(self):
        """Test 1: get_assets(search_query='gpt') returns assets where model_name LIKE '%gpt%'."""
        from burnlens.storage.queries import get_assets

        results = await get_assets(self.db_path, search_query="gpt")
        assert len(results) == 2, f"Expected 2 gpt assets, got {len(results)}"
        for r in results:
            assert "gpt" in r.model_name.lower()

    @pytest.mark.asyncio
    async def test_search_by_provider(self):
        """Test 2: get_assets(search_query='openai') returns assets where provider LIKE '%openai%'."""
        from burnlens.storage.queries import get_assets

        results = await get_assets(self.db_path, search_query="openai")
        assert len(results) == 2, f"Expected 2 openai assets, got {len(results)}"
        for r in results:
            assert "openai" in r.provider.lower() or "openai" in r.endpoint_url.lower()

    @pytest.mark.asyncio
    async def test_search_by_owner_team(self):
        """Test 3: get_assets(search_query='ml-team') returns assets where owner_team LIKE '%ml-team%'."""
        from burnlens.storage.queries import get_assets

        results = await get_assets(self.db_path, search_query="ml-team")
        assert len(results) == 1
        assert results[0].owner_team == "ml-team"

    @pytest.mark.asyncio
    async def test_search_by_endpoint_url(self):
        """Test 4: get_assets(search_query='api.openai.com') returns assets where endpoint_url LIKE '%api.openai.com%'."""
        from burnlens.storage.queries import get_assets

        results = await get_assets(self.db_path, search_query="api.openai.com")
        assert len(results) == 2, f"Expected 2 openai endpoint assets, got {len(results)}"
        for r in results:
            assert "api.openai.com" in r.endpoint_url

    @pytest.mark.asyncio
    async def test_search_by_tag_value(self):
        """Test 5: get_assets(search_query='env:prod') returns assets where tags LIKE '%env:prod%' (JSON serialized)."""
        from burnlens.storage.queries import get_assets

        # Tags are stored as JSON: {"env": "prod"} → search for 'prod' to find them
        results = await get_assets(self.db_path, search_query="prod")
        assert len(results) == 2, f"Expected 2 assets with env:prod tag, got {len(results)}"

    @pytest.mark.asyncio
    async def test_get_assets_count_with_search(self):
        """Test 6: get_assets_count(search_query='gpt') returns correct count matching search."""
        from burnlens.storage.queries import get_assets_count

        count = await get_assets_count(self.db_path, search_query="gpt")
        assert count == 2

    @pytest.mark.asyncio
    async def test_api_search_param(self):
        """Test 7: GET /api/v1/assets?search=gpt returns filtered results."""
        resp = await self.client.get("/api/v1/assets?search=gpt")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        for item in data["items"]:
            assert "gpt" in item["model_name"].lower()

    @pytest.mark.asyncio
    async def test_search_combines_with_provider_filter(self):
        """Test 8: search combines with other filters: get_assets(provider='openai', search_query='gpt-4') narrows correctly."""
        from burnlens.storage.queries import get_assets

        results = await get_assets(self.db_path, provider="openai", search_query="gpt-4")
        assert len(results) == 1
        assert results[0].model_name == "gpt-4o"
        assert results[0].provider == "openai"
