"""Nyquist validation tests for Phase 3: Asset Management API.

These tests fill coverage gaps identified during phase validation.
Each test targets a specific requirement behavior not covered by existing tests.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from burnlens.storage.database import init_db, insert_asset, insert_discovery_event
from burnlens.storage.models import AiAsset, DiscoveryEvent


def _make_asset(
    provider: str = "openai",
    model_name: str = "gpt-4o",
    endpoint_url: str = "https://api.openai.com",
    status: str = "shadow",
    risk_tier: str = "unclassified",
    first_seen_at: datetime | None = None,
    owner_team: str | None = None,
    tags: dict | None = None,
) -> AiAsset:
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
        tags=tags or {},
    )


# ---------------------------------------------------------------------------
# API-01: Pagination actually slices results
# ---------------------------------------------------------------------------


class TestAPI01Pagination:
    """Validate that limit and offset actually control result windowing."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, tmp_path):
        from fastapi import FastAPI
        from burnlens.api.assets import router as assets_router

        self.db_path = str(tmp_path / "test.db")
        await init_db(self.db_path)

        app = FastAPI()
        app.state.db_path = self.db_path
        app.include_router(assets_router, prefix="/api/v1/assets")
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        yield
        await self.client.aclose()

    @pytest.mark.asyncio
    async def test_limit_restricts_returned_items(self):
        """API-01: limit=2 on 4 assets returns 2 items but total=4."""
        for i in range(4):
            await insert_asset(self.db_path, _make_asset(model_name=f"model-{i}"))

        resp = await self.client.get("/api/v1/assets?limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 4
        assert data["limit"] == 2

    @pytest.mark.asyncio
    async def test_offset_skips_items(self):
        """API-01: offset=2 with limit=2 on 4 assets returns the last 2 items."""
        for i in range(4):
            await insert_asset(self.db_path, _make_asset(model_name=f"model-{i}"))

        resp = await self.client.get("/api/v1/assets?limit=2&offset=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 4
        assert data["offset"] == 2


# ---------------------------------------------------------------------------
# API-05: Shadow endpoints filtered by date range (combined filter)
# ---------------------------------------------------------------------------


class TestAPI05ShadowDateFilter:
    """Validate listing shadow assets filtered by date_since (combined)."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, tmp_path):
        from fastapi import FastAPI
        from burnlens.api.assets import router as assets_router

        self.db_path = str(tmp_path / "test.db")
        await init_db(self.db_path)

        app = FastAPI()
        app.state.db_path = self.db_path
        app.include_router(assets_router, prefix="/api/v1/assets")
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        yield
        await self.client.aclose()

    @pytest.mark.asyncio
    async def test_shadow_plus_date_since_combined(self):
        """API-05: status=shadow&date_since returns only recent shadow assets."""
        # Shadow, old
        await insert_asset(self.db_path, _make_asset(
            status="shadow", first_seen_at=datetime(2025, 6, 1), model_name="old-shadow",
        ))
        # Shadow, recent
        await insert_asset(self.db_path, _make_asset(
            status="shadow", first_seen_at=datetime(2026, 3, 15), model_name="new-shadow",
        ))
        # Approved, recent (should be excluded by status filter)
        await insert_asset(self.db_path, _make_asset(
            status="approved", first_seen_at=datetime(2026, 3, 20), model_name="new-approved",
        ))

        resp = await self.client.get("/api/v1/assets?status=shadow&date_since=2026-01-01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["model_name"] == "new-shadow"
        assert data["items"][0]["status"] == "shadow"


# ---------------------------------------------------------------------------
# API-03: Partial update preserves untouched fields
# ---------------------------------------------------------------------------


class TestAPI03PartialUpdatePreservation:
    """Validate that PATCH only changes specified fields, preserving others."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, tmp_path):
        from fastapi import FastAPI
        from burnlens.api.assets import router as assets_router

        self.db_path = str(tmp_path / "test.db")
        await init_db(self.db_path)

        app = FastAPI()
        app.state.db_path = self.db_path
        app.include_router(assets_router, prefix="/api/v1/assets")
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        yield
        await self.client.aclose()

    @pytest.mark.asyncio
    async def test_patch_owner_team_preserves_risk_tier_and_tags(self):
        """API-03: Updating owner_team does not reset risk_tier or tags."""
        asset_id = await insert_asset(self.db_path, _make_asset(
            risk_tier="high", owner_team="Original", tags={"env": "prod"},
        ))

        # Update only owner_team
        resp = await self.client.patch(
            f"/api/v1/assets/{asset_id}",
            json={"owner_team": "NewTeam"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["owner_team"] == "NewTeam"
        assert data["risk_tier"] == "high", "risk_tier was reset unexpectedly"
        assert data["tags"] == {"env": "prod"}, "tags were reset unexpectedly"


# ---------------------------------------------------------------------------
# API-06: Approve returns 404 for non-existent asset
# ---------------------------------------------------------------------------


class TestAPI06Approve404:
    """Validate approve endpoint returns 404 for non-existent asset."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, tmp_path):
        from fastapi import FastAPI
        from burnlens.api.assets import router as assets_router

        self.db_path = str(tmp_path / "test.db")
        await init_db(self.db_path)

        app = FastAPI()
        app.state.db_path = self.db_path
        app.include_router(assets_router, prefix="/api/v1/assets")
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        yield
        await self.client.aclose()

    @pytest.mark.asyncio
    async def test_approve_nonexistent_asset_returns_404(self):
        """API-06: POST /approve on non-existent asset returns 404."""
        resp = await self.client.post("/api/v1/assets/99999/approve")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Router mounting: All Phase 3 routes live in server.py
# ---------------------------------------------------------------------------


class TestRouterMounting:
    """Validate all Phase 3 API routes are mounted in the production server app."""

    def test_all_api_v1_routes_mounted_in_server(self):
        """All 8 route paths from Phase 3 are present in get_app()."""
        from burnlens.config import BurnLensConfig
        from burnlens.proxy.server import get_app

        config = BurnLensConfig()
        app = get_app(config)

        routes = [r.path for r in app.routes if hasattr(r, "path")]

        expected_fragments = [
            "/api/v1/assets",           # list
            "/api/v1/assets/summary",   # summary
            "/api/v1/assets/{asset_id}",  # detail + patch
            "/api/v1/assets/{asset_id}/approve",  # approve
            "/api/v1/discovery/events",  # discovery events
            "/api/v1/providers/signatures",  # provider signatures
        ]

        for fragment in expected_fragments:
            assert any(fragment in r for r in routes), (
                f"Expected route containing '{fragment}' not found in {routes}"
            )
