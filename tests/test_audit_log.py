"""Tests for audit logging endpoints."""

import datetime
import time
from types import SimpleNamespace

import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock
from uuid import uuid4


def _plan(name):
    """Patch the server-side plan lookup that require_enterprise reads."""
    return patch(
        "burnlens_cloud.plans.resolve_limits",
        AsyncMock(return_value=SimpleNamespace(plan=name, gated_features={})),
    )

from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from burnlens_cloud.models import TokenPayload
from burnlens_cloud.auth import verify_token as _verify_token
from burnlens_cloud.compliance.audit import router as audit_router


@pytest_asyncio.fixture
async def audit_client():
    """(AsyncClient, FastAPI app) with the audit-log router mounted.

    Tests inject auth via `app.dependency_overrides[_verify_token]` (see
    `_auth`) — the same pattern used by the settings/alerts cloud tests.
    """
    app = FastAPI()
    app.include_router(audit_router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac, app


def _auth(app, token):
    """Override the verify_token FastAPI dependency for a single test."""
    app.dependency_overrides[_verify_token] = lambda: token


@pytest.fixture
def enterprise_admin_token():
    """Create admin token for enterprise plan."""
    return TokenPayload(
        workspace_id=uuid4(),
        user_id=uuid4(),
        role="admin",
        plan="enterprise",
        iat=int(time.time()),
        exp=int(time.time()) + 86400,
    )


@pytest.fixture
def non_enterprise_admin_token():
    """Create admin token for non-enterprise plan."""
    return TokenPayload(
        workspace_id=uuid4(),
        user_id=uuid4(),
        role="admin",
        plan="cloud",
        iat=int(time.time()),
        exp=int(time.time()) + 86400,
    )


class TestAuditLogEndpoint:
    """Test audit log query endpoint."""

    @pytest.fixture(autouse=True)
    def _default_enterprise(self):
        with _plan("enterprise"):
            yield

    @pytest.mark.asyncio
    async def test_audit_log_enterprise_only(self, audit_client, non_enterprise_admin_token):
        """GET /api/audit-log should reject non-enterprise plans (server-side, not JWT)."""
        ac, app = audit_client
        _auth(app, non_enterprise_admin_token)

        with _plan("cloud"):
            response = await ac.get("/api/audit-log")

        assert response.status_code == 403
        assert "enterprise" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_audit_log_admin_only(self, audit_client):
        """GET /api/audit-log should require admin+ role."""
        viewer_token = TokenPayload(
            workspace_id=uuid4(),
            user_id=uuid4(),
            role="viewer",
            plan="enterprise",
            iat=int(time.time()),
            exp=int(time.time()) + 86400,
        )

        ac, app = audit_client
        _auth(app, viewer_token)

        response = await ac.get("/api/audit-log")
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_audit_log_success(self, audit_client, enterprise_admin_token):
        """GET /api/audit-log should return paginated audit entries."""
        ac, app = audit_client
        _auth(app, enterprise_admin_token)

        mock_db = AsyncMock()
        # Mock count query
        mock_db.fetchval.return_value = 50
        # Mock fetch query
        mock_db.fetch.return_value = [
            {
                "id": 1,
                "action": "invite_member",
                "detail": {"email": "alice@example.com"},
                "created_at": datetime.datetime.utcnow(),
                "ip_address": "192.168.1.1",
                "user_agent": "Mozilla/5.0",
                "api_key_last4": "xxxx",
                "email_encrypted": "bob@example.com",
                "user_name": "Bob Smith",
            }
        ]

        with patch(
            "burnlens_cloud.compliance.audit.get_db",
            AsyncMock(return_value=mock_db),
        ), patch("burnlens_cloud.compliance.audit.decrypt_pii", lambda c: c):
            response = await ac.get("/api/audit-log?days=90&limit=10&offset=0")

        assert response.status_code == 200
        data = response.json()
        assert "entries" in data
        assert data["total"] == 50
        assert data["limit"] == 10
        assert data["offset"] == 0

    @pytest.mark.asyncio
    async def test_audit_log_includes_user_info(self, audit_client, enterprise_admin_token):
        """Audit log should include user information."""
        ac, app = audit_client
        _auth(app, enterprise_admin_token)

        mock_db = AsyncMock()
        mock_db.fetchval.return_value = 1
        mock_db.fetch.return_value = [
            {
                "id": 1,
                "action": "update_custom_pricing",
                "detail": {"models_updated": ["gpt-4o"]},
                "created_at": datetime.datetime.utcnow(),
                "ip_address": "10.0.0.1",
                "user_agent": "curl/7.68.0",
                "api_key_last4": "4567",
                "email_encrypted": "admin@example.com",
                "user_name": "Admin User",
            }
        ]

        with patch(
            "burnlens_cloud.compliance.audit.get_db",
            AsyncMock(return_value=mock_db),
        ), patch("burnlens_cloud.compliance.audit.decrypt_pii", lambda c: c):
            response = await ac.get("/api/audit-log")

        assert response.status_code == 200
        entry = response.json()["entries"][0]
        assert entry["user"] is not None
        assert "Admin User" in entry["user"]
        assert "admin@example.com" in entry["user"]  # decrypted from email_encrypted
        assert entry["ip_address"] == "10.0.0.1"
        assert entry["api_key_last4"] == "4567"

    @pytest.mark.asyncio
    async def test_audit_log_pagination(self, audit_client, enterprise_admin_token):
        """Audit log should support pagination."""
        ac, app = audit_client
        _auth(app, enterprise_admin_token)

        mock_db = AsyncMock()
        mock_db.fetchval.return_value = 1000
        mock_db.fetch.return_value = []

        with patch(
            "burnlens_cloud.compliance.audit.get_db",
            AsyncMock(return_value=mock_db),
        ):
            # Request page 2 with limit 100
            response = await ac.get("/api/audit-log?limit=100&offset=100")

        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 100
        assert data["offset"] == 100


class TestAuditLogCsvExport:
    """Test audit log CSV export."""

    @pytest.fixture(autouse=True)
    def _default_enterprise(self):
        with _plan("enterprise"):
            yield

    @pytest.mark.asyncio
    async def test_export_csv_enterprise_only(self, audit_client, non_enterprise_admin_token):
        """CSV export should reject non-enterprise plans (server-side, not JWT)."""
        ac, app = audit_client
        _auth(app, non_enterprise_admin_token)

        with _plan("cloud"):
            response = await ac.get("/api/audit-log/export")

        assert response.status_code == 403
        assert "enterprise" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_export_csv_format(self, audit_client, enterprise_admin_token):
        """CSV export should include all audit fields."""
        ac, app = audit_client
        _auth(app, enterprise_admin_token)

        mock_db = AsyncMock()
        mock_db.fetch.return_value = [
            {
                "id": 1,
                "action": "invite_member",
                "detail": {"email": "alice@example.com", "role": "admin"},
                "created_at": datetime.datetime(2025, 1, 1, 12, 0, 0),
                "ip_address": "192.168.1.1",
                "user_agent": "Mozilla/5.0",
                "api_key_last4": "abcd",
                "email_encrypted": "bob@example.com",
                "user_name": "Bob",
            }
        ]

        with patch(
            "burnlens_cloud.compliance.audit.get_db",
            AsyncMock(return_value=mock_db),
        ), patch("burnlens_cloud.compliance.audit.decrypt_pii", lambda c: c):
            response = await ac.get("/api/audit-log/export")

        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "attachment" in response.headers["content-disposition"]

    @pytest.mark.asyncio
    async def test_export_csv_content(self, audit_client, enterprise_admin_token):
        """CSV export should contain audit data."""
        ac, app = audit_client
        _auth(app, enterprise_admin_token)

        mock_db = AsyncMock()
        mock_db.fetch.return_value = [
            {
                "id": 1,
                "action": "update_custom_pricing",
                "detail": {"models_updated": ["gpt-4o"]},
                "created_at": datetime.datetime(2025, 1, 1, 12, 0, 0),
                "ip_address": "10.0.0.1",
                "user_agent": "curl/7.68",
                "api_key_last4": "xyz1",
                "email_encrypted": "admin@example.com",
                "user_name": "Admin",
            }
        ]

        with patch(
            "burnlens_cloud.compliance.audit.get_db",
            AsyncMock(return_value=mock_db),
        ), patch("burnlens_cloud.compliance.audit.decrypt_pii", lambda c: c):
            response = await ac.get("/api/audit-log/export")

        content = response.text
        assert "Timestamp" in content  # Header
        assert "User" in content
        assert "Action" in content
        assert "update_custom_pricing" in content
        assert "admin@example.com" in content  # decrypted from email_encrypted

    @pytest.mark.asyncio
    async def test_export_csv_filename_timestamp(self, audit_client, enterprise_admin_token):
        """CSV filename should include date."""
        ac, app = audit_client
        _auth(app, enterprise_admin_token)

        mock_db = AsyncMock()
        mock_db.fetch.return_value = []

        with patch(
            "burnlens_cloud.compliance.audit.get_db",
            AsyncMock(return_value=mock_db),
        ):
            response = await ac.get("/api/audit-log/export")

        disposition = response.headers["content-disposition"]
        assert "audit-log" in disposition
        assert ".csv" in disposition


class TestAuditLogQueryColumns:
    """Guard against the Phase 1c dropped-column regression.

    users.email was dropped in Phase 1c; both audit queries must select
    u.email_encrypted (and decrypt in Python), never u.email — otherwise
    every call 500s in prod while unit tests that mock the row shape pass.
    """

    @pytest.fixture(autouse=True)
    def _default_enterprise(self):
        with _plan("enterprise"):
            yield

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ["/api/audit-log", "/api/audit-log/export"])
    async def test_query_selects_encrypted_email_not_dropped_column(
        self, audit_client, enterprise_admin_token, path
    ):
        ac, app = audit_client
        _auth(app, enterprise_admin_token)

        mock_db = AsyncMock()
        mock_db.fetchval.return_value = 0
        mock_db.fetch.return_value = []

        with patch(
            "burnlens_cloud.compliance.audit.get_db",
            AsyncMock(return_value=mock_db),
        ):
            await ac.get(path)

        sql = mock_db.fetch.call_args.args[0]
        assert "email_encrypted" in sql
        assert "u.email " not in sql and "u.email\n" not in sql
        assert "u.email," not in sql
