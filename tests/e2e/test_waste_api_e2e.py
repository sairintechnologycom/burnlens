"""End-to-end validation of dashboard /api/waste endpoint for new prompt detectors."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from burnlens.dashboard.routes import router as dashboard_router
from burnlens.storage.database import init_db, insert_request
from burnlens.storage.models import RequestRecord

def _create_record(
    provider="openai",
    model="gpt-4o",
    input_tokens=1000,
    output_tokens=100,
    cost_usd=0.01,
    system_prompt_hash=None,
    cache_read_tokens=0,
    prompt_system_tokens=0,
    prompt_user_tokens=0,
    prompt_tools_tokens=0,
    prompt_rag_tokens=0,
    prompt_history_tokens=0,
):
    return RequestRecord(
        provider=provider,
        model=model,
        request_path="/v1/chat/completions",
        timestamp=datetime.now(timezone.utc),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        duration_ms=500,
        status_code=200,
        tags={},
        system_prompt_hash=system_prompt_hash,
        cache_read_tokens=cache_read_tokens,
        prompt_system_tokens=prompt_system_tokens,
        prompt_user_tokens=prompt_user_tokens,
        prompt_tools_tokens=prompt_tools_tokens,
        prompt_rag_tokens=prompt_rag_tokens,
        prompt_history_tokens=prompt_history_tokens,
    )


@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "waste_api_test.db")


@pytest.fixture
async def seeded_db(db_path: str) -> str:
    await init_db(db_path)

    # 1. Trigger PromptCachingOpportunityDetector:
    # 5 requests with same system prompt hash, large system tokens (1500), cache_read_tokens=0
    for _ in range(5):
        await insert_request(
            db_path,
            _create_record(
                system_prompt_hash="cache-op-hash",
                prompt_system_tokens=1500,
                cache_read_tokens=0,
                cost_usd=0.10,
            ),
        )

    # 2. Trigger OversizedToolSchemaDetector:
    # 3 requests with tools tokens >= 1000 and ratio >= 30%
    for _ in range(3):
        await insert_request(
            db_path,
            _create_record(
                input_tokens=3000,
                prompt_tools_tokens=1500,
                cost_usd=0.10,
            ),
        )

    # 3. Trigger LowRAGEfficiencyDetector:
    # 3 requests with RAG tokens >= 8000 and output tokens < 100
    for _ in range(3):
        await insert_request(
            db_path,
            _create_record(
                prompt_rag_tokens=9000,
                output_tokens=50,
                cost_usd=0.20,
            ),
        )

    # 4. Trigger HistoryBloatDetector:
    # 3 requests with history tokens >= 5000 and ratio >= 50%
    for _ in range(3):
        await insert_request(
            db_path,
            _create_record(
                input_tokens=10000,
                prompt_history_tokens=6000,
                cost_usd=0.20,
            ),
        )

    return db_path


@pytest.mark.asyncio
async def test_dashboard_api_waste_endpoint(seeded_db: str):
    # Build FastAPI test app
    app = FastAPI()
    app.state.db_path = seeded_db
    app.include_router(dashboard_router, prefix="/api")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/waste")

    assert resp.status_code == 200
    data = resp.json()

    # The result should contain all 8 findings
    assert len(data) == 8

    # Verify that our 4 new prompt detectors are represented
    findings_by_detector = {item["detector"]: item for item in data}

    # 1. PromptCachingOpportunityDetector
    caching = findings_by_detector["PromptCachingOpportunityDetector"]
    assert caching["severity"] == "medium"
    assert caching["affected_count"] == 5
    assert caching["estimated_waste_usd"] == round(0.50 * 0.3, 6)  # 30% of $0.50

    # 2. OversizedToolSchemaDetector
    tools = findings_by_detector["OversizedToolSchemaDetector"]
    assert tools["severity"] == "medium"
    assert tools["affected_count"] == 3
    assert tools["estimated_waste_usd"] == round(0.30 * 0.5, 6)  # 50% of $0.30

    # 3. LowRAGEfficiencyDetector
    rag = findings_by_detector["LowRAGEfficiencyDetector"]
    assert rag["severity"] == "medium"
    assert rag["affected_count"] == 3
    assert rag["estimated_waste_usd"] == round(0.60 * 0.5, 6)  # 50% of $0.60

    # 4. HistoryBloatDetector
    history = findings_by_detector["HistoryBloatDetector"]
    assert history["severity"] == "medium"
    assert history["affected_count"] == 3
    assert history["estimated_waste_usd"] == round(0.60 * 0.4, 6)  # 40% of $0.60
