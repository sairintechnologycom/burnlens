"""The local dashboard's /api/budget must report MONTH-TO-DATE spend.

compute_budget_status divides spent_usd by the day of the month to forecast the
month, so handing it a lifetime total reports every dollar ever spent as this
month's and forecasts roughly 2x that. On a real dogfood database (158k rows,
$11k lifetime) the budget page read $11k spent against a monthly budget.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from burnlens.analysis.budget import period_start_iso
from burnlens.storage.database import init_db, insert_request
from burnlens.storage.models import RequestRecord


def _record(days_ago: float, cost: float) -> RequestRecord:
    return RequestRecord(
        provider="anthropic",
        model="claude-opus-5",
        request_path="/v1/messages",
        timestamp=datetime.now(timezone.utc) - timedelta(days=days_ago),
        input_tokens=1_000,
        output_tokens=50,
        cost_usd=cost,
        duration_ms=400,
        status_code=200,
        tags={},
    )


@pytest.fixture
async def db(tmp_path):
    path = str(tmp_path / "budget.db")
    await init_db(path)
    return path


@pytest.fixture
async def client(db):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from burnlens.dashboard.routes import router as dashboard_router

    app = FastAPI()
    app.state.db_path = db
    app.include_router(dashboard_router, prefix="/api")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def test_period_start_iso_is_the_first_of_this_month():
    now = datetime(2026, 8, 16, 13, 45, tzinfo=timezone.utc)
    assert period_start_iso("monthly", now).startswith("2026-08-01T00:00:00")
    # Defaulting `now` must not crash — the dashboard calls it with one arg.
    assert period_start_iso("monthly").endswith("+00:00")


async def test_budget_excludes_spend_from_before_this_month(client, db):
    """A row older than the month start must not count toward this month."""
    await insert_request(db, _record(days_ago=0, cost=5.0))
    # 400 days back is in a prior month whatever today's date is.
    await insert_request(db, _record(days_ago=400, cost=1000.0))

    body = (await client.get("/api/budget")).json()

    assert body["spent_usd"] == pytest.approx(5.0)
    # The forecast scales month-to-date spend, so the stale row must not reach
    # it either: 1005 * 30 / elapsed would dwarf any real projection.
    assert body["forecast_usd"] < 1000.0
