"""BL-E4: the dashboard's findings API and its one state-changing route."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from burnlens.analysis.waste import ModelOverkillDetector
from burnlens.dashboard.routes import router as dashboard_router
from burnlens.storage.database import init_db, insert_request
from burnlens.storage.findings import list_findings, sync_findings
from burnlens.storage.models import RequestRecord

_ROWS = [
    {
        "model": "claude-opus-5",
        "input_tokens": 1_000,
        "output_tokens": 50,
        "cost_usd": 0.25,
        "tags": {"workflow_id": "invoice-gen"},
        "system_prompt_hash": None,
    }
    for _ in range(20)
]


@pytest.fixture
async def client(tmp_path):
    db_path = str(tmp_path / "api.db")
    await init_db(db_path)
    for _ in range(20):
        await insert_request(
            db_path,
            RequestRecord(
                provider="anthropic",
                model="claude-opus-5",
                request_path="/v1/messages",
                timestamp=datetime.now(timezone.utc),
                input_tokens=1_000,
                output_tokens=50,
                cost_usd=0.25,
                duration_ms=400,
                status_code=200,
                tags={"workflow_id": "invoice-gen"},
            ),
        )
    await sync_findings(db_path, ModelOverkillDetector().run(_ROWS))

    app = FastAPI()
    app.state.db_path = db_path
    app.include_router(dashboard_router, prefix="/api")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.db_path = db_path
        yield c


@pytest.mark.asyncio
async def test_findings_are_listed_with_lifecycle_state(client):
    resp = await client.get("/api/findings")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["status"] == "open"
    assert body[0]["subject_type"] == "workflow"
    assert body[0]["subject_key"] == "invoice-gen"
    assert body[0]["id"]


@pytest.mark.asyncio
async def test_findings_filter_by_status(client):
    assert len((await client.get("/api/findings?status=open")).json()) == 1
    assert (await client.get("/api/findings?status=resolved")).json() == []


@pytest.mark.asyncio
async def test_status_change_requires_x_requested_with(client):
    """The dashboard API's only mutation. server.host can be set to 0.0.0.0,
    which would otherwise expose an unauthenticated state change."""
    finding_id = (await client.get("/api/findings")).json()[0]["id"]

    resp = await client.post(
        f"/api/findings/{finding_id}/status", json={"status": "resolved"}
    )

    assert resp.status_code == 403
    # And the finding is genuinely untouched, not merely reported as refused.
    assert (await client.get("/api/findings")).json()[0]["status"] == "open"


@pytest.mark.asyncio
async def test_status_change_applies_with_the_header(client):
    finding_id = (await client.get("/api/findings")).json()[0]["id"]

    resp = await client.post(
        f"/api/findings/{finding_id}/status",
        json={"status": "acknowledged"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert resp.status_code == 200
    stored = await list_findings(client.db_path)
    assert stored[0].status == "acknowledged"


@pytest.mark.asyncio
async def test_invalid_status_is_rejected(client):
    finding_id = (await client.get("/api/findings")).json()[0]["id"]

    resp = await client.post(
        f"/api/findings/{finding_id}/status",
        json={"status": "fixed-ish"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_unknown_finding_404s(client):
    resp = await client.post(
        "/api/findings/nope/status",
        json={"status": "resolved"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_verify_endpoint_returns_verdicts(client):
    finding_id = (await client.get("/api/findings")).json()[0]["id"]
    await client.post(
        f"/api/findings/{finding_id}/status",
        json={"status": "resolved"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    resp = await client.get("/api/findings/verify")

    assert resp.status_code == 200
    verdicts = resp.json()
    assert len(verdicts) == 1
    # Resolved seconds ago — the honest answer is "not yet", not a number.
    assert verdicts[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_economics_endpoint_serves_the_kpis(client):
    resp = await client.get("/api/economics?period=30d")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_spend_usd"] == pytest.approx(5.0)
    assert body["detected_waste_usd"] > 0
    assert 0 <= body["waste_rate"] <= 1
    assert body["cost_confidence"]["total_requests"] == 20
    assert body["cost_confidence"]["unpriced_requests"] == 0
    assert body["outcome_coverage"]["cost_untagged_usd"] == pytest.approx(0.0)
    assert body["outcome_coverage"]["cost_unattributed_usd"] == pytest.approx(5.0)
    assert "savings" in body
    assert "verified_monthly_usd" in body["savings"]


@pytest.mark.asyncio
async def test_findings_savings_endpoint_matches_the_cloud_contract(client):
    resp = await client.get("/api/findings/savings")
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "open_projected_monthly_usd",
        "verified_monthly_usd",
        "missed_predicted_monthly_usd",
        "inconclusive_predicted_monthly_usd",
        "realisation_pct",
        "counts",
    ):
        assert key in body
    assert body["counts"]["open"] >= 1


@pytest.mark.asyncio
async def test_summary_counts_unpriced_requests(client):
    await insert_request(
        client.db_path,
        RequestRecord(
            provider="openai",
            model="zzz-not-a-real-model-v0",
            request_path="/v1/chat/completions",
            timestamp=datetime.now(timezone.utc),
            cost_usd=0.0,
        ),
    )
    resp = await client.get("/api/summary?period=30d")
    assert resp.status_code == 200
    body = resp.json()
    assert body["unpriced_requests"] == 1
    assert body["total_requests"] == 21
