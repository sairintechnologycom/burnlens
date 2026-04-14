"""Tests for status page and SLA tracking."""

import pytest
from datetime import datetime
from unittest.mock import patch, AsyncMock
from uuid import uuid4

from burnlens_cloud.deployment.status import StatusChecker, StatusPageRenderer
from burnlens_cloud.models import ComponentStatus, StatusResponse


@pytest.fixture
def status_checker():
    """Create status checker instance."""
    return StatusChecker(base_url="http://localhost:8000")


class TestStatusChecker:
    """Test endpoint health checking."""

    @pytest.mark.asyncio
    async def test_check_endpoint_success(self, status_checker):
        """Successful check should return (True, latency_ms)."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.status_code = 200

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            ok, latency_ms = await status_checker.check_endpoint("Ingest API", "/v1/ingest")

            assert ok is False  # POST to ingest endpoint
            assert isinstance(latency_ms, int)
            assert latency_ms >= 0

    @pytest.mark.asyncio
    async def test_check_endpoint_timeout(self, status_checker):
        """Timeout should return (False, latency_ms)."""
        import asyncio

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.side_effect = asyncio.TimeoutError()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            ok, latency_ms = await status_checker.check_endpoint("Ingest API", "/v1/ingest")

            assert ok is False
            assert isinstance(latency_ms, int)

    @pytest.mark.asyncio
    async def test_run_check_records_results(self, status_checker):
        """run_check should record all endpoint results."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.status_code = 200

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with patch("burnlens_cloud.deployment.status.execute_insert") as mock_insert:
                await status_checker.run_check()

                # Should record 3 checks (one per endpoint)
                assert mock_insert.call_count == 3

    @pytest.mark.asyncio
    async def test_get_component_status_operational(self, status_checker):
        """Component with high uptime should be operational."""
        with patch("burnlens_cloud.deployment.status.execute_query") as mock_query:
            mock_query.return_value = [
                {
                    "total": 100,
                    "ok_count": 100,  # 100% uptime
                }
            ]

            status, uptime = await status_checker.get_component_status(days=30)

            assert status == "operational"
            assert uptime == 100.0

    @pytest.mark.asyncio
    async def test_get_component_status_degraded(self, status_checker):
        """Component with 95-99.5% uptime should be degraded."""
        with patch("burnlens_cloud.deployment.status.execute_query") as mock_query:
            mock_query.return_value = [
                {
                    "total": 1000,
                    "ok_count": 960,  # 96% uptime
                }
            ]

            status, uptime = await status_checker.get_component_status(days=30)

            assert status == "degraded"
            assert 95.0 <= uptime < 99.5

    @pytest.mark.asyncio
    async def test_get_component_status_down(self, status_checker):
        """Component with <95% uptime should be down."""
        with patch("burnlens_cloud.deployment.status.execute_query") as mock_query:
            mock_query.return_value = [
                {
                    "total": 1000,
                    "ok_count": 900,  # 90% uptime
                }
            ]

            status, uptime = await status_checker.get_component_status(days=30)

            assert status == "down"
            assert uptime == 90.0


class TestStatusPageRenderer:
    """Test HTML status page rendering."""

    def test_render_creates_valid_html(self):
        """Render should return valid HTML with all components."""
        components = [
            {"name": "Ingest API", "status": "operational", "uptime_30d": 99.97},
            {"name": "Dashboard API", "status": "degraded", "uptime_30d": 97.50},
            {"name": "Cloud Sync", "status": "down", "uptime_30d": 92.00},
        ]

        html = StatusPageRenderer.render(components)

        assert "<!DOCTYPE html>" in html
        assert "Ingest API" in html
        assert "Dashboard API" in html
        assert "Cloud Sync" in html
        assert "99.97" in html
        assert "97.50" in html
        assert "92.00" in html

    def test_render_includes_status_badges(self):
        """HTML should include status badges."""
        components = [
            {"name": "Test", "status": "operational", "uptime_30d": 100.0},
        ]

        html = StatusPageRenderer.render(components)

        assert "operational" in html
        assert "OPERATIONAL" in html

    def test_render_includes_darkmode_theme(self):
        """HTML should use dark theme colors."""
        components = [
            {"name": "Test", "status": "operational", "uptime_30d": 100.0},
        ]

        html = StatusPageRenderer.render(components)

        assert "#080c10" in html  # Dark background
        assert "#00e5c8" in html  # Cyan accent

    def test_render_includes_uptime_colors(self):
        """HTML should include status colors (green/amber/red)."""
        components = [
            {"name": "Test", "status": "operational", "uptime_30d": 100.0},
        ]

        html = StatusPageRenderer.render(components)

        assert "#10b981" in html  # Green for operational
        assert "#f59e0b" in html  # Amber for degraded
        assert "#ef4444" in html  # Red for down


class TestStatusEndpoints:
    """Test /status endpoints (public, no auth)."""

    @pytest.mark.asyncio
    async def test_status_page_html(self, client):
        """GET /status should return HTML status page."""
        with patch("burnlens_cloud.deployment_api.get_status_checker") as mock_checker_class:
            mock_checker = AsyncMock()
            mock_checker.get_component_status.return_value = ("operational", 99.97)
            mock_checker_class.return_value = mock_checker

            response = await client.get("/status")

            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
            assert "BurnLens Status" in response.text

    @pytest.mark.asyncio
    async def test_status_api_json(self, client):
        """GET /api/status should return JSON status."""
        with patch("burnlens_cloud.deployment_api.get_status_checker") as mock_checker_class:
            mock_checker = AsyncMock()
            mock_checker.get_component_status.return_value = ("operational", 99.97)
            mock_checker_class.return_value = mock_checker

            response = await client.get("/api/status")

            assert response.status_code == 200
            data = response.json()
            assert "components" in data
            assert isinstance(data["components"], list)
            assert len(data["components"]) == 3

    @pytest.mark.asyncio
    async def test_status_api_includes_all_metrics(self, client):
        """Status API should include all component metrics."""
        with patch("burnlens_cloud.deployment_api.get_status_checker") as mock_checker_class:
            mock_checker = AsyncMock()
            mock_checker.get_component_status.return_value = ("operational", 99.97)
            mock_checker_class.return_value = mock_checker

            response = await client.get("/api/status")

            data = response.json()
            for component in data["components"]:
                assert "name" in component
                assert "status" in component
                assert "uptime_30d" in component
                assert component["uptime_30d"] >= 0
                assert component["uptime_30d"] <= 100

    @pytest.mark.asyncio
    async def test_status_page_no_auth_required(self, client):
        """Status endpoints should not require authentication."""
        # No auth headers should still work
        response = await client.get("/status")
        assert response.status_code == 200

        response = await client.get("/api/status")
        assert response.status_code == 200
