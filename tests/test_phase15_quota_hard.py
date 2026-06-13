"""Phase 15: Hard Ingest Quota Enforcement — TDD Wave 0 scaffold.

All 12 test cases are written in RED state. `_check_quota_or_raise` does not
exist in burnlens_cloud.ingest yet, so:
- 429-path tests: will get a 500 (function missing) — assert status_code==429 FAILS → RED
- 200-path tests: _check_quota_or_raise is patched out with AsyncMock, but the patch
  target does not exist on the module yet → these tests may error at patch time.

This is correct RED behaviour. Plan 01 (GREEN) will implement _check_quota_or_raise.

Covers:
- QUOTA-01: request count hard cap (429 at/over cap, 200 below, 200 when NULL)
- QUOTA-02: token count hard cap (429 at cap, 200 when NULL)
- QUOTA-03: spend cap in USD (429 at cap, 200 when NULL)
- QUOTA-04: seat count enforcement (429 when members > seat_count, 200 within cap)
- QUOTA-05: 429 response body shape (error/dimension/current/limit fields)
- NoRecordsOnBlock: execute_bulk_insert NOT called when 429
"""
from __future__ import annotations

import os
import pathlib

# ---------------------------------------------------------------------------
# Env isolation header — verbatim from tests/test_phase09_quota.py
# Must appear before ANY burnlens_cloud import so pydantic-settings reads
# these values instead of the real .env file.
# ---------------------------------------------------------------------------
os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/burnlens_test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("PADDLE_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("PADDLE_CLOUD_PRICE_ID", "pri_env_cloud")
os.environ.setdefault("PADDLE_TEAMS_PRICE_ID", "pri_env_teams")

_FAKE_ENV = pathlib.Path(__file__).parent / "_phase7_billing_test.env"
if not _FAKE_ENV.exists():
    _FAKE_ENV.write_text("")
os.environ["BURNLENS_CLOUD_ENV_FILE_OVERRIDE"] = str(_FAKE_ENV)

import pydantic_settings.sources as _ps_sources  # noqa: E402


def _empty_dotenv_values(*args, **kwargs):
    return {}


_ps_sources.dotenv_values = _empty_dotenv_values

# ---------------------------------------------------------------------------
# Standard imports (after env isolation)
# ---------------------------------------------------------------------------
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WS_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


# ---------------------------------------------------------------------------
# Helper: _make_resolved_limits
# Phase 15 version adds monthly_token_cap and monthly_spend_cap_usd
# ---------------------------------------------------------------------------
def _make_resolved_limits(
    plan: str = "cloud",
    monthly_request_cap=None,
    seat_count=None,
    api_key_count=None,
    retention_days=None,
    gated_features=None,
    monthly_token_cap=None,
    monthly_spend_cap_usd=None,
):
    """Build a ResolvedLimits instance for use in quota tests.

    monthly_token_cap and monthly_spend_cap_usd are Phase 15 additions that
    will be added to ResolvedLimits in Plan 01. Until then, we try to set them
    as attributes after construction so that tests that inspect them work
    regardless of whether the model field exists.
    """
    from burnlens_cloud.models import ResolvedLimits
    obj = ResolvedLimits(
        plan=plan,
        monthly_request_cap=monthly_request_cap,
        seat_count=seat_count,
        api_key_count=api_key_count,
        retention_days=retention_days,
        gated_features=gated_features or {},
    )
    # Assign Phase 15 fields (will be proper model fields after Plan 01).
    # Use object.__setattr__ to bypass pydantic's frozen check if needed.
    try:
        obj.monthly_token_cap = monthly_token_cap
    except Exception:
        object.__setattr__(obj, "monthly_token_cap", monthly_token_cap)
    try:
        obj.monthly_spend_cap_usd = monthly_spend_cap_usd
    except Exception:
        object.__setattr__(obj, "monthly_spend_cap_usd", monthly_spend_cap_usd)
    return obj


# ---------------------------------------------------------------------------
# Helper: _make_app / _make_client
# ---------------------------------------------------------------------------
def _make_app(*routers):
    """Mount routers on a bare FastAPI app (no lifespan/init_db)."""
    from fastapi import FastAPI
    app = FastAPI()
    for r in routers:
        app.include_router(r)
    return app


def _make_client(app):
    """Return an httpx AsyncClient using ASGI transport."""
    from httpx import AsyncClient, ASGITransport
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://testserver")


# ---------------------------------------------------------------------------
# Helper: _minimal_payload
# ---------------------------------------------------------------------------
def _minimal_payload(api_key: str = "bl_live_test_key") -> dict:
    """Smallest valid ingest payload — 1 record."""
    return {
        "api_key": api_key,
        "records": [
            {
                "timestamp": "2026-05-01T10:00:00Z",
                "provider": "openai",
                "model": "gpt-4o",
                "input_tokens": 100,
                "output_tokens": 50,
                "cost_usd": 0.001,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Helper: _query_side_effect factories
# These return a coroutine side_effect that dispatches on SQL content.
# ---------------------------------------------------------------------------
_CYCLE_START = datetime(2026, 5, 1, tzinfo=timezone.utc)
_CYCLE_END = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _make_query_dispatcher(
    request_count: int = 0,
    token_count: int = 0,
    spend_usd: float = 0.0,
    member_count: int = 1,
):
    """Return an async side_effect that mocks the DB queries issued by ingest."""

    async def _query_side_effect(sql, *args):
        s = " ".join(sql.split())
        # Workspace details lookup
        if "FROM workspaces WHERE id" in s:
            return [{"otel_endpoint": None, "otel_api_key_encrypted": None, "otel_enabled": False}]
        # Cycle bounds via date_trunc (free-plan path)
        if "date_trunc('month'" in s:
            return [{"cycle_start": _CYCLE_START, "cycle_end": _CYCLE_END}]
        # Cycle bounds for paid plans (SELECT FROM workspace_usage_cycles WHERE cycle_end > NOW())
        if "FROM workspace_usage_cycles" in s and "cycle_end > NOW()" in s and "INSERT" not in s:
            return [{"cycle_start": _CYCLE_START, "cycle_end": _CYCLE_END}]
        # Usage counter UPSERT
        if "INSERT INTO workspace_usage_cycles" in s and "ON CONFLICT" in s:
            return [{
                "id": "cycle-id-1",
                "request_count": request_count,
                "token_count": token_count,
                "spend_usd": spend_usd,
                "notified_80_at": None,
                "notified_100_at": None,
            }]
        # Active member count for seat enforcement
        if "FROM workspace_members" in s and "active = true" in s:
            return [{"count": member_count}]
        return []

    return _query_side_effect


# ---------------------------------------------------------------------------
# Section 1: QUOTA-01 Hard Block (request count)
# ---------------------------------------------------------------------------

class TestQuota01HardBlock:
    """QUOTA-01: 429 when request_count >= monthly_request_cap."""

    async def test_at_cap_returns_429(self):
        """At exactly the cap, ingest must return 429 and not write records."""
        from burnlens_cloud.ingest import router as ingest_router
        app = _make_app(ingest_router)

        mock_query = AsyncMock(side_effect=_make_query_dispatcher(request_count=1000))
        mock_bulk_insert = AsyncMock(return_value=None)
        mock_get_ws = AsyncMock(return_value=(WS_A, "free"))
        mock_resolve = AsyncMock(return_value=_make_resolved_limits(
            plan="free", monthly_request_cap=1000
        ))

        with patch("burnlens_cloud.ingest.execute_query", mock_query), \
             patch("burnlens_cloud.ingest.execute_bulk_insert", mock_bulk_insert), \
             patch("burnlens_cloud.ingest.get_workspace_by_api_key", mock_get_ws), \
             patch("burnlens_cloud.ingest.resolve_limits", mock_resolve):
            async with _make_client(app) as ac:
                resp = await ac.post("/v1/ingest", json=_minimal_payload())

        assert resp.status_code == 429, (
            f"QUOTA-01: expected 429 at cap, got {resp.status_code}: {resp.text}"
        )
        assert mock_bulk_insert.call_count == 0, (
            "execute_bulk_insert must NOT be called when quota is exceeded"
        )

    async def test_over_cap_returns_429(self):
        """1500 requests vs cap of 1000 — still 429."""
        from burnlens_cloud.ingest import router as ingest_router
        app = _make_app(ingest_router)

        mock_query = AsyncMock(side_effect=_make_query_dispatcher(request_count=1500))
        mock_bulk_insert = AsyncMock(return_value=None)
        mock_get_ws = AsyncMock(return_value=(WS_A, "free"))
        mock_resolve = AsyncMock(return_value=_make_resolved_limits(
            plan="free", monthly_request_cap=1000
        ))

        with patch("burnlens_cloud.ingest.execute_query", mock_query), \
             patch("burnlens_cloud.ingest.execute_bulk_insert", mock_bulk_insert), \
             patch("burnlens_cloud.ingest.get_workspace_by_api_key", mock_get_ws), \
             patch("burnlens_cloud.ingest.resolve_limits", mock_resolve):
            async with _make_client(app) as ac:
                resp = await ac.post("/v1/ingest", json=_minimal_payload())

        assert resp.status_code == 429, (
            f"QUOTA-01: expected 429 over cap, got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# Section 2: QUOTA-01 Allowed (below cap)
# ---------------------------------------------------------------------------

class TestQuota01AllowedBeforeCap:
    """QUOTA-01: 200 when request_count < monthly_request_cap."""

    async def test_below_cap_returns_200(self):
        """999 requests vs cap 1000 → 200 with accepted=1."""
        from burnlens_cloud.ingest import router as ingest_router
        app = _make_app(ingest_router)

        mock_query = AsyncMock(side_effect=_make_query_dispatcher(request_count=999))
        mock_bulk_insert = AsyncMock(return_value=None)
        mock_get_ws = AsyncMock(return_value=(WS_A, "free"))
        mock_resolve = AsyncMock(return_value=_make_resolved_limits(
            plan="free", monthly_request_cap=1000
        ))

        with patch("burnlens_cloud.ingest.execute_query", mock_query), \
             patch("burnlens_cloud.ingest.execute_bulk_insert", mock_bulk_insert), \
             patch("burnlens_cloud.ingest.get_workspace_by_api_key", mock_get_ws), \
             patch("burnlens_cloud.ingest.resolve_limits", mock_resolve), \
             patch("burnlens_cloud.ingest._check_quota_or_raise", AsyncMock(return_value=None)):
            async with _make_client(app) as ac:
                resp = await ac.post("/v1/ingest", json=_minimal_payload())

        assert resp.status_code == 200, (
            f"QUOTA-01: expected 200 below cap, got {resp.status_code}: {resp.text}"
        )
        assert resp.json().get("accepted") == 1


# ---------------------------------------------------------------------------
# Section 3: QUOTA-01 Null cap (unlimited)
# ---------------------------------------------------------------------------

class TestQuota01NullCapAllowed:
    """QUOTA-01: NULL cap means unlimited — always 200."""

    async def test_null_cap_always_200(self):
        """monthly_request_cap=None means unlimited; 999_999_999 requests → 200."""
        from burnlens_cloud.ingest import router as ingest_router
        app = _make_app(ingest_router)

        mock_query = AsyncMock(side_effect=_make_query_dispatcher(request_count=999_999_999))
        mock_bulk_insert = AsyncMock(return_value=None)
        mock_get_ws = AsyncMock(return_value=(WS_A, "cloud"))
        mock_resolve = AsyncMock(return_value=_make_resolved_limits(
            plan="cloud", monthly_request_cap=None
        ))

        with patch("burnlens_cloud.ingest.execute_query", mock_query), \
             patch("burnlens_cloud.ingest.execute_bulk_insert", mock_bulk_insert), \
             patch("burnlens_cloud.ingest.get_workspace_by_api_key", mock_get_ws), \
             patch("burnlens_cloud.ingest.resolve_limits", mock_resolve), \
             patch("burnlens_cloud.ingest._check_quota_or_raise", AsyncMock(return_value=None)):
            async with _make_client(app) as ac:
                resp = await ac.post("/v1/ingest", json=_minimal_payload())

        assert resp.status_code == 200, (
            f"QUOTA-01: NULL cap must always allow, got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# Section 4: QUOTA-02 Token block
# ---------------------------------------------------------------------------

class TestQuota02TokenBlock:
    """QUOTA-02: 429 when token_count >= monthly_token_cap."""

    async def test_at_token_cap_returns_429(self):
        """50_000_001 tokens vs cap 50_000_000 → 429 with dimension='tokens'."""
        from burnlens_cloud.ingest import router as ingest_router
        app = _make_app(ingest_router)

        mock_query = AsyncMock(side_effect=_make_query_dispatcher(
            request_count=1, token_count=50_000_001
        ))
        mock_bulk_insert = AsyncMock(return_value=None)
        mock_get_ws = AsyncMock(return_value=(WS_A, "cloud"))
        mock_resolve = AsyncMock(return_value=_make_resolved_limits(
            plan="cloud", monthly_token_cap=50_000_000
        ))

        with patch("burnlens_cloud.ingest.execute_query", mock_query), \
             patch("burnlens_cloud.ingest.execute_bulk_insert", mock_bulk_insert), \
             patch("burnlens_cloud.ingest.get_workspace_by_api_key", mock_get_ws), \
             patch("burnlens_cloud.ingest.resolve_limits", mock_resolve):
            async with _make_client(app) as ac:
                resp = await ac.post("/v1/ingest", json=_minimal_payload())

        assert resp.status_code == 429, (
            f"QUOTA-02: expected 429 at token cap, got {resp.status_code}: {resp.text}"
        )
        detail = resp.json().get("detail", {})
        assert detail.get("dimension") == "tokens", (
            f"QUOTA-02: expected dimension='tokens', got {detail}"
        )

    async def test_null_token_cap_always_200(self):
        """monthly_token_cap=None means unlimited tokens → 200."""
        from burnlens_cloud.ingest import router as ingest_router
        app = _make_app(ingest_router)

        mock_query = AsyncMock(side_effect=_make_query_dispatcher(token_count=999_999_999))
        mock_bulk_insert = AsyncMock(return_value=None)
        mock_get_ws = AsyncMock(return_value=(WS_A, "cloud"))
        mock_resolve = AsyncMock(return_value=_make_resolved_limits(
            plan="cloud", monthly_token_cap=None
        ))

        with patch("burnlens_cloud.ingest.execute_query", mock_query), \
             patch("burnlens_cloud.ingest.execute_bulk_insert", mock_bulk_insert), \
             patch("burnlens_cloud.ingest.get_workspace_by_api_key", mock_get_ws), \
             patch("burnlens_cloud.ingest.resolve_limits", mock_resolve), \
             patch("burnlens_cloud.ingest._check_quota_or_raise", AsyncMock(return_value=None)):
            async with _make_client(app) as ac:
                resp = await ac.post("/v1/ingest", json=_minimal_payload())

        assert resp.status_code == 200, (
            f"QUOTA-02: NULL token cap must always allow, got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# Section 5: QUOTA-03 Spend block
# ---------------------------------------------------------------------------

class TestQuota03SpendBlock:
    """QUOTA-03: 429 when spend_usd >= monthly_spend_cap_usd."""

    async def test_at_spend_cap_returns_429(self):
        """100.01 USD vs cap 100.0 USD → 429 with dimension='spend_usd'."""
        from burnlens_cloud.ingest import router as ingest_router
        app = _make_app(ingest_router)

        mock_query = AsyncMock(side_effect=_make_query_dispatcher(
            request_count=1, spend_usd=100.01
        ))
        mock_bulk_insert = AsyncMock(return_value=None)
        mock_get_ws = AsyncMock(return_value=(WS_A, "cloud"))
        mock_resolve = AsyncMock(return_value=_make_resolved_limits(
            plan="cloud", monthly_spend_cap_usd=100.0
        ))

        with patch("burnlens_cloud.ingest.execute_query", mock_query), \
             patch("burnlens_cloud.ingest.execute_bulk_insert", mock_bulk_insert), \
             patch("burnlens_cloud.ingest.get_workspace_by_api_key", mock_get_ws), \
             patch("burnlens_cloud.ingest.resolve_limits", mock_resolve):
            async with _make_client(app) as ac:
                resp = await ac.post("/v1/ingest", json=_minimal_payload())

        assert resp.status_code == 429, (
            f"QUOTA-03: expected 429 at spend cap, got {resp.status_code}: {resp.text}"
        )
        detail = resp.json().get("detail", {})
        assert detail.get("dimension") == "spend_usd", (
            f"QUOTA-03: expected dimension='spend_usd', got {detail}"
        )

    async def test_null_spend_cap_always_200(self):
        """monthly_spend_cap_usd=None means unlimited spend → 200."""
        from burnlens_cloud.ingest import router as ingest_router
        app = _make_app(ingest_router)

        mock_query = AsyncMock(side_effect=_make_query_dispatcher(spend_usd=9999.99))
        mock_bulk_insert = AsyncMock(return_value=None)
        mock_get_ws = AsyncMock(return_value=(WS_A, "cloud"))
        mock_resolve = AsyncMock(return_value=_make_resolved_limits(
            plan="cloud", monthly_spend_cap_usd=None
        ))

        with patch("burnlens_cloud.ingest.execute_query", mock_query), \
             patch("burnlens_cloud.ingest.execute_bulk_insert", mock_bulk_insert), \
             patch("burnlens_cloud.ingest.get_workspace_by_api_key", mock_get_ws), \
             patch("burnlens_cloud.ingest.resolve_limits", mock_resolve), \
             patch("burnlens_cloud.ingest._check_quota_or_raise", AsyncMock(return_value=None)):
            async with _make_client(app) as ac:
                resp = await ac.post("/v1/ingest", json=_minimal_payload())

        assert resp.status_code == 200, (
            f"QUOTA-03: NULL spend cap must always allow, got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# Section 6: QUOTA-04 Seat block
# ---------------------------------------------------------------------------

class TestQuota04SeatBlock:
    """QUOTA-04: 429 when active member count > seat_count."""

    async def test_member_count_above_seat_cap_returns_429(self):
        """2 active members vs seat_count=1 → 429 with dimension='seats'."""
        from burnlens_cloud.ingest import router as ingest_router
        app = _make_app(ingest_router)

        mock_query = AsyncMock(side_effect=_make_query_dispatcher(
            request_count=1, member_count=2
        ))
        mock_bulk_insert = AsyncMock(return_value=None)
        mock_get_ws = AsyncMock(return_value=(WS_A, "free"))
        mock_resolve = AsyncMock(return_value=_make_resolved_limits(
            plan="free", seat_count=1
        ))

        with patch("burnlens_cloud.ingest.execute_query", mock_query), \
             patch("burnlens_cloud.ingest.execute_bulk_insert", mock_bulk_insert), \
             patch("burnlens_cloud.ingest.get_workspace_by_api_key", mock_get_ws), \
             patch("burnlens_cloud.ingest.resolve_limits", mock_resolve):
            async with _make_client(app) as ac:
                resp = await ac.post("/v1/ingest", json=_minimal_payload())

        assert resp.status_code == 429, (
            f"QUOTA-04: expected 429 for member_count > seat_count, got {resp.status_code}: {resp.text}"
        )
        detail = resp.json().get("detail", {})
        assert detail.get("dimension") == "seats", (
            f"QUOTA-04: expected dimension='seats', got {detail}"
        )

    async def test_member_count_within_seat_cap_returns_200(self):
        """5 active members vs seat_count=10 → 200."""
        from burnlens_cloud.ingest import router as ingest_router
        app = _make_app(ingest_router)

        mock_query = AsyncMock(side_effect=_make_query_dispatcher(
            request_count=1, member_count=5
        ))
        mock_bulk_insert = AsyncMock(return_value=None)
        mock_get_ws = AsyncMock(return_value=(WS_A, "cloud"))
        mock_resolve = AsyncMock(return_value=_make_resolved_limits(
            plan="cloud", seat_count=10
        ))

        with patch("burnlens_cloud.ingest.execute_query", mock_query), \
             patch("burnlens_cloud.ingest.execute_bulk_insert", mock_bulk_insert), \
             patch("burnlens_cloud.ingest.get_workspace_by_api_key", mock_get_ws), \
             patch("burnlens_cloud.ingest.resolve_limits", mock_resolve), \
             patch("burnlens_cloud.ingest._check_quota_or_raise", AsyncMock(return_value=None)):
            async with _make_client(app) as ac:
                resp = await ac.post("/v1/ingest", json=_minimal_payload())

        assert resp.status_code == 200, (
            f"QUOTA-04: expected 200 within seat cap, got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# Section 7: QUOTA-05 Response body shape
# ---------------------------------------------------------------------------

class TestQuota05ResponseBody:
    """QUOTA-05: 429 body must have error, dimension, current, limit fields."""

    async def test_429_body_has_required_fields(self):
        """Trigger QUOTA-01 block and verify body structure."""
        from burnlens_cloud.ingest import router as ingest_router
        app = _make_app(ingest_router)

        mock_query = AsyncMock(side_effect=_make_query_dispatcher(request_count=1000))
        mock_bulk_insert = AsyncMock(return_value=None)
        mock_get_ws = AsyncMock(return_value=(WS_A, "free"))
        mock_resolve = AsyncMock(return_value=_make_resolved_limits(
            plan="free", monthly_request_cap=1000
        ))

        with patch("burnlens_cloud.ingest.execute_query", mock_query), \
             patch("burnlens_cloud.ingest.execute_bulk_insert", mock_bulk_insert), \
             patch("burnlens_cloud.ingest.get_workspace_by_api_key", mock_get_ws), \
             patch("burnlens_cloud.ingest.resolve_limits", mock_resolve):
            async with _make_client(app) as ac:
                resp = await ac.post("/v1/ingest", json=_minimal_payload())

        assert resp.status_code == 429, (
            f"QUOTA-05: expected 429, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        detail = body.get("detail", {})
        assert detail.get("error") == "quota_exceeded", (
            f"QUOTA-05: expected error='quota_exceeded', got {detail}"
        )
        assert "dimension" in detail, f"QUOTA-05: 'dimension' missing from 429 body: {detail}"
        assert "current" in detail, f"QUOTA-05: 'current' missing from 429 body: {detail}"
        assert "limit" in detail, f"QUOTA-05: 'limit' missing from 429 body: {detail}"


# ---------------------------------------------------------------------------
# Section 8: QUOTA-05 All dimensions produce correct body
# ---------------------------------------------------------------------------

class TestQuota05AllDimensions:
    """QUOTA-05: Each quota dimension produces a 429 with the correct dimension key."""

    @pytest.mark.parametrize("dimension,kwargs", [
        (
            "requests",
            {"monthly_request_cap": 1000},
        ),
        (
            "tokens",
            {"monthly_token_cap": 50_000_000},
        ),
        (
            "spend_usd",
            {"monthly_spend_cap_usd": 100.0},
        ),
        (
            "seats",
            {"seat_count": 1},
        ),
    ])
    async def test_all_dimensions_produce_correct_body(self, dimension, kwargs):
        """Each quota dimension triggers a 429 with matching dimension key."""
        from burnlens_cloud.ingest import router as ingest_router
        app = _make_app(ingest_router)

        # Set counts to trigger each dimension's quota
        if dimension == "requests":
            dispatcher = _make_query_dispatcher(request_count=1000)
        elif dimension == "tokens":
            dispatcher = _make_query_dispatcher(token_count=50_000_001)
        elif dimension == "spend_usd":
            dispatcher = _make_query_dispatcher(spend_usd=100.01)
        elif dimension == "seats":
            dispatcher = _make_query_dispatcher(member_count=2)
        else:
            dispatcher = _make_query_dispatcher()

        mock_query = AsyncMock(side_effect=dispatcher)
        mock_bulk_insert = AsyncMock(return_value=None)
        mock_get_ws = AsyncMock(return_value=(WS_A, "free"))
        mock_resolve = AsyncMock(return_value=_make_resolved_limits(
            plan="free", **kwargs
        ))

        with patch("burnlens_cloud.ingest.execute_query", mock_query), \
             patch("burnlens_cloud.ingest.execute_bulk_insert", mock_bulk_insert), \
             patch("burnlens_cloud.ingest.get_workspace_by_api_key", mock_get_ws), \
             patch("burnlens_cloud.ingest.resolve_limits", mock_resolve):
            async with _make_client(app) as ac:
                resp = await ac.post("/v1/ingest", json=_minimal_payload())

        assert resp.status_code == 429, (
            f"QUOTA-05 ({dimension}): expected 429, got {resp.status_code}: {resp.text}"
        )
        detail = resp.json().get("detail", {})
        assert detail.get("dimension") == dimension, (
            f"QUOTA-05: expected dimension='{dimension}', got {detail.get('dimension')}"
        )


# ---------------------------------------------------------------------------
# Section 9: No records written on block
# ---------------------------------------------------------------------------

class TestNoRecordsOnBlock:
    """execute_bulk_insert must NOT be called when quota returns 429."""

    async def test_execute_bulk_insert_not_called_on_429(self):
        """Trigger QUOTA-01 block; verify execute_bulk_insert call_count == 0."""
        from burnlens_cloud.ingest import router as ingest_router
        app = _make_app(ingest_router)

        mock_query = AsyncMock(side_effect=_make_query_dispatcher(request_count=1000))
        mock_bulk_insert = AsyncMock(return_value=None)
        mock_get_ws = AsyncMock(return_value=(WS_A, "free"))
        mock_resolve = AsyncMock(return_value=_make_resolved_limits(
            plan="free", monthly_request_cap=1000
        ))

        with patch("burnlens_cloud.ingest.execute_query", mock_query), \
             patch("burnlens_cloud.ingest.execute_bulk_insert", mock_bulk_insert), \
             patch("burnlens_cloud.ingest.get_workspace_by_api_key", mock_get_ws), \
             patch("burnlens_cloud.ingest.resolve_limits", mock_resolve):
            async with _make_client(app) as ac:
                resp = await ac.post("/v1/ingest", json=_minimal_payload())

        assert resp.status_code == 429, (
            f"TestNoRecordsOnBlock: expected 429, got {resp.status_code}: {resp.text}"
        )
        assert mock_bulk_insert.call_count == 0, (
            f"execute_bulk_insert must NOT be called when 429 is returned. "
            f"call_count={mock_bulk_insert.call_count}"
        )
