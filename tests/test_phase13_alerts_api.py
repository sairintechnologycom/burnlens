"""Tests for alerts API endpoints (GET /api/v1/alert-rules, PATCH /api/v1/alert-rules/{id})."""

import pytest
from unittest.mock import patch, AsyncMock
from uuid import uuid4
import time

from burnlens_cloud.models import TokenPayload
from burnlens_cloud.auth import verify_token as _verify_token


def _auth(app, token):
    """Override the verify_token FastAPI dependency for a single test."""
    app.dependency_overrides[_verify_token] = lambda: token


def _make_alerts_app():
    from fastapi import FastAPI
    from burnlens_cloud.alerts_api import router as alerts_router
    app = FastAPI()
    app.include_router(alerts_router)
    return app


@pytest.fixture
def owner_token():
    return TokenPayload(
        workspace_id=uuid4(), user_id=uuid4(),
        role="owner", plan="cloud",
        iat=int(time.time()), exp=int(time.time()) + 86400,
    )


@pytest.fixture
def viewer_token():
    return TokenPayload(
        workspace_id=uuid4(), user_id=uuid4(),
        role="viewer", plan="cloud",
        iat=int(time.time()), exp=int(time.time()) + 86400,
    )


class TestAlertRulesGet:

    @pytest.mark.asyncio
    async def test_list_alert_rules_200(self, owner_token):
        from httpx import AsyncClient, ASGITransport
        app = _make_alerts_app()
        _auth(app, owner_token)
        mock_rows = [
            {"id": str(uuid4()), "threshold_pct": 80, "channel": "email",
             "enabled": True, "has_slack": False, "extra_emails": [],
             "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"},
        ]
        with patch("burnlens_cloud.alerts_api.execute_query", AsyncMock(return_value=mock_rows)):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
                response = await ac.get("/api/v1/alert-rules")
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["threshold_pct"] == 80

    @pytest.mark.asyncio
    async def test_list_rules_viewer_allowed(self, viewer_token):
        from httpx import AsyncClient, ASGITransport
        app = _make_alerts_app()
        _auth(app, viewer_token)
        with patch("burnlens_cloud.alerts_api.execute_query", AsyncMock(return_value=[])):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
                response = await ac.get("/api/v1/alert-rules")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_rules_scoped_to_workspace(self, owner_token):
        from httpx import AsyncClient, ASGITransport
        app = _make_alerts_app()
        _auth(app, owner_token)
        mock_execute_query = AsyncMock(return_value=[])
        with patch("burnlens_cloud.alerts_api.execute_query", mock_execute_query):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
                await ac.get("/api/v1/alert-rules")
        # First positional arg after the SQL string must be the token workspace_id
        call_args = mock_execute_query.call_args
        assert call_args is not None
        assert owner_token.workspace_id in call_args.args or owner_token.workspace_id in call_args.kwargs.values()


class TestAlertRulesPatch:

    @pytest.mark.asyncio
    async def test_patch_toggle_enabled(self, owner_token):
        from httpx import AsyncClient, ASGITransport
        app = _make_alerts_app()
        _auth(app, owner_token)
        with patch("burnlens_cloud.alerts_api.execute_insert", AsyncMock(return_value="UPDATE 1")):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
                response = await ac.patch(
                    f"/api/v1/alert-rules/{uuid4()}",
                    json={"enabled": True},
                )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_patch_idor_protection(self, owner_token):
        """UPDATE with workspace_id mismatch returns 0 rows -> 404, not 200."""
        from httpx import AsyncClient, ASGITransport
        app = _make_alerts_app()
        _auth(app, owner_token)
        with patch("burnlens_cloud.alerts_api.execute_insert", AsyncMock(return_value="UPDATE 0")):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
                response = await ac.patch(
                    f"/api/v1/alert-rules/{uuid4()}",
                    json={"enabled": True},
                )
        assert response.status_code == 404
        assert response.json()["detail"] == "rule_not_found"

    @pytest.mark.asyncio
    async def test_patch_invalid_threshold(self, owner_token):
        from httpx import AsyncClient, ASGITransport
        app = _make_alerts_app()
        _auth(app, owner_token)
        mock_insert = AsyncMock()
        with patch("burnlens_cloud.alerts_api.execute_insert", mock_insert):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
                response = await ac.patch(
                    f"/api/v1/alert-rules/{uuid4()}",
                    json={"threshold_pct": 50},
                )
        assert response.status_code == 422
        mock_insert.assert_not_called()

    @pytest.mark.asyncio
    async def test_patch_extra_emails(self, owner_token):
        from httpx import AsyncClient, ASGITransport
        app = _make_alerts_app()
        _auth(app, owner_token)
        with patch("burnlens_cloud.alerts_api.execute_insert", AsyncMock(return_value="UPDATE 1")):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
                response = await ac.patch(
                    f"/api/v1/alert-rules/{uuid4()}",
                    json={"extra_emails": ["test@example.com"]},
                )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_patch_viewer_forbidden(self, viewer_token):
        from httpx import AsyncClient, ASGITransport
        app = _make_alerts_app()
        _auth(app, viewer_token)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            response = await ac.patch(
                f"/api/v1/alert-rules/{uuid4()}",
                json={"enabled": True},
            )
        assert response.status_code == 403
