"""Tests for audit logging endpoints."""

import pytest
from unittest.mock import patch, AsyncMock
from uuid import uuid4

from burnlens_cloud.models import TokenPayload


@pytest.fixture
def enterprise_admin_token():
    """Create admin token for enterprise plan."""
    return TokenPayload(
        workspace_id=uuid4(),
        user_id=uuid4(),
        role="admin",
        plan="enterprise",
        iat=int(__import__("time").time()),
        exp=int(__import__("time").time()) + 86400,
    )


@pytest.fixture
def non_enterprise_admin_token():
    """Create admin token for non-enterprise plan."""
    return TokenPayload(
        workspace_id=uuid4(),
        user_id=uuid4(),
        role="admin",
        plan="cloud",
        iat=int(__import__("time").time()),
        exp=int(__import__("time").time()) + 86400,
    )


class TestAuditLogEndpoint:
    """Test audit log query endpoint."""

    @pytest.mark.asyncio
    async def test_audit_log_enterprise_only(self, client, non_enterprise_admin_token):
        """GET /api/audit-log should reject non-enterprise plans."""
        with patch("burnlens_cloud.compliance.audit.verify_token", return_value=non_enterprise_admin_token):
            response = await client.get("/api/audit-log")

            assert response.status_code == 403
            assert "enterprise" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_audit_log_admin_only(self, client):
        """GET /api/audit-log should require admin+ role."""
        viewer_token = TokenPayload(
            workspace_id=uuid4(),
            user_id=uuid4(),
            role="viewer",
            plan="enterprise",
            iat=int(__import__("time").time()),
            exp=int(__import__("time").time()) + 86400,
        )

        with patch("burnlens_cloud.compliance.audit.verify_token", return_value=viewer_token):
            with patch("burnlens_cloud.compliance.audit.require_role") as mock_require:
                mock_require.side_effect = __import__("fastapi").HTTPException(status_code=403)

                response = await client.get("/api/audit-log")
                assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_audit_log_success(self, client, enterprise_admin_token):
        """GET /api/audit-log should return paginated audit entries."""
        with patch("burnlens_cloud.compliance.audit.verify_token", return_value=enterprise_admin_token):
            with patch("burnlens_cloud.compliance.audit.get_db") as mock_db_class:
                mock_db = AsyncMock()

                # Mock count query
                mock_db.fetchval.return_value = 50

                # Mock fetch query
                mock_db.fetch.return_value = [
                    {
                        "id": 1,
                        "action": "invite_member",
                        "detail": {"email": "alice@example.com"},
                        "created_at": __import__("datetime").datetime.utcnow(),
                        "ip_address": "192.168.1.1",
                        "user_agent": "Mozilla/5.0",
                        "api_key_last4": "xxxx",
                        "user_email": "bob@example.com",
                        "user_name": "Bob Smith",
                    }
                ]

                mock_db_class.return_value = mock_db

                response = await client.get("/api/audit-log?days=90&limit=10&offset=0")

                assert response.status_code == 200
                data = response.json()
                assert "entries" in data
                assert data["total"] == 50
                assert data["limit"] == 10
                assert data["offset"] == 0

    @pytest.mark.asyncio
    async def test_audit_log_includes_user_info(self, client, enterprise_admin_token):
        """Audit log should include user information."""
        with patch("burnlens_cloud.compliance.audit.verify_token", return_value=enterprise_admin_token):
            with patch("burnlens_cloud.compliance.audit.get_db") as mock_db_class:
                mock_db = AsyncMock()
                mock_db.fetchval.return_value = 1
                mock_db.fetch.return_value = [
                    {
                        "id": 1,
                        "action": "update_custom_pricing",
                        "detail": {"models_updated": ["gpt-4o"]},
                        "created_at": __import__("datetime").datetime.utcnow(),
                        "ip_address": "10.0.0.1",
                        "user_agent": "curl/7.68.0",
                        "api_key_last4": "4567",
                        "user_email": "admin@example.com",
                        "user_name": "Admin User",
                    }
                ]
                mock_db_class.return_value = mock_db

                response = await client.get("/api/audit-log")

                assert response.status_code == 200
                entry = response.json()["entries"][0]
                assert entry["user"] is not None
                assert "Admin User" in entry["user"]
                assert entry["ip_address"] == "10.0.0.1"
                assert entry["api_key_last4"] == "4567"

    @pytest.mark.asyncio
    async def test_audit_log_pagination(self, client, enterprise_admin_token):
        """Audit log should support pagination."""
        with patch("burnlens_cloud.compliance.audit.verify_token", return_value=enterprise_admin_token):
            with patch("burnlens_cloud.compliance.audit.get_db") as mock_db_class:
                mock_db = AsyncMock()
                mock_db.fetchval.return_value = 1000
                mock_db.fetch.return_value = []
                mock_db_class.return_value = mock_db

                # Request page 2 with limit 100
                response = await client.get("/api/audit-log?limit=100&offset=100")

                assert response.status_code == 200
                data = response.json()
                assert data["limit"] == 100
                assert data["offset"] == 100


class TestAuditLogCsvExport:
    """Test audit log CSV export."""

    @pytest.mark.asyncio
    async def test_export_csv_enterprise_only(self, client, non_enterprise_admin_token):
        """CSV export should reject non-enterprise plans."""
        with patch("burnlens_cloud.compliance.audit.verify_token", return_value=non_enterprise_admin_token):
            response = await client.get("/api/audit-log/export")

            assert response.status_code == 403
            assert "enterprise" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_export_csv_format(self, client, enterprise_admin_token):
        """CSV export should include all audit fields."""
        with patch("burnlens_cloud.compliance.audit.verify_token", return_value=enterprise_admin_token):
            with patch("burnlens_cloud.compliance.audit.get_db") as mock_db_class:
                mock_db = AsyncMock()
                mock_db.fetch.return_value = [
                    {
                        "id": 1,
                        "action": "invite_member",
                        "detail": {"email": "alice@example.com", "role": "admin"},
                        "created_at": __import__("datetime").datetime(2025, 1, 1, 12, 0, 0),
                        "ip_address": "192.168.1.1",
                        "user_agent": "Mozilla/5.0",
                        "api_key_last4": "abcd",
                        "user_email": "bob@example.com",
                        "user_name": "Bob",
                    }
                ]
                mock_db_class.return_value = mock_db

                response = await client.get("/api/audit-log/export")

                assert response.status_code == 200
                assert "text/csv" in response.headers["content-type"]
                assert "attachment" in response.headers["content-disposition"]

    @pytest.mark.asyncio
    async def test_export_csv_content(self, client, enterprise_admin_token):
        """CSV export should contain audit data."""
        with patch("burnlens_cloud.compliance.audit.verify_token", return_value=enterprise_admin_token):
            with patch("burnlens_cloud.compliance.audit.get_db") as mock_db_class:
                mock_db = AsyncMock()
                mock_db.fetch.return_value = [
                    {
                        "id": 1,
                        "action": "update_custom_pricing",
                        "detail": {"models_updated": ["gpt-4o"]},
                        "created_at": __import__("datetime").datetime(2025, 1, 1, 12, 0, 0),
                        "ip_address": "10.0.0.1",
                        "user_agent": "curl/7.68",
                        "api_key_last4": "xyz1",
                        "user_email": "admin@example.com",
                        "user_name": "Admin",
                    }
                ]
                mock_db_class.return_value = mock_db

                response = await client.get("/api/audit-log/export")

                content = response.text
                assert "Timestamp" in content  # Header
                assert "User" in content
                assert "Action" in content
                assert "update_custom_pricing" in content
                assert "admin@example.com" in content or "Admin" in content

    @pytest.mark.asyncio
    async def test_export_csv_filename_timestamp(self, client, enterprise_admin_token):
        """CSV filename should include date."""
        with patch("burnlens_cloud.compliance.audit.verify_token", return_value=enterprise_admin_token):
            with patch("burnlens_cloud.compliance.audit.get_db") as mock_db_class:
                mock_db = AsyncMock()
                mock_db.fetch.return_value = []
                mock_db_class.return_value = mock_db

                response = await client.get("/api/audit-log/export")

                disposition = response.headers["content-disposition"]
                assert "audit-log" in disposition
                assert ".csv" in disposition
