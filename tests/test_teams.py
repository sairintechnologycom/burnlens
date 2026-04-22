"""Tests for Teams functionality."""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from datetime import datetime, timedelta

from burnlens_cloud.models import TokenPayload


@pytest_asyncio.fixture
async def client():
    """Create test client with mocked database."""
    from burnlens_cloud.main import get_app

    app = get_app()

    with patch("burnlens_cloud.database.init_db") as mock_init:
        with patch("burnlens_cloud.database.close_db") as mock_close:
            mock_init.return_value = None
            mock_close.return_value = None

            async with AsyncClient(app=app, base_url="http://test") as ac:
                yield ac


@pytest.mark.asyncio
async def test_invite_member_success(client):
    """Test successful member invitation."""
    workspace_id = str(uuid4())
    user_id = str(uuid4())
    admin_id = str(uuid4())

    with patch("burnlens_cloud.team_api.execute_query") as mock_query:
        with patch("burnlens_cloud.team_api.execute_insert") as mock_insert:
            with patch("burnlens_cloud.team_api.send_invitation_email") as mock_email:
                with patch("burnlens_cloud.auth.decode_jwt") as mock_decode:
                    # Mock workspace query
                    mock_query.side_effect = [
                        [{"plan": "teams", "name": "Test Workspace"}],  # Workspace info
                        [],  # Check if user already member
                        [{"count": 2}],  # Check seat limit (2 < 10)
                    ]

                    mock_insert.return_value = None
                    mock_email.return_value = None

                    # Create token
                    token = TokenPayload(
                        workspace_id=workspace_id,
                        user_id=admin_id,
                        role="admin",
                        plan="teams",
                        iat=int(datetime.now().timestamp()),
                        exp=int((datetime.now() + timedelta(hours=24)).timestamp()),
                    )

                    mock_decode.return_value = token

                    response = await client.post(
                        "/team/invite",
                        json={"email": "new@example.com", "role": "viewer"},
                        headers={"Authorization": f"Bearer test-token"},
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert data["email"] == "new@example.com"
                    assert data["token"] is not None
                    assert data["expires_at"] is not None


@pytest.mark.asyncio
async def test_invite_requires_admin_role(client):
    """Test that invite endpoint requires admin role."""
    workspace_id = str(uuid4())
    user_id = str(uuid4())

    with patch("burnlens_cloud.auth.decode_jwt") as mock_decode:
        # Create viewer token
        token = TokenPayload(
            workspace_id=workspace_id,
            user_id=user_id,
            role="viewer",  # Insufficient permission
            plan="teams",
            iat=int(datetime.now().timestamp()),
            exp=int((datetime.now() + timedelta(hours=24)).timestamp()),
        )

        mock_decode.return_value = token

        response = await client.post(
            "/team/invite",
            json={"email": "new@example.com", "role": "viewer"},
            headers={"Authorization": f"Bearer test-token"},
        )

        assert response.status_code == 403
        data = response.json()
        assert data["detail"]["error"] == "insufficient_role"
        assert data["detail"]["required"] == "admin"
        assert data["detail"]["current"] == "viewer"


@pytest.mark.asyncio
async def test_invite_team_plan_only(client):
    """Test that invite requires teams plan."""
    workspace_id = str(uuid4())
    admin_id = str(uuid4())

    with patch("burnlens_cloud.team_api.execute_query") as mock_query:
        with patch("burnlens_cloud.auth.decode_jwt") as mock_decode:
            # Mock workspace query returning free plan
            mock_query.return_value = [{"plan": "free", "name": "Free Workspace"}]

            token = TokenPayload(
                workspace_id=workspace_id,
                user_id=admin_id,
                role="admin",
                plan="free",
                iat=int(datetime.now().timestamp()),
                exp=int((datetime.now() + timedelta(hours=24)).timestamp()),
            )

            mock_decode.return_value = token

            response = await client.post(
                "/team/invite",
                json={"email": "new@example.com", "role": "viewer"},
                headers={"Authorization": f"Bearer test-token"},
            )

            assert response.status_code == 422
            data = response.json()
            assert data["detail"]["error"] == "plan_does_not_support_teams"


@pytest.mark.asyncio
async def test_seat_limit_enforcement(client):
    """Test that seat limit is enforced."""
    workspace_id = str(uuid4())
    admin_id = str(uuid4())

    with patch("burnlens_cloud.team_api.execute_query") as mock_query:
        with patch("burnlens_cloud.auth.decode_jwt") as mock_decode:
            # Mock workspace query
            mock_query.side_effect = [
                [{"plan": "free", "name": "Free Workspace"}],  # Workspace info
                [{"count": 1}],  # Seat count = seat limit (1 >= 1)
            ]

            token = TokenPayload(
                workspace_id=workspace_id,
                user_id=admin_id,
                role="admin",
                plan="free",
                iat=int(datetime.now().timestamp()),
                exp=int((datetime.now() + timedelta(hours=24)).timestamp()),
            )

            mock_decode.return_value = token

            response = await client.post(
                "/team/invite",
                json={"email": "new@example.com", "role": "viewer"},
                headers={"Authorization": f"Bearer test-token"},
            )

            assert response.status_code == 422
            data = response.json()
            assert data["detail"]["error"] == "seat_limit_reached"


@pytest.mark.asyncio
async def test_list_members(client):
    """Test listing workspace members.

    WR-06: After Phase 1c dropped users.email, list_members selects
    u.email_encrypted and decrypts in Python. This test mocks decrypt_pii
    so we do not need a real encryption key.
    """
    workspace_id = str(uuid4())
    user_id = str(uuid4())

    with patch("burnlens_cloud.team_api.execute_query") as mock_query:
        with patch("burnlens_cloud.team_api.decrypt_pii") as mock_decrypt:
            with patch("burnlens_cloud.auth.decode_jwt") as mock_decode:
                # Mock members query — now returns email_encrypted instead of email
                mock_query.return_value = [
                    {
                        "id": str(uuid4()),
                        "user_id": user_id,
                        "role": "owner",
                        "joined_at": datetime.now(),
                        "last_login": datetime.now(),
                        "invited_by": None,
                        "email_encrypted": "ENC::owner@example.com",
                        "name": "Owner",
                    }
                ]
                mock_decrypt.return_value = "owner@example.com"

                token = TokenPayload(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    role="owner",
                    plan="teams",
                    iat=int(datetime.now().timestamp()),
                    exp=int((datetime.now() + timedelta(hours=24)).timestamp()),
                )

                mock_decode.return_value = token

                response = await client.get(
                    "/team/members",
                    headers={"Authorization": f"Bearer test-token"},
                )

                assert response.status_code == 200
                data = response.json()
                assert len(data) == 1
                assert data[0]["email"] == "owner@example.com"
                assert data[0]["role"] == "owner"
                mock_decrypt.assert_called_once_with("ENC::owner@example.com")


@pytest.mark.asyncio
async def test_remove_member_requires_admin(client):
    """Test that removing members requires admin role."""
    workspace_id = str(uuid4())
    viewer_id = str(uuid4())
    member_id = str(uuid4())

    with patch("burnlens_cloud.auth.decode_jwt") as mock_decode:
        token = TokenPayload(
            workspace_id=workspace_id,
            user_id=viewer_id,
            role="viewer",  # Insufficient permission
            plan="teams",
            iat=int(datetime.now().timestamp()),
            exp=int((datetime.now() + timedelta(hours=24)).timestamp()),
        )

        mock_decode.return_value = token

        response = await client.delete(
            f"/team/members/{member_id}",
            headers={"Authorization": f"Bearer test-token"},
        )

        assert response.status_code == 403


@pytest.mark.asyncio
async def test_dashboard_endpoints_require_viewer_role(client):
    """Test that dashboard GET endpoints require viewer role."""
    workspace_id = str(uuid4())
    user_id = str(uuid4())

    with patch("burnlens_cloud.auth.decode_jwt") as mock_decode:
        # Create token with role missing (simulates old token format)
        token = TokenPayload(
            workspace_id=workspace_id,
            user_id=user_id,
            role="viewer",  # Required for dashboard
            plan="teams",
            iat=int(datetime.now().timestamp()),
            exp=int((datetime.now() + timedelta(hours=24)).timestamp()),
        )

        mock_decode.return_value = token

        with patch("burnlens_cloud.dashboard_api.execute_query") as mock_query:
            mock_query.return_value = [
                {
                    "total_cost": 10.0,
                    "request_count": 100,
                    "avg_cost": 0.1,
                    "model_count": 2,
                }
            ]

            response = await client.get(
                "/api/summary",
                headers={"Authorization": f"Bearer test-token"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["total_cost_usd"] == 10.0
            assert data["total_requests"] == 100


@pytest.mark.asyncio
async def test_invitation_token_generation(client):
    """Test that invitation tokens are generated correctly."""
    workspace_id = str(uuid4())
    admin_id = str(uuid4())

    with patch("burnlens_cloud.team_api.execute_query") as mock_query:
        with patch("burnlens_cloud.team_api.execute_insert") as mock_insert:
            with patch("burnlens_cloud.team_api.send_invitation_email"):
                with patch("burnlens_cloud.auth.decode_jwt") as mock_decode:
                    mock_query.side_effect = [
                        [{"plan": "teams", "name": "Test Workspace"}],
                        [],
                        [{"count": 1}],
                    ]

                    mock_insert.return_value = None

                    token = TokenPayload(
                        workspace_id=workspace_id,
                        user_id=admin_id,
                        role="admin",
                        plan="teams",
                        iat=int(datetime.now().timestamp()),
                        exp=int((datetime.now() + timedelta(hours=24)).timestamp()),
                    )

                    mock_decode.return_value = token

                    response = await client.post(
                        "/team/invite",
                        json={"email": "test@example.com", "role": "admin"},
                        headers={"Authorization": f"Bearer test-token"},
                    )

                    assert response.status_code == 200
                    data = response.json()
                    # Token should be 32-char hex string
                    assert len(data["token"]) == 32
                    assert all(c in "0123456789abcdef" for c in data["token"])
