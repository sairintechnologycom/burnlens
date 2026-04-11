"""Tests for Phase 5: Discovery Dashboard — validates DASH-01 through DASH-08.

Covers:
- /ui/discovery route serves discovery.html (DASH-01 smoke)
- discovery.html contains all required structural elements (DASH-01..08)
- discovery.js contains all required functions (DASH-01..08)
- Asset summary API returns new_this_week at HTTP level (DASH-06)
- Discovery route is registered before StaticFiles mount (DASH-01)
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from burnlens.config import BurnLensConfig
from burnlens.storage.database import init_db, insert_asset
from burnlens.storage.models import AiAsset


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STATIC_DIR = Path(__file__).resolve().parent.parent / "burnlens" / "dashboard" / "static"


def _read_static(filename: str) -> str:
    """Read a static file from the dashboard directory."""
    return (_STATIC_DIR / filename).read_text()


def _make_asset(**overrides) -> AiAsset:
    now = datetime.utcnow()
    defaults = dict(
        provider="openai",
        model_name="gpt-4o",
        endpoint_url="https://api.openai.com/v1/chat/completions",
        status="shadow",
        risk_tier="unclassified",
        owner_team=None,
        first_seen_at=now,
        last_active_at=now,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return AiAsset(**defaults)


# ---------------------------------------------------------------------------
# DASH-01: Discovery route serves HTML page
# ---------------------------------------------------------------------------


class TestDiscoveryRouteServed:
    """Verify /ui/discovery route is registered and serves discovery.html."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, tmp_path):
        self.db_path = str(tmp_path / "test.db")
        await init_db(self.db_path)

        config = BurnLensConfig()
        config.db_path = self.db_path

        from burnlens.proxy.server import get_app
        app = get_app(config)
        app.state.db_path = self.db_path

        self.client = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        )
        yield
        await self.client.aclose()

    @pytest.mark.asyncio
    async def test_discovery_route_returns_html(self):
        """DASH-01: GET /ui/discovery returns 200 with HTML content."""
        resp = await self.client.get("/ui/discovery")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert "text/html" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_discovery_page_contains_title(self):
        """DASH-01: Served page contains the BurnLens discovery title."""
        resp = await self.client.get("/ui/discovery")
        assert resp.status_code == 200
        assert "AI Asset Discovery" in resp.text


# ---------------------------------------------------------------------------
# DASH-01..08: discovery.html structural element tests
# ---------------------------------------------------------------------------


class TestDiscoveryHtmlStructure:
    """Verify discovery.html contains all DOM elements required by DASH-01..08."""

    @pytest.fixture(autouse=True)
    def load_html(self):
        self.html = _read_static("discovery.html")

    def test_dash01_kpi_cards_present(self):
        """DASH-01: HTML has all 5 KPI card IDs."""
        for card_id in [
            "kpi-total-assets",
            "kpi-active-month",
            "kpi-shadow",
            "kpi-unassigned",
            "kpi-monthly-spend",
        ]:
            assert card_id in self.html, f"Missing KPI card: {card_id}"

    def test_dash02_provider_chart_canvas(self):
        """DASH-02: HTML has canvas element for provider donut chart."""
        assert 'id="provider-chart"' in self.html

    def test_dash03_sortable_table_headers(self):
        """DASH-03: HTML has 8 sortable table headers with data-col attributes."""
        expected_cols = [
            "model_name", "provider", "owner_team", "status",
            "risk_tier", "monthly_spend_usd", "first_seen_at", "last_active_at",
        ]
        for col in expected_cols:
            assert f'data-col="{col}"' in self.html, f"Missing sortable column: {col}"

    def test_dash03_filter_dropdowns(self):
        """DASH-03: HTML has filter dropdowns for provider, status, risk, team, and date."""
        for fid in [
            "filter-provider", "filter-status", "filter-risk",
            "filter-team", "filter-date-since",
        ]:
            assert fid in self.html, f"Missing filter element: {fid}"

    def test_dash04_shadow_panel_section(self):
        """DASH-04: HTML has shadow panel section with count badge."""
        assert 'id="shadow-panel-section"' in self.html
        assert 'id="shadow-panel"' in self.html
        assert 'id="shadow-panel-count"' in self.html

    def test_dash05_timeline_section(self):
        """DASH-05: HTML has discovery timeline section."""
        assert 'id="timeline-section"' in self.html
        assert 'id="timeline-panel"' in self.html

    def test_dash06_new_this_week_panel(self):
        """DASH-06: HTML has new-this-week panel."""
        assert 'id="new-this-week-panel"' in self.html
        assert 'id="new-this-week-list"' in self.html

    def test_dash07_global_search_input(self):
        """DASH-07: HTML has global search input."""
        assert 'id="global-search"' in self.html
        assert 'type="search"' in self.html

    def test_dash08_saved_views_ui(self):
        """DASH-08: HTML has saved views dropdown, save button, delete button, and form."""
        for eid in [
            "saved-views-select", "save-view-btn", "delete-view-btn",
            "save-view-form", "view-name-input", "confirm-save-view",
        ]:
            assert eid in self.html, f"Missing saved views element: {eid}"

    def test_pagination_controls(self):
        """DASH-03: HTML has pagination controls."""
        assert 'id="asset-pagination"' in self.html
        assert 'id="btn-prev"' in self.html
        assert 'id="btn-next"' in self.html

    def test_navigation_links(self):
        """DASH-01: Header has links to main dashboard and discovery page."""
        assert 'href="/ui/"' in self.html
        assert 'href="/ui/discovery"' in self.html


# ---------------------------------------------------------------------------
# DASH-01..08: discovery.js function presence tests
# ---------------------------------------------------------------------------


class TestDiscoveryJsFunctions:
    """Verify discovery.js contains all required functions for DASH-01..08."""

    @pytest.fixture(autouse=True)
    def load_js(self):
        self.js = _read_static("discovery.js")

    def test_dash01_fetch_asset_summary(self):
        """DASH-01: JS has fetchAssetSummary function that calls assets/summary."""
        assert "fetchAssetSummary" in self.js
        assert "assets/summary" in self.js

    def test_dash01_fetch_assets(self):
        """DASH-01: JS has fetchAssets function that calls assets API."""
        assert "fetchAssets" in self.js

    def test_dash02_render_provider_chart(self):
        """DASH-02: JS has renderProviderChart using Chart.js Doughnut type."""
        assert "renderProviderChart" in self.js
        assert "doughnut" in self.js.lower() or "Doughnut" in self.js

    def test_dash03_sort_logic(self):
        """DASH-03: JS has sort state tracking and sort function."""
        assert "sortable" in self.js or "sortAssetData" in self.js or "_assetSort" in self.js

    def test_dash04_shadow_functions(self):
        """DASH-04: JS has fetchShadowAssets, handleApprove, handleAssignTeam."""
        assert "fetchShadowAssets" in self.js
        assert "handleApprove" in self.js
        assert "handleAssignTeam" in self.js

    def test_dash04_approve_calls_post(self):
        """DASH-04: JS handleApprove calls POST to /approve endpoint."""
        assert "/approve" in self.js
        assert "'POST'" in self.js or '"POST"' in self.js

    def test_dash04_assign_team_calls_patch(self):
        """DASH-04: JS handleAssignTeam calls PATCH with owner_team."""
        assert "'PATCH'" in self.js or '"PATCH"' in self.js
        assert "owner_team" in self.js

    def test_dash05_fetch_timeline(self):
        """DASH-05: JS has fetchTimeline that calls discovery/events."""
        assert "fetchTimeline" in self.js
        assert "discovery/events" in self.js

    def test_dash06_new_this_week_rendering(self):
        """DASH-06: JS renders new-this-week content."""
        assert "new-this-week" in self.js or "renderNewThisWeek" in self.js or "new_this_week" in self.js

    def test_dash07_search_handler_with_debounce(self):
        """DASH-07: JS has search handler with debounce logic."""
        assert "handleSearch" in self.js
        assert "debounce" in self.js.lower() or "setTimeout" in self.js

    def test_dash07_search_param_passed_to_api(self):
        """DASH-07: JS passes search param in API fetch calls."""
        assert "search" in self.js

    def test_dash08_saved_views_localStorage(self):
        """DASH-08: JS uses localStorage for saved views."""
        assert "localStorage" in self.js
        assert "burnlens_saved_views" in self.js

    def test_dash08_saved_views_crud(self):
        """DASH-08: JS has save, load, delete, and render functions for views."""
        for fn in ["saveView", "loadView", "deleteView", "renderSavedViewsDropdown"]:
            assert fn in self.js, f"Missing saved views function: {fn}"

    def test_dash08_get_current_filters(self):
        """DASH-08: JS has getCurrentFilters to capture filter state."""
        assert "getCurrentFilters" in self.js


# ---------------------------------------------------------------------------
# DASH-01 + DASH-06: Asset summary API returns new_this_week at HTTP level
# ---------------------------------------------------------------------------


class TestAssetSummaryAPINewThisWeek:
    """Verify GET /api/v1/assets/summary includes new_this_week count at API level."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup(self, tmp_path):
        from fastapi import FastAPI
        from burnlens.api.assets import router as assets_router

        self.db_path = str(tmp_path / "test.db")
        await init_db(self.db_path)

        app = FastAPI()
        app.state.db_path = self.db_path
        app.include_router(assets_router, prefix="/api/v1/assets")

        self.client = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        )
        yield
        await self.client.aclose()

    @pytest.mark.asyncio
    async def test_summary_includes_new_this_week_field(self):
        """DASH-06: Summary endpoint includes new_this_week in response."""
        now = datetime.utcnow()
        recent = now - timedelta(days=2)
        old = now - timedelta(days=14)

        await insert_asset(self.db_path, _make_asset(
            model_name="recent-model",
            first_seen_at=recent,
        ))
        await insert_asset(self.db_path, _make_asset(
            model_name="old-model",
            first_seen_at=old,
        ))

        resp = await self.client.get("/api/v1/assets/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "new_this_week" in data
        assert data["new_this_week"] == 1
        assert data["total"] == 2


# ---------------------------------------------------------------------------
# DASH-01: CSS contains discovery-specific styles
# ---------------------------------------------------------------------------


class TestDiscoveryCssStyles:
    """Verify style.css contains discovery-specific styling."""

    @pytest.fixture(autouse=True)
    def load_css(self):
        self.css = _read_static("style.css")

    def test_discovery_kpi_grid_style(self):
        """DASH-01: CSS has discovery-kpi-grid layout."""
        assert "discovery-kpi-grid" in self.css

    def test_shadow_card_style(self):
        """DASH-04: CSS has shadow-card styling."""
        assert "shadow-card" in self.css or "shadow-panel" in self.css

    def test_timeline_style(self):
        """DASH-05: CSS has timeline styles."""
        assert "timeline" in self.css

    def test_global_search_style(self):
        """DASH-07: CSS has global search styling."""
        assert "global-search" in self.css

    def test_save_view_bar_style(self):
        """DASH-08: CSS has save-view-bar styling."""
        assert "save-view" in self.css

    def test_status_badge_styles(self):
        """DASH-03: CSS has status badge variant styles."""
        assert "status-shadow" in self.css
        assert "status-approved" in self.css or "status-active" in self.css
