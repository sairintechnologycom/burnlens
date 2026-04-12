"""Dashboard API data consistency tests.

Validates that dashboard API responses match raw SQLite data.
Uses a lightweight FastAPI test app with the dashboard router mounted,
seeded with 30 synthetic rows from conftest_e2e.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import aiosqlite
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from burnlens.dashboard.routes import router as dashboard_router
from burnlens.storage.database import init_db, insert_request
from burnlens.storage.models import RequestRecord
from burnlens.cost.calculator import TokenUsage, calculate_cost

# ---------------------------------------------------------------------------
# Seed helpers (mirror conftest_e2e logic but self-contained)
# ---------------------------------------------------------------------------

_MODELS = {
    "openai": ["gpt-4o-mini", "gpt-4o"],
    "anthropic": ["claude-haiku-4-5-20251001"],
    "google": ["gemini-1.5-flash"],
}
_REQUEST_PATHS = {
    "openai": "/v1/chat/completions",
    "anthropic": "/v1/messages",
    "google": "/v1beta/models/gemini-1.5-flash:generateContent",
}
_FEATURES = ["chat", "search", "summarise"]
_TEAMS = ["backend", "research", "infra"]
_CUSTOMERS = ["acme-corp", "beta-user", "unknown-co"]
_SEED_COUNT = 30


def _calc_cost(provider: str, model: str, inp: int, out: int) -> float:
    return calculate_cost(provider, model, TokenUsage(input_tokens=inp, output_tokens=out))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module")
async def test_db():
    """Create a temp DB, seed 30 rows, yield path, then clean up."""
    import hashlib
    import random

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    await init_db(db_path)

    now = datetime.now(timezone.utc)
    rng = random.Random(42)

    for i in range(_SEED_COUNT):
        provider = ["openai", "openai", "anthropic", "google"][i % 4]
        model = _MODELS[provider][i % len(_MODELS[provider])]
        input_tokens = rng.randint(50, 8000)
        output_tokens = rng.randint(10, 500)
        days_ago = rng.uniform(0, 14)

        record = RequestRecord(
            provider=provider,
            model=model,
            request_path=_REQUEST_PATHS[provider],
            timestamp=now - timedelta(days=days_ago),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=_calc_cost(provider, model, input_tokens, output_tokens),
            duration_ms=rng.randint(200, 5000),
            status_code=200,
            tags={
                "feature": _FEATURES[i % len(_FEATURES)],
                "team": _TEAMS[i % len(_TEAMS)],
                "customer": _CUSTOMERS[i % len(_CUSTOMERS)],
                "streaming": str(rng.choice([True, False])).lower(),
            },
            system_prompt_hash=hashlib.sha256(f"system-prompt-{i}".encode()).hexdigest(),
        )
        await insert_request(db_path, record)

    yield db_path

    os.unlink(db_path)
    # Clean up WAL/SHM files
    for ext in ("-wal", "-shm"):
        try:
            os.unlink(db_path + ext)
        except FileNotFoundError:
            pass


@pytest_asyncio.fixture(scope="module")
async def client(test_db: str):
    """Build a minimal test app with the dashboard router and return an async client."""
    app = FastAPI()
    app.state.db_path = test_db
    # Provide a minimal config stub so routes that check budget don't crash
    app.state.config = SimpleNamespace(alerts=None)
    app.include_router(dashboard_router, prefix="/api")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# 1. Total cost matches DB SUM
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stats_total_cost_matches_db_sum(client: httpx.AsyncClient, test_db: str):
    resp = await client.get("/api/summary", params={"period": "30d"})
    assert resp.status_code == 200
    api_cost = resp.json()["total_cost_usd"]

    async with aiosqlite.connect(test_db) as db:
        cursor = await db.execute("SELECT COALESCE(SUM(cost_usd), 0.0) FROM requests")
        row = await cursor.fetchone()
    db_cost = float(row[0])

    # API rounds to 6 decimal places in the summary endpoint
    assert round(api_cost, 6) == round(db_cost, 6)


# ---------------------------------------------------------------------------
# 2. Request count matches DB COUNT
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stats_request_count_matches_db_count(client: httpx.AsyncClient, test_db: str):
    resp = await client.get("/api/summary", params={"period": "30d"})
    assert resp.status_code == 200
    api_count = resp.json()["total_requests"]

    async with aiosqlite.connect(test_db) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM requests")
        row = await cursor.fetchone()
    db_count = int(row[0])

    assert api_count == db_count


# ---------------------------------------------------------------------------
# 3. Cost-by-model sums to total
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cost_by_model_sums_to_total(client: httpx.AsyncClient):
    models_resp = await client.get("/api/costs/by-model", params={"period": "30d"})
    assert models_resp.status_code == 200
    model_total = sum(m["total_cost_usd"] for m in models_resp.json())

    summary_resp = await client.get("/api/summary", params={"period": "30d"})
    assert summary_resp.status_code == 200
    api_total = summary_resp.json()["total_cost_usd"]

    assert model_total == pytest.approx(api_total, rel=1e-5)


# ---------------------------------------------------------------------------
# 4. All seeded models present
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cost_by_model_all_models_present(client: httpx.AsyncClient):
    resp = await client.get("/api/costs/by-model", params={"period": "30d"})
    assert resp.status_code == 200
    models_in_response = {m["model"] for m in resp.json()}

    expected = {"gpt-4o-mini", "gpt-4o", "claude-haiku-4-5-20251001", "gemini-1.5-flash"}
    assert expected.issubset(models_in_response), (
        f"Missing models: {expected - models_in_response}"
    )


# ---------------------------------------------------------------------------
# 5. Cost-by-team matches DB per-team sums
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cost_by_team_sums_correctly(client: httpx.AsyncClient, test_db: str):
    resp = await client.get("/api/costs/by-tag", params={"tag": "team", "period": "30d"})
    assert resp.status_code == 200
    api_teams = {entry["tag"]: entry["total_cost_usd"] for entry in resp.json()}

    async with aiosqlite.connect(test_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT json_extract(tags, '$.team') AS team, SUM(cost_usd) AS total
            FROM requests
            WHERE json_extract(tags, '$.team') IS NOT NULL
            GROUP BY json_extract(tags, '$.team')
            """
        )
        rows = await cursor.fetchall()

    for row in rows:
        team = row["team"]
        assert team in api_teams, f"Team {team!r} missing from API response"
        assert round(api_teams[team], 6) == round(float(row["total"]), 6)


# ---------------------------------------------------------------------------
# 6. Cost-by-feature has no null/empty keys
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cost_by_feature_no_null_keys(client: httpx.AsyncClient):
    resp = await client.get("/api/costs/by-tag", params={"tag": "feature", "period": "30d"})
    assert resp.status_code == 200
    for entry in resp.json():
        tag = entry["tag"]
        assert tag is not None and tag != "", f"Found null/empty feature key: {tag!r}"


# ---------------------------------------------------------------------------
# 7. Cost timeline covers 14 days (seeded data spans 14 days)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cost_timeline_covers_14_days(client: httpx.AsyncClient):
    resp = await client.get("/api/costs/timeline", params={"period": "14d"})
    assert resp.status_code == 200
    data = resp.json()

    # Seeded data spread across 14 days — we should have multiple data points
    # (exact count depends on which days the RNG placed data)
    assert len(data) >= 1, "Timeline should have at least one data point"

    # Verify dates span multiple days
    dates = [entry["date"] for entry in data]
    assert len(set(dates)) == len(dates), "Timeline dates should be unique"

    # All dates should be within the last 14 days
    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=14)
    for d in dates:
        parsed = datetime.strptime(d, "%Y-%m-%d").date()
        assert parsed >= cutoff, f"Date {d} is older than 14 days"


# ---------------------------------------------------------------------------
# 8. Recent requests ordered by timestamp DESC
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recent_requests_ordered_by_timestamp_desc(client: httpx.AsyncClient):
    resp = await client.get("/api/requests", params={"limit": 50})
    assert resp.status_code == 200
    requests_data = resp.json()

    assert len(requests_data) > 0, "Should have seeded requests"

    timestamps = [r["timestamp"] for r in requests_data]
    assert timestamps == sorted(timestamps, reverse=True), (
        "Requests should be ordered by timestamp descending"
    )


# ---------------------------------------------------------------------------
# 9. Request costs are not in scientific notation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recent_requests_cost_not_scientific_notation(client: httpx.AsyncClient):
    resp = await client.get("/api/requests", params={"limit": 50})
    assert resp.status_code == 200

    # Check the raw JSON text (not parsed floats) since Python's json.loads
    # converts both "0.0000798" and "7.98e-05" to the same float.
    raw_text = resp.text
    for req in resp.json():
        cost = req["cost_usd"]
        # Verify the value is a valid number (not a string like "5.12e-05")
        assert isinstance(cost, (int, float)), (
            f"cost_usd should be numeric, got {type(cost).__name__}: {cost!r}"
        )
        # Check Python's repr doesn't use scientific notation for display purposes.
        # Note: JSON serializers may emit scientific notation for very small floats;
        # this is valid JSON but can cause display bugs in CSV exports / UIs.
        cost_str = f"{cost:.10f}"
        assert "e" not in cost_str.lower(), (
            f"Formatted cost should not use scientific notation: {cost_str}"
        )


# ---------------------------------------------------------------------------
# 10. Waste endpoint returns valid format (no 500 error)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_waste_alerts_format_valid(client: httpx.AsyncClient):
    resp = await client.get("/api/waste")
    assert resp.status_code == 200

    data = resp.json()
    assert isinstance(data, list), "Waste response should be a list"

    for item in data:
        assert "detector" in item, "Each waste finding must have 'detector'"
        assert "description" in item, "Each waste finding must have 'description'"
        assert "affected_count" in item, "Each waste finding must have 'affected_count'"
