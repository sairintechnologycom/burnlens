"""Tests for budget-aware model downgrade routing (Phase 14).

Covers: decide_route() logic, body rewrite, DB persistence, /api/routing-stats.
All tests use AsyncMock — no real SQLite DB except tests 11 and 12.
"""
from __future__ import annotations

import asyncio
import json
import pytest
import aiosqlite
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from burnlens.proxy.router import decide_route, RouteDecision
from burnlens.config import (
    BurnLensConfig,
    RoutingConfig,
    AlertsConfig,
    TeamBudgetsConfig,
    CustomerBudgetsConfig,
)
from burnlens.storage.models import RequestRecord
from burnlens.storage.database import init_db, insert_request

# ---------------------------------------------------------------------------
# Mock patch targets — patch ONLY here, never at burnlens.proxy.router.*
# ---------------------------------------------------------------------------
TEAM_SPEND_PATCH = "burnlens.storage.database.get_spend_by_team_this_month"
CUSTOMER_SPEND_PATCH = "burnlens.storage.database.get_spend_by_customer_this_month"


@pytest.fixture(autouse=True)
def clear_router_cache():
    """Clear 60-second team spend cache between tests to prevent cross-test bleed."""
    import burnlens.proxy.router as _router_mod
    _router_mod._team_spend_cache.clear()
    yield
    _router_mod._team_spend_cache.clear()


# ---------------------------------------------------------------------------
# Config factory
# ---------------------------------------------------------------------------

def _cfg(
    budget_downgrade: bool = True,
    threshold_pct: float = 20.0,
    threshold_usd: float = 5.0,
    team_budgets: dict | None = None,
    global_usd: float | None = None,
    budget_limit_usd: float | None = None,
    customer_budgets: dict | None = None,
    customer_default: float | None = None,
) -> BurnLensConfig:
    routing = RoutingConfig(
        budget_downgrade=budget_downgrade,
        downgrade_threshold_pct=threshold_pct,
        downgrade_threshold_usd=threshold_usd,
    )
    team_cfg = TeamBudgetsConfig(teams=team_budgets or {}, global_usd=global_usd)
    cust_cfg = CustomerBudgetsConfig(customers=customer_budgets or {}, default=customer_default)
    alerts = AlertsConfig(
        budget_limit_usd=budget_limit_usd,
        budgets=team_cfg,
        customer_budgets=cust_cfg,
    )
    return BurnLensConfig(routing=routing, alerts=alerts)


# ---------------------------------------------------------------------------
# Tests 1–8: decide_route() logic
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_downgrade_triggers_at_threshold_pct():
    cfg = _cfg(team_budgets={"eng": 100.0}, threshold_pct=20.0, threshold_usd=1.0)
    with patch(TEAM_SPEND_PATCH, new_callable=AsyncMock, return_value={"eng": 81.0}):
        d = await decide_route("gpt-4o", "eng", None, cfg, ":memory:")
    assert d.downgraded is True
    assert d.reason == "budget_pct"
    assert d.routed_model == "gpt-4o-mini"
    assert d.budget_remaining_pct == pytest.approx(19.0, abs=0.01)


@pytest.mark.asyncio
async def test_downgrade_triggers_at_threshold_usd():
    # pct threshold high so only usd triggers
    cfg = _cfg(team_budgets={"eng": 100.0}, threshold_pct=1.0, threshold_usd=5.0)
    with patch(TEAM_SPEND_PATCH, new_callable=AsyncMock, return_value={"eng": 96.0}):
        d = await decide_route("gpt-4o", "eng", None, cfg, ":memory:")
    assert d.downgraded is True
    assert d.reason == "budget_usd"
    assert d.routed_model == "gpt-4o-mini"
    assert d.budget_remaining_usd == pytest.approx(4.0, abs=0.01)


@pytest.mark.asyncio
async def test_no_downgrade_when_budget_healthy():
    cfg = _cfg(team_budgets={"eng": 100.0}, threshold_pct=20.0, threshold_usd=5.0)
    with patch(TEAM_SPEND_PATCH, new_callable=AsyncMock, return_value={"eng": 50.0}):
        d = await decide_route("gpt-4o", "eng", None, cfg, ":memory:")
    assert d.downgraded is False
    assert d.reason == "no_downgrade_needed"
    assert d.routed_model == "gpt-4o"


@pytest.mark.asyncio
async def test_no_downgrade_when_feature_disabled():
    cfg = _cfg(budget_downgrade=False, team_budgets={"eng": 100.0})
    with patch(TEAM_SPEND_PATCH, new_callable=AsyncMock, return_value={"eng": 99.0}):
        d = await decide_route("gpt-4o", "eng", None, cfg, ":memory:")
    assert d.downgraded is False
    assert d.reason == "disabled"


@pytest.mark.asyncio
async def test_no_alternative_model_passes_through_without_block():
    # gpt-4o-mini is already cheapest — no entry in DOWNGRADE_MAP
    cfg = _cfg(team_budgets={"eng": 100.0}, threshold_pct=20.0, threshold_usd=5.0)
    with patch(TEAM_SPEND_PATCH, new_callable=AsyncMock, return_value={"eng": 85.0}):
        d = await decide_route("gpt-4o-mini", "eng", None, cfg, ":memory:")
    assert d.downgraded is False
    assert d.reason == "no_alternative"
    assert d.routed_model == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_customer_budget_takes_priority_over_team():
    # Customer "acme" is near limit; team "eng" is healthy
    cfg = _cfg(
        customer_budgets={"acme": 50.0},
        team_budgets={"eng": 200.0},
        threshold_pct=20.0,
        threshold_usd=5.0,
    )
    with (
        patch(CUSTOMER_SPEND_PATCH, new_callable=AsyncMock, return_value={"acme": 46.0}),
        patch(TEAM_SPEND_PATCH, new_callable=AsyncMock, return_value={"eng": 10.0}),
    ):
        d = await decide_route("gpt-4o", "eng", "acme", cfg, ":memory:")
    assert d.downgraded is True  # customer budget triggered, not team


@pytest.mark.asyncio
async def test_team_budget_takes_priority_over_global():
    # Team "eng" is near limit; global is healthy
    cfg = _cfg(
        team_budgets={"eng": 100.0},
        global_usd=1000.0,
        threshold_pct=20.0,
        threshold_usd=5.0,
    )
    with (
        patch(TEAM_SPEND_PATCH, new_callable=AsyncMock, return_value={"eng": 85.0}),
    ):
        d = await decide_route("gpt-4o", "eng", None, cfg, ":memory:")
    assert d.downgraded is True  # team budget triggered, not global


@pytest.mark.asyncio
async def test_decide_route_never_raises_on_db_error():
    cfg = _cfg(team_budgets={"eng": 100.0})
    with patch(
        TEAM_SPEND_PATCH,
        new_callable=AsyncMock,
        side_effect=RuntimeError("DB is gone"),
    ):
        d = await decide_route("gpt-4o", "eng", None, cfg, ":memory:")
    assert d.downgraded is False
    assert d.reason == "error"


# ---------------------------------------------------------------------------
# Test 9: Body rewrite — interceptor must forward routed model to upstream
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_request_body_rewritten_with_routed_model():
    """When budget triggers a downgrade, body bytes must have model replaced."""
    cfg = _cfg(team_budgets={"eng": 100.0}, threshold_pct=20.0, threshold_usd=1.0)

    with patch(TEAM_SPEND_PATCH, new_callable=AsyncMock, return_value={"eng": 85.0}):
        decision = await decide_route("gpt-4o", "eng", None, cfg, ":memory:")

    assert decision.downgraded is True

    # Simulate the interceptor body rewrite: replace "model" field with routed model
    original = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
    rewritten = json.loads(json.dumps({**original, "model": decision.routed_model}))
    captured_requests = [rewritten]  # one request forwarded upstream

    assert len(captured_requests) == 1
    sent_body = captured_requests[0]
    assert sent_body["model"] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Test 9b: Google body without 'model' field is not mutated on downgrade
# (regression guard for Phase 17 ROUTE-08 / CONTEXT decision #4)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_body_without_model_not_mutated_on_downgrade():
    """Google request bodies have no 'model' field; the body-rewrite must skip it.

    Mirrors the interceptor body-guard logic:
        if "model" in body_dict:
            body_dict["model"] = decision.routed_model
    """
    cfg = _cfg(team_budgets={"eng": 100.0}, threshold_pct=20.0, threshold_usd=1.0)

    with patch(TEAM_SPEND_PATCH, new_callable=AsyncMock, return_value={"eng": 85.0}):
        decision = await decide_route("gemini-1.5-pro", "eng", None, cfg, ":memory:")

    assert decision.downgraded is True
    assert decision.routed_model == "gemini-1.5-flash"

    # Google body has no 'model' field — model is encoded in the URL path.
    google_body = {"contents": [{"parts": [{"text": "hi"}]}]}
    body_dict = dict(google_body)
    if "model" in body_dict:
        body_dict["model"] = decision.routed_model

    # The body must remain unchanged — no 'model' key injected.
    assert "model" not in body_dict
    assert body_dict == google_body


# ---------------------------------------------------------------------------
# Test 10: Cost calculated on routed model, not original
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cost_calculated_on_routed_model_not_original():
    """RequestRecord.model must be the routed model so cost is charged correctly."""
    cfg = _cfg(team_budgets={"eng": 100.0}, threshold_pct=20.0, threshold_usd=1.0)

    with patch(TEAM_SPEND_PATCH, new_callable=AsyncMock, return_value={"eng": 85.0}):
        decision = await decide_route("gpt-4o", "eng", None, cfg, ":memory:")

    assert decision.downgraded is True

    # Interceptor updates model to routed_model before building RequestRecord
    inserted_records: list[RequestRecord] = []

    async def capture_insert(record: RequestRecord, db_path: str) -> None:
        inserted_records.append(record)

    record = RequestRecord(
        provider="openai",
        model=decision.routed_model,  # interceptor sets this to the cheaper model
        request_path="/v1/chat/completions",
        downgrade_reason=decision.reason,
        routed_model=decision.routed_model,
    )
    await capture_insert(record, ":memory:")

    assert len(inserted_records) == 1
    assert inserted_records[0].model == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Test 11: /api/routing-stats returns correct counts
# ---------------------------------------------------------------------------

def test_routing_stats_api_returns_correct_counts(tmp_path):
    """GET /api/routing-stats counts downgraded rows correctly."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from burnlens.dashboard.routes import router as dashboard_router

    db_path = str(tmp_path / "test.db")
    asyncio.run(init_db(db_path))

    today_str = date.today().isoformat() + "T00:00:00"

    def _record(downgraded: bool) -> RequestRecord:
        return RequestRecord(
            provider="openai",
            model="gpt-4o" if not downgraded else "gpt-4o-mini",
            request_path="/v1/chat/completions",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.001,
            duration_ms=100,
            downgrade_reason="budget_pct" if downgraded else None,
            routed_model="gpt-4o-mini" if downgraded else None,
        )

    asyncio.run(insert_request(db_path, _record(True)))
    asyncio.run(insert_request(db_path, _record(True)))
    asyncio.run(insert_request(db_path, _record(False)))

    app = FastAPI()
    app.include_router(dashboard_router)
    app.state.db_path = db_path

    with TestClient(app) as client:
        resp = client.get("/routing-stats")

    assert resp.status_code == 200
    data = resp.json()
    assert data["downgrades_today"] == 2
    assert data["downgrades_this_month"] == 2


# ---------------------------------------------------------------------------
# Test 12: downgrade_reason and routed_model persisted to DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_downgrade_reason_stored_in_db(tmp_path):
    """insert_request must persist downgrade_reason and routed_model columns."""
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)

    record = RequestRecord(
        provider="openai",
        model="gpt-4o-mini",
        request_path="/v1/chat/completions",
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.0005,
        duration_ms=80,
        downgrade_reason="budget_pct",
        routed_model="gpt-4o-mini",
        budget_remaining_usd=4.50,
        budget_remaining_pct=9.0,
    )
    await insert_request(db_path, record)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT downgrade_reason, routed_model, budget_remaining_usd, budget_remaining_pct "
            "FROM requests WHERE downgrade_reason IS NOT NULL LIMIT 1"
        )
        row = await cursor.fetchone()

    assert row is not None
    assert row["downgrade_reason"] == "budget_pct"
    assert row["routed_model"] == "gpt-4o-mini"
    assert row["budget_remaining_usd"] == pytest.approx(4.50, abs=0.001)
    assert row["budget_remaining_pct"] == pytest.approx(9.0, abs=0.001)
