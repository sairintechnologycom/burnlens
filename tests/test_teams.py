"""Tests for Teams functionality."""

import os
import pathlib

# Test-safe env: prevent the project-root .env (OSS-proxy oriented) from
# being loaded by pydantic-settings during burnlens_cloud import. Mirrors
# tests/test_billing_webhook_phase7.py — required so `Settings()` doesn't
# reject OPENAI_BASE_URL / ANTHROPIC_BASE_URL as extra fields.
os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/burnlens_test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests")
os.environ.setdefault("ENVIRONMENT", "test")

_FAKE_ENV = pathlib.Path(__file__).parent / "_phase7_billing_test.env"
if not _FAKE_ENV.exists():
    _FAKE_ENV.write_text("")
os.environ["BURNLENS_CLOUD_ENV_FILE_OVERRIDE"] = str(_FAKE_ENV)

import pydantic_settings.sources as _ps_sources  # noqa: E402


def _empty_dotenv_values(*args, **kwargs):
    return {}


_ps_sources.dotenv_values = _empty_dotenv_values

import pytest
import pytest_asyncio
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from datetime import datetime, timedelta

from burnlens_cloud.models import TokenPayload


@pytest_asyncio.fixture
async def client():
    """Create test client with mocked database.

    GAP-06 update: switch from the legacy `AsyncClient(app=app, ...)` constructor
    (removed in modern httpx) to `ASGITransport(app=app)` per current httpx
    contract. Required so the two seat-limit/feature-gate assertions can run.
    """
    from httpx import ASGITransport
    from burnlens_cloud.main import get_app

    # Bypass lifespan startup (init_db / scheduler tasks) by patching the
    # database hooks before the app is built.
    with patch("burnlens_cloud.database.init_db", new_callable=AsyncMock):
        with patch("burnlens_cloud.database.close_db", new_callable=AsyncMock):
            app = get_app()
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
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


def _mock_resolve_limits_pool(plan: str, gated_features: dict, seat_count=1, api_key_count=1):
    """Install a mock asyncpg pool on burnlens_cloud.plans so resolve_limits()
    returns synthetic data without hitting Postgres.

    `require_feature` lazy-imports `resolve_limits` and captures it in a closure
    at FastAPI dependency-registration time, so patching the function reference
    is too late. Patching `burnlens_cloud.plans.pool` makes the captured
    function find a working (mocked) pool when it runs.
    """
    mock_conn = MagicMock()
    mock_conn.fetchrow = AsyncMock(return_value={
        "plan": plan,
        "monthly_request_cap": 1000,
        "seat_count": seat_count,
        "retention_days": 7,
        "api_key_count": api_key_count,
        "gated_features": gated_features,
    })
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_pool


@pytest.mark.asyncio
async def test_invite_team_plan_only(client):
    """Phase 9 D-16/D-17: Free-plan invite is now blocked by the
    require_feature("teams_view") FastAPI dependency, returning 402
    feature_not_in_plan instead of the legacy 422 plan_does_not_support_teams.

    GAP-06: updated in-place per gsd-nyquist-auditor request — assertions now
    match the production 402 contract.
    """
    workspace_id = str(uuid4())
    admin_id = str(uuid4())

    mock_pool = _mock_resolve_limits_pool(
        plan="free",
        gated_features={"teams_view": False, "customers_view": False},
    )

    async def _q(sql, *args):
        s = " ".join(sql.split())
        if "FROM plan_limits" in s and "gated_features" in s:
            return [{"plan": "teams", "gated_features": {"teams_view": True}}]
        return [{"plan": "free", "name": "Free Workspace"}]

    with patch("burnlens_cloud.team_api.execute_query", side_effect=_q):
        with patch("burnlens_cloud.auth.execute_query", side_effect=_q):
            with patch("burnlens_cloud.plans.pool", mock_pool):
                with patch("burnlens_cloud.auth.decode_jwt") as mock_decode:
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

                    assert response.status_code == 402, response.text
                    data = response.json()
                    assert data["detail"]["error"] == "feature_not_in_plan"
                    assert data["detail"]["required_feature"] == "teams_view"
                    assert data["detail"]["required_plan"] == "teams"
                    assert "upgrade_url" in data["detail"]


@pytest.mark.asyncio
async def test_seat_limit_enforcement(client):
    """Phase 9 D-14/D-16: seat-limit response converted from 422 to 402 with the
    standardized D-14 body shape: {error, limit, current, required_plan, upgrade_url}.

    GAP-06: updated in-place per gsd-nyquist-auditor request — assertions now
    match the production 402 contract.
    """
    workspace_id = str(uuid4())
    admin_id = str(uuid4())

    # Teams plan: teams_view feature ON (so the feature gate passes through).
    # The seat cap is enforced at the handler level: seat_count=1, current=1.
    mock_pool = _mock_resolve_limits_pool(
        plan="teams",
        gated_features={"teams_view": True, "customers_view": True},
        seat_count=1,
    )

    # team_api.execute_query side_effect order matches the invite_member call
    # sequence post-feature-gate:
    # 1) SELECT plan, name FROM workspaces
    # 2) Existing-member check (returns [])
    # 3) check_seat_limit COUNT (returns 1 → at cap)
    # 4) _current_seat_count COUNT (returns 1)
    # 5) _lowest_plan_with_seat_count plan_limits SELECT ([])
    team_query_responses = [
        [{"plan": "teams", "name": "Teams Workspace"}],
        [],
        [{"count": 1}],
        [{"c": 1}],
        [],
    ]
    team_query_iter = iter(team_query_responses)

    async def _team_q(sql, *args):
        try:
            return next(team_query_iter)
        except StopIteration:
            return []

    async def _auth_q(sql, *args):
        return []

    with patch("burnlens_cloud.team_api.execute_query", side_effect=_team_q):
        with patch("burnlens_cloud.auth.execute_query", side_effect=_auth_q):
            with patch("burnlens_cloud.plans.pool", mock_pool):
                with patch("burnlens_cloud.auth.decode_jwt") as mock_decode:
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

                    assert response.status_code == 402, response.text
                    data = response.json()
                    detail = data["detail"]
                    assert detail["error"] == "seat_limit_reached"
                    assert detail["limit"] == 1
                    assert detail["current"] == 1
                    assert "required_plan" in detail
                    assert "upgrade_url" in detail
                    assert "/settings#billing" in detail["upgrade_url"]


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
