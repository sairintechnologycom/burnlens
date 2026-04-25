"""Phase 10 Plan 01: /billing/summary extension + /billing/usage/daily.

Covers:
- Pydantic model shapes for the new usage / available_plans / api_keys / daily payloads.
- /billing/summary now carries `usage`, `available_plans`, `api_keys` subobjects.
- New GET /billing/usage/daily endpoint: workspace-scoped daily aggregation
  over `request_records` within the caller's current cycle.
- ?cycle=previous returns the documented HTTP 400 stub.
- Workspace isolation is enforced via verify_token (D-18 / D-20 / D-26 / T-10-01).
- 401 on missing auth.
- Brand-new workspace with no usage cycle row gets request_count=0 + valid bounds.
"""
from __future__ import annotations

import json
import os
import pathlib
import time
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

# Test-safe env. Mirror the pattern used by tests/test_billing_webhook_phase7.py.
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


WS_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
WS_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER_ID = "11111111-1111-1111-1111-111111111111"


def _encode_test_jwt(workspace_id: str = WS_A, plan: str = "cloud") -> str:
    from burnlens_cloud.auth import encode_jwt
    return encode_jwt(workspace_id, USER_ID, "owner", plan)


@pytest.fixture
def app_client():
    """A FastAPI app mounting only the billing router. DB pool is NOT initialized."""
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport

    from burnlens_cloud import config as config_mod
    config_mod.settings.paddle_webhook_secret = "test-webhook-secret"

    from burnlens_cloud.billing import router as billing_router
    app = FastAPI()
    app.include_router(billing_router)

    transport = ASGITransport(app=app)

    async def _client():
        return AsyncClient(transport=transport, base_url="http://testserver")

    return _client


# ---------------------------------------------------------------------------
# Section 1 — Pydantic model shapes (Task 1 RED → GREEN)
# ---------------------------------------------------------------------------


def test_usage_current_cycle_shape():
    from burnlens_cloud.models import UsageCurrentCycle
    obj = UsageCurrentCycle(
        start=datetime(2026, 4, 1, tzinfo=timezone.utc),
        end=datetime(2026, 5, 1, tzinfo=timezone.utc),
        request_count=42,
        monthly_request_cap=1_000_000,
    )
    payload = json.loads(obj.model_dump_json())
    assert payload["request_count"] == 42
    assert payload["monthly_request_cap"] == 1_000_000
    # ISO-8601 timestamps
    assert payload["start"].startswith("2026-04-01")
    assert payload["end"].startswith("2026-05-01")


def test_available_plan_shape():
    from burnlens_cloud.models import AvailablePlan
    obj = AvailablePlan(plan="cloud", price_cents=2900)
    payload = json.loads(obj.model_dump_json())
    assert payload == {"plan": "cloud", "price_cents": 2900, "currency": "USD"}


def test_api_keys_summary_shape():
    from burnlens_cloud.models import ApiKeysSummary
    obj = ApiKeysSummary(active_count=2, limit=3)
    payload = json.loads(obj.model_dump_json())
    assert payload == {"active_count": 2, "limit": 3}

    unlimited = ApiKeysSummary(active_count=4, limit=None)
    payload2 = json.loads(unlimited.model_dump_json())
    assert payload2 == {"active_count": 4, "limit": None}


def test_usage_daily_entry_shape():
    from burnlens_cloud.models import UsageDailyEntry
    obj = UsageDailyEntry(date=date(2026, 4, 12), requests=17)
    payload = json.loads(obj.model_dump_json())
    assert payload == {"date": "2026-04-12", "requests": 17}


def test_usage_daily_response_shape():
    from burnlens_cloud.models import UsageDailyResponse, UsageDailyEntry
    obj = UsageDailyResponse(
        cycle_start=datetime(2026, 4, 1, tzinfo=timezone.utc),
        cycle_end=datetime(2026, 5, 1, tzinfo=timezone.utc),
        cap=1_000_000,
        current=33,
        daily=[
            UsageDailyEntry(date=date(2026, 4, 11), requests=10),
            UsageDailyEntry(date=date(2026, 4, 12), requests=23),
        ],
    )
    payload = json.loads(obj.model_dump_json())
    assert payload["cap"] == 1_000_000
    assert payload["current"] == 33
    assert len(payload["daily"]) == 2
    assert payload["daily"][0] == {"date": "2026-04-11", "requests": 10}


def test_billing_summary_extended_models():
    """BillingSummary must carry the three new optional subobjects without breaking
    the original Phase 7/8 contract."""
    from burnlens_cloud.models import (
        BillingSummary,
        UsageCurrentCycle,
        AvailablePlan,
        ApiKeysSummary,
    )

    # Backward-compat: old shape still serializes (no new fields supplied).
    legacy = BillingSummary(plan="free", status="active")
    legacy_payload = json.loads(legacy.model_dump_json())
    assert legacy_payload["plan"] == "free"
    assert legacy_payload.get("usage") is None
    assert legacy_payload.get("available_plans") == []
    assert legacy_payload.get("api_keys") is None

    # New shape: all three fields populate correctly.
    extended = BillingSummary(
        plan="cloud",
        status="active",
        usage=UsageCurrentCycle(
            start=datetime(2026, 4, 1, tzinfo=timezone.utc),
            end=datetime(2026, 5, 1, tzinfo=timezone.utc),
            request_count=100,
            monthly_request_cap=1_000_000,
        ),
        available_plans=[
            AvailablePlan(plan="cloud", price_cents=2900),
            AvailablePlan(plan="teams", price_cents=9900),
        ],
        api_keys=ApiKeysSummary(active_count=1, limit=3),
    )
    payload = json.loads(extended.model_dump_json())
    assert payload["usage"]["request_count"] == 100
    assert payload["usage"]["monthly_request_cap"] == 1_000_000
    assert payload["available_plans"][0]["price_cents"] == 2900
    assert payload["available_plans"][1]["price_cents"] == 9900
    assert payload["api_keys"] == {"active_count": 1, "limit": 3}


# ---------------------------------------------------------------------------
# Section 2 — /billing/summary extension (Task 2)
# ---------------------------------------------------------------------------


def _summary_workspace_row(plan: str = "cloud"):
    """The workspaces SELECT row used by /billing/summary."""
    return {
        "plan": plan,
        "price_cents": 2900 if plan == "cloud" else (9900 if plan == "teams" else None),
        "currency": "USD" if plan != "free" else None,
        "subscription_status": "active",
        "trial_ends_at": None,
        "current_period_ends_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
        "cancel_at_period_end": False,
    }


def _plan_limits_rows():
    """`SELECT plan, paddle_price_id FROM plan_limits WHERE paddle_price_id IS NOT NULL`."""
    return [
        {"plan": "cloud", "paddle_price_id": "pri_cloud"},
        {"plan": "teams", "paddle_price_id": "pri_teams"},
    ]


def _resolved_limits(plan: str = "cloud", api_key_count=3):
    from burnlens_cloud.models import ResolvedLimits
    return ResolvedLimits(
        plan=plan,
        monthly_request_cap=1_000_000 if plan == "cloud" else 10_000_000,
        seat_count=1 if plan == "cloud" else 10,
        retention_days=30 if plan == "cloud" else 90,
        api_key_count=api_key_count,
        gated_features={},
    )


def _make_summary_query_side_effect(
    *,
    plan: str = "cloud",
    cycle_request_count: int = 0,
    has_cycle_row: bool = True,
    api_keys_active: int = 0,
):
    """Produce an async side-effect for execute_query that handles every SELECT
    fired inside the extended /billing/summary handler.

    Order-agnostic: dispatch on SQL substring so the implementation is free to
    re-order fetches.
    """
    cycle_start = datetime(2026, 4, 19, tzinfo=timezone.utc)
    cycle_end = datetime(2026, 5, 19, tzinfo=timezone.utc)

    async def _side_effect(sql, *args):
        s = " ".join(sql.split())  # collapse whitespace for substring checks
        # 1) Workspaces row for the summary base fields.
        if "FROM workspaces" in s and "WHERE id = $1" in s:
            return [_summary_workspace_row(plan)]
        # 2) Cycle bounds — workspace_usage_cycles read.
        if "FROM workspace_usage_cycles" in s:
            if not has_cycle_row:
                return []
            return [{
                "cycle_start": cycle_start,
                "cycle_end": cycle_end,
                "request_count": cycle_request_count,
            }]
        # 3) Calendar-month fallback (used for free or when no cycle row exists).
        if "date_trunc('month'" in s and "FROM workspace_usage_cycles" not in s:
            return [{
                "cycle_start": datetime(2026, 4, 1, tzinfo=timezone.utc),
                "cycle_end": datetime(2026, 5, 1, tzinfo=timezone.utc),
            }]
        # 4) Available plans.
        if "FROM plan_limits" in s and "paddle_price_id IS NOT NULL" in s:
            return _plan_limits_rows()
        # 5) Active api_keys count.
        if "FROM api_keys" in s and "revoked_at IS NULL" in s:
            return [{"n": api_keys_active}]
        return []

    return AsyncMock(side_effect=_side_effect)


@pytest.mark.asyncio
async def test_summary_includes_usage_current_cycle(app_client):
    token = _encode_test_jwt(WS_A, "cloud")
    mock_query = _make_summary_query_side_effect(
        plan="cloud", cycle_request_count=42, api_keys_active=1
    )
    mock_resolve = AsyncMock(return_value=_resolved_limits("cloud", api_key_count=3))

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.resolve_limits", mock_resolve):
        async with await app_client() as ac:
            resp = await ac.get(
                "/billing/summary",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["usage"] is not None
    assert body["usage"]["request_count"] == 42
    assert body["usage"]["monthly_request_cap"] == 1_000_000
    assert body["usage"]["start"] is not None
    assert body["usage"]["end"] is not None


@pytest.mark.asyncio
async def test_summary_available_plans_excludes_free(app_client):
    token = _encode_test_jwt(WS_A, "cloud")
    mock_query = _make_summary_query_side_effect(plan="cloud", api_keys_active=0)
    mock_resolve = AsyncMock(return_value=_resolved_limits("cloud", api_key_count=3))

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.resolve_limits", mock_resolve):
        async with await app_client() as ac:
            resp = await ac.get(
                "/billing/summary",
                headers={"Authorization": f"Bearer {token}"},
            )

    body = resp.json()
    plans = {p["plan"]: p for p in body["available_plans"]}
    assert set(plans.keys()) == {"cloud", "teams"}
    assert plans["cloud"]["price_cents"] == 2900
    assert plans["teams"]["price_cents"] == 9900
    assert plans["cloud"]["currency"] == "USD"
    assert plans["teams"]["currency"] == "USD"
    assert "free" not in plans


@pytest.mark.asyncio
async def test_summary_api_keys_active_count(app_client):
    token = _encode_test_jwt(WS_A, "cloud")
    mock_query = _make_summary_query_side_effect(plan="cloud", api_keys_active=2)
    mock_resolve = AsyncMock(return_value=_resolved_limits("cloud", api_key_count=3))

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.resolve_limits", mock_resolve):
        async with await app_client() as ac:
            resp = await ac.get(
                "/billing/summary",
                headers={"Authorization": f"Bearer {token}"},
            )

    body = resp.json()
    assert body["api_keys"] == {"active_count": 2, "limit": 3}


@pytest.mark.asyncio
async def test_summary_api_keys_workspace_isolation(app_client):
    """The api_keys count SQL must parameterize on token.workspace_id, never WS_B."""
    token_a = _encode_test_jwt(WS_A, "cloud")

    captured_calls: list[tuple] = []

    async def _capture(sql, *args):
        captured_calls.append((sql, args))
        s = " ".join(sql.split())
        if "FROM workspaces" in s:
            return [_summary_workspace_row("cloud")]
        if "FROM workspace_usage_cycles" in s:
            return [{
                "cycle_start": datetime(2026, 4, 1, tzinfo=timezone.utc),
                "cycle_end": datetime(2026, 5, 1, tzinfo=timezone.utc),
                "request_count": 0,
            }]
        if "date_trunc('month'" in s:
            return [{
                "cycle_start": datetime(2026, 4, 1, tzinfo=timezone.utc),
                "cycle_end": datetime(2026, 5, 1, tzinfo=timezone.utc),
            }]
        if "FROM plan_limits" in s:
            return _plan_limits_rows()
        if "FROM api_keys" in s:
            return [{"n": 1}]
        return []

    mock_query = AsyncMock(side_effect=_capture)
    mock_resolve = AsyncMock(return_value=_resolved_limits("cloud", api_key_count=3))

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.resolve_limits", mock_resolve):
        async with await app_client() as ac:
            resp = await ac.get(
                "/billing/summary",
                headers={"Authorization": f"Bearer {token_a}"},
            )

    assert resp.status_code == 200
    # Find the api_keys count call and verify $1 == WS_A, never WS_B.
    api_keys_calls = [
        c for c in captured_calls if "FROM api_keys" in " ".join(c[0].split())
    ]
    assert len(api_keys_calls) == 1, api_keys_calls
    api_args = api_keys_calls[0][1]
    assert WS_A in api_args
    assert WS_B not in api_args


@pytest.mark.asyncio
async def test_summary_api_keys_unlimited_plan(app_client):
    token = _encode_test_jwt(WS_A, "teams")
    mock_query = _make_summary_query_side_effect(plan="teams", api_keys_active=4)
    # Teams workspace with overridden None cap (treated as unlimited)
    mock_resolve = AsyncMock(return_value=_resolved_limits("teams", api_key_count=None))

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.resolve_limits", mock_resolve):
        async with await app_client() as ac:
            resp = await ac.get(
                "/billing/summary",
                headers={"Authorization": f"Bearer {token}"},
            )

    body = resp.json()
    assert body["api_keys"]["active_count"] == 4
    assert body["api_keys"]["limit"] is None


@pytest.mark.asyncio
async def test_summary_brand_new_workspace_zero_count(app_client):
    """A workspace with no row in workspace_usage_cycles still gets request_count=0
    and valid cycle bounds."""
    token = _encode_test_jwt(WS_A, "cloud")
    mock_query = _make_summary_query_side_effect(
        plan="cloud", has_cycle_row=False, api_keys_active=0
    )
    mock_resolve = AsyncMock(return_value=_resolved_limits("cloud", api_key_count=3))

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.resolve_limits", mock_resolve):
        async with await app_client() as ac:
            resp = await ac.get(
                "/billing/summary",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["usage"]["request_count"] == 0
    assert body["usage"]["start"] is not None
    assert body["usage"]["end"] is not None
    assert body["usage"]["monthly_request_cap"] == 1_000_000


# ---------------------------------------------------------------------------
# Section 3 — /billing/usage/daily endpoint
# ---------------------------------------------------------------------------


def _make_daily_query_side_effect(
    *,
    daily_rows: list[dict] | None = None,
    has_cycle_row: bool = True,
    request_count: int = 50,
):
    """Side-effect for the /usage/daily handler. Resolves cycle + daily aggregation."""
    cycle_start = datetime(2026, 4, 19, tzinfo=timezone.utc)
    cycle_end = datetime(2026, 5, 19, tzinfo=timezone.utc)
    if daily_rows is None:
        daily_rows = [
            {"date": date(2026, 4, 19), "requests": 10},
            {"date": date(2026, 4, 20), "requests": 25},
            {"date": date(2026, 4, 21), "requests": 15},
        ]

    async def _side_effect(sql, *args):
        s = " ".join(sql.split())
        if "FROM workspace_usage_cycles" in s:
            if not has_cycle_row:
                return []
            return [{
                "cycle_start": cycle_start,
                "cycle_end": cycle_end,
                "request_count": request_count,
            }]
        if "date_trunc('month'" in s and "FROM request_records" not in s:
            return [{
                "cycle_start": datetime(2026, 4, 1, tzinfo=timezone.utc),
                "cycle_end": datetime(2026, 5, 1, tzinfo=timezone.utc),
            }]
        if "FROM workspaces" in s:
            return [_summary_workspace_row("cloud")]
        if "FROM request_records" in s:
            return daily_rows
        return []

    return AsyncMock(side_effect=_side_effect)


@pytest.mark.asyncio
async def test_usage_daily_returns_grouped_rows(app_client):
    token = _encode_test_jwt(WS_A, "cloud")
    mock_query = _make_daily_query_side_effect(request_count=50)
    mock_resolve = AsyncMock(return_value=_resolved_limits("cloud", api_key_count=3))

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.resolve_limits", mock_resolve):
        async with await app_client() as ac:
            resp = await ac.get(
                "/billing/usage/daily",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"cycle_start", "cycle_end", "cap", "current", "daily"}
    assert body["cap"] == 1_000_000
    assert body["current"] == 50
    assert len(body["daily"]) == 3
    assert body["daily"][0] == {"date": "2026-04-19", "requests": 10}
    assert body["daily"][1] == {"date": "2026-04-20", "requests": 25}


@pytest.mark.asyncio
async def test_usage_daily_previous_returns_400(app_client):
    token = _encode_test_jwt(WS_A, "cloud")
    # No DB calls should be needed for the previous-cycle stub. Wire a noop just in case.
    mock_query = AsyncMock(return_value=[])
    mock_resolve = AsyncMock(return_value=_resolved_limits("cloud"))

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.resolve_limits", mock_resolve):
        async with await app_client() as ac:
            resp = await ac.get(
                "/billing/usage/daily?cycle=previous",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 400
    body = resp.json()
    # FastAPI wraps the dict under "detail"
    detail = body.get("detail", body)
    assert detail.get("error") == "not_implemented"
    assert detail.get("message") == "Previous cycle drill-down is a v1.2 feature."


@pytest.mark.asyncio
async def test_usage_daily_workspace_isolation(app_client):
    """Critical security invariant (T-10-01): the daily SQL must parameterize on
    token.workspace_id only — never on a query-string-supplied id."""
    token_a = _encode_test_jwt(WS_A, "cloud")

    captured: list[tuple] = []
    cycle_start = datetime(2026, 4, 19, tzinfo=timezone.utc)
    cycle_end = datetime(2026, 5, 19, tzinfo=timezone.utc)

    async def _capture(sql, *args):
        captured.append((sql, args))
        s = " ".join(sql.split())
        if "FROM workspace_usage_cycles" in s:
            return [{
                "cycle_start": cycle_start,
                "cycle_end": cycle_end,
                "request_count": 5,
            }]
        if "FROM request_records" in s:
            return []
        if "FROM workspaces" in s:
            return [_summary_workspace_row("cloud")]
        if "date_trunc('month'" in s and "FROM request_records" not in s:
            return [{"cycle_start": cycle_start, "cycle_end": cycle_end}]
        return []

    mock_query = AsyncMock(side_effect=_capture)
    mock_resolve = AsyncMock(return_value=_resolved_limits("cloud", api_key_count=3))

    with patch("burnlens_cloud.billing.execute_query", mock_query), \
         patch("burnlens_cloud.billing.resolve_limits", mock_resolve):
        async with await app_client() as ac:
            # Even if a hostile caller appends ?workspace_id=WS_B, the handler
            # must not honor it. (FastAPI will simply not bind the unknown param.)
            resp = await ac.get(
                f"/billing/usage/daily?workspace_id={WS_B}",
                headers={"Authorization": f"Bearer {token_a}"},
            )

    assert resp.status_code == 200
    # Find the request_records SQL call and verify $1 == WS_A.
    rr_calls = [c for c in captured if "FROM request_records" in " ".join(c[0].split())]
    assert len(rr_calls) == 1, rr_calls
    args = rr_calls[0][1]
    assert WS_A in args
    assert WS_B not in args


@pytest.mark.asyncio
async def test_usage_daily_unauthenticated_returns_401(app_client):
    async with await app_client() as ac:
        resp = await ac.get("/billing/usage/daily")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_usage_daily_invalid_cycle_returns_400(app_client):
    token = _encode_test_jwt(WS_A, "cloud")
    async with await app_client() as ac:
        resp = await ac.get(
            "/billing/usage/daily?cycle=garbage",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 400
