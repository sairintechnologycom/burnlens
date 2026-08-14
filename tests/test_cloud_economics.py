"""BL-F2: cloud GET /api/v1/economics."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from burnlens_cloud.findings import get_economics_overview


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EconConn:
    def __init__(self):
        self.requests: list[dict] = []
        self.findings: list[dict] = []
        self.outcomes: list[dict] = []

    async def fetchrow(self, sql, *args):
        if "status_code >= 400" in sql:
            rows = [r for r in self.requests if int(r.get("status_code") or 200) >= 400]
            return {
                "spend": sum(float(r["cost_usd"]) for r in rows),
                "n": len(rows),
            }
        if "COUNT(trace_id)" in sql:
            return {
                "request_count": len(self.requests),
                "traced_count": sum(1 for r in self.requests if r.get("trace_id")),
                "parented_count": sum(1 for r in self.requests if r.get("parent_span_id")),
                "distinct_traces": len({r["trace_id"] for r in self.requests if r.get("trace_id")}),
            }
        if "FROM waste_findings" in sql and "GROUP BY" not in sql:
            openish = [
                f for f in self.findings if f["status"] in ("open", "acknowledged")
            ]
            return {
                "total_waste": sum(float(f["estimated_waste_usd"]) for f in openish),
                "open_count": len(openish),
            }
        if "FROM request_records" in sql:
            return {"spend": sum(float(r["cost_usd"]) for r in self.requests)}
        return None

    async def fetch(self, sql, *args):
        if "GROUP BY detector" in sql:
            buckets: dict[str, float] = {}
            for f in self.findings:
                if f["status"] not in ("open", "acknowledged"):
                    continue
                buckets[f["detector"]] = buckets.get(f["detector"], 0.0) + float(
                    f["estimated_waste_usd"]
                )
            return [{"detector": k, "waste": v} for k, v in buckets.items()]
        if "cost_accepted" in sql or "FULL OUTER JOIN" in sql:
            return self.outcomes
        return []


@pytest.mark.asyncio
async def test_economics_spend_waste_error_and_cost_per_accepted():
    ws = uuid4()
    conn = EconConn()
    conn.requests = [
        {"cost_usd": 1.00, "status_code": 200, "trace_id": "aa", "parent_span_id": "p"},
        {"cost_usd": 0.50, "status_code": 200, "trace_id": "aa"},
        {"cost_usd": 0.25, "status_code": 500},
    ]
    conn.findings = [
        {
            "status": "open",
            "detector": "ModelOverkillDetector",
            "estimated_waste_usd": 0.40,
        },
        {
            "status": "resolved",
            "detector": "ContextBloatDetector",
            "estimated_waste_usd": 9.00,
        },
    ]
    conn.outcomes = [{"accepted_count": 2, "cost_total": 1.50}]

    overview = await get_economics_overview(conn, ws, _now() - timedelta(days=7))
    assert overview["total_spend_usd"] == pytest.approx(1.75)
    assert overview["detected_waste_usd"] == pytest.approx(0.40)
    assert overview["waste_rate"] == pytest.approx(0.4 / 1.75, rel=1e-3)
    assert overview["error_spend_usd"] == pytest.approx(0.25)
    assert overview["error_request_count"] == 1
    assert overview["accepted_count"] == 2
    assert overview["cost_per_accepted_usd"] == pytest.approx(0.75)
    assert overview["waste_estimate_clamped"] is False
    assert overview["open_finding_count"] == 1
    assert overview["waste_by_detector"]["ModelOverkillDetector"] == pytest.approx(0.40)


@pytest.mark.asyncio
async def test_economics_clamps_waste_rate_when_estimates_overlap():
    conn = EconConn()
    conn.requests = [{"cost_usd": 1.00, "status_code": 200}]
    conn.findings = [
        {"status": "open", "detector": "A", "estimated_waste_usd": 0.80},
        {"status": "open", "detector": "B", "estimated_waste_usd": 0.80},
    ]
    overview = await get_economics_overview(conn, uuid4(), _now() - timedelta(days=7))
    assert overview["waste_estimate_clamped"] is True
    assert overview["waste_rate"] == 1.0
    assert overview["detected_waste_usd"] == pytest.approx(1.00)


@pytest.mark.asyncio
async def test_economics_cost_per_accepted_is_null_when_nothing_accepted():
    conn = EconConn()
    conn.requests = [{"cost_usd": 2.00, "status_code": 200}]
    conn.outcomes = [{"accepted_count": 0, "cost_total": 2.00}]
    overview = await get_economics_overview(conn, uuid4(), _now() - timedelta(days=7))
    assert overview["cost_per_accepted_usd"] is None
    assert overview["accepted_count"] == 0


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


@pytest_asyncio.fixture
async def econ_client():
    from burnlens_cloud.findings_api import router

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_economics_endpoint_zero_accepted_serialises_null(econ_client):
    from burnlens_cloud.auth import encode_jwt

    ws = uuid4()
    conn = EconConn()
    token = encode_jwt(str(ws), str(uuid4()), "owner", "cloud")
    with patch("burnlens_cloud.findings_api.get_pool", return_value=FakePool(conn)):
        resp = await econ_client.get(
            "/api/v1/economics",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["cost_per_accepted_usd"] is None
    assert "cost_per_accepted_usd" in body
