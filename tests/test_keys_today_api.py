"""CODE-2 STEP 8: dashboard /api/keys-today endpoint.

Covers the per-API-key daily-cap progress panel: registered keys without
traffic, capped keys at varying utilisation, uncapped traffic (NO_CAP),
default-cap fallback, and the empty-state contract.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from burnlens.config import (
    AlertsConfig,
    ApiKeyBudgetsConfig,
    BurnLensConfig,
    KeyBudgetEntry,
)
from burnlens.dashboard.routes import router as dashboard_router
from burnlens.keys import register_key
from burnlens.storage.database import insert_request
from burnlens.storage.models import RequestRecord


def _make_config(
    keys: dict[str, KeyBudgetEntry] | None = None,
    default: KeyBudgetEntry | None = None,
    tz: str = "UTC",
) -> BurnLensConfig:
    return BurnLensConfig(
        alerts=AlertsConfig(
            api_key_budgets=ApiKeyBudgetsConfig(
                keys=keys or {},
                default=default,
                reset_timezone=tz,
            ),
        ),
    )


async def _seed_spend(
    db_path: str,
    label: str | None,
    cost: float,
    timestamp: datetime | None = None,
) -> None:
    tags: dict[str, Any] = {}
    if label is not None:
        tags["key_label"] = label
    await insert_request(
        db_path,
        RequestRecord(
            provider="openai",
            model="gpt-4o",
            request_path="/v1/chat",
            timestamp=timestamp or datetime.now(timezone.utc),
            input_tokens=0,
            output_tokens=0,
            reasoning_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=0,
            cost_usd=cost,
            duration_ms=0,
            status_code=200,
            tags=tags,
        ),
    )


@pytest_asyncio.fixture
async def app_client(initialized_db: str) -> AsyncIterator[tuple[AsyncClient, FastAPI]]:
    app = FastAPI()
    app.state.db_path = initialized_db
    app.state.config = _make_config()
    app.include_router(dashboard_router, prefix="/api")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, app


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_state_no_keys_no_traffic(app_client) -> None:
    client, _ = app_client
    resp = await client.get("/api/keys-today")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_registered_key_with_no_traffic_shows_zero_spend(
    app_client, initialized_db: str
) -> None:
    client, app = app_client
    app.state.config = _make_config(
        keys={"backend": KeyBudgetEntry(daily_usd=10.0)},
    )
    await register_key(initialized_db, "backend", "openai", "sk-bk")

    resp = await client.get("/api/keys-today")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["label"] == "backend"
    assert row["spent_usd"] == 0.0
    assert row["daily_cap"] == 10.0
    assert row["pct_used"] == 0.0
    assert row["status"] == "OK"
    assert row["reset_timezone"] == "UTC"


@pytest.mark.asyncio
async def test_status_thresholds(app_client, initialized_db: str) -> None:
    client, app = app_client
    app.state.config = _make_config(
        keys={
            "ok": KeyBudgetEntry(daily_usd=10.0),
            "warn": KeyBudgetEntry(daily_usd=10.0),
            "crit": KeyBudgetEntry(daily_usd=10.0),
        },
    )
    await _seed_spend(initialized_db, "ok", cost=4.0)     # 40% → OK
    await _seed_spend(initialized_db, "warn", cost=8.0)   # 80% → WARNING
    await _seed_spend(initialized_db, "crit", cost=12.0)  # 120% → CRITICAL

    resp = await client.get("/api/keys-today")
    assert resp.status_code == 200
    rows = resp.json()
    by_label = {r["label"]: r for r in rows}

    assert by_label["ok"]["status"] == "OK"
    assert by_label["ok"]["pct_used"] == 40.0

    assert by_label["warn"]["status"] == "WARNING"
    assert by_label["warn"]["pct_used"] == 80.0

    assert by_label["crit"]["status"] == "CRITICAL"
    assert by_label["crit"]["pct_used"] == 120.0


@pytest.mark.asyncio
async def test_sorted_by_pct_desc_with_uncapped_at_bottom(
    app_client, initialized_db: str
) -> None:
    client, app = app_client
    app.state.config = _make_config(
        keys={
            "low": KeyBudgetEntry(daily_usd=100.0),  # 1%
            "high": KeyBudgetEntry(daily_usd=10.0),  # 90%
        },
    )
    await _seed_spend(initialized_db, "low", cost=1.0)
    await _seed_spend(initialized_db, "high", cost=9.0)
    await _seed_spend(initialized_db, "uncapped", cost=50.0)

    resp = await client.get("/api/keys-today")
    rows = resp.json()
    assert [r["label"] for r in rows] == ["high", "low", "uncapped"]
    assert rows[2]["status"] == "NO_CAP"
    assert rows[2]["daily_cap"] is None
    assert rows[2]["pct_used"] is None


@pytest.mark.asyncio
async def test_default_cap_applies_to_unspecified_label(
    app_client, initialized_db: str
) -> None:
    client, app = app_client
    app.state.config = _make_config(
        default=KeyBudgetEntry(daily_usd=20.0),
    )
    await _seed_spend(initialized_db, "ad-hoc", cost=5.0)

    resp = await client.get("/api/keys-today")
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["label"] == "ad-hoc"
    assert rows[0]["daily_cap"] == 20.0
    assert rows[0]["pct_used"] == 25.0
    assert rows[0]["status"] == "OK"


@pytest.mark.asyncio
async def test_unregistered_traffic_with_no_cap_is_no_cap(
    app_client, initialized_db: str
) -> None:
    """Traffic carrying a key_label tag with no cap configured shows as NO_CAP."""
    client, _ = app_client
    await _seed_spend(initialized_db, "stray", cost=3.0)

    resp = await client.get("/api/keys-today")
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["label"] == "stray"
    assert rows[0]["status"] == "NO_CAP"
    assert rows[0]["spent_usd"] == 3.0


@pytest.mark.asyncio
async def test_null_key_label_traffic_is_skipped(
    app_client, initialized_db: str
) -> None:
    """Requests with no key_label tag must not surface as a phantom row."""
    client, _ = app_client
    await _seed_spend(initialized_db, label=None, cost=99.0)

    resp = await client.get("/api/keys-today")
    assert resp.json() == []


@pytest.mark.asyncio
async def test_reset_timezone_propagates(
    app_client, initialized_db: str
) -> None:
    client, app = app_client
    app.state.config = _make_config(
        keys={"k": KeyBudgetEntry(daily_usd=10.0)},
        tz="Asia/Kolkata",
    )
    await register_key(initialized_db, "k", "openai", "sk-tz")

    resp = await client.get("/api/keys-today")
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["reset_timezone"] == "Asia/Kolkata"
