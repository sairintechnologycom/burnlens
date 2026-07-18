"""Tests for real-time anomaly and runaway agent loop detection."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from burnlens.detection.anomaly import (
    AnomalyDetector,
    calculate_mad,
    calculate_median,
    calculate_mean_std,
)
from burnlens.storage.database import (
    insert_request,
    insert_anomaly_event,
)
from burnlens.storage.models import RequestRecord, AnomalyEvent
from burnlens.storage.queries import get_recent_anomaly_events

from .conftest import settle_background_tasks
from burnlens.config import BurnLensConfig, AlertsConfig


# ---------------------------------------------------------------------------
# Test Statistics Math Helpers
# ---------------------------------------------------------------------------

def test_stats_math():
    """Verify median, MAD, and mean/std calculation helper functions."""
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert calculate_median(vals) == 3.0

    vals_even = [1.0, 2.0, 3.0, 4.0]
    assert calculate_median(vals_even) == 2.5

    assert calculate_median([]) == 0.0

    # MAD: median of absolute deviations from median (3.0)
    # deviations: [2.0, 1.0, 0.0, 1.0, 2.0] -> sorted: [0.0, 1.0, 1.0, 2.0, 2.0] -> median is 1.0
    assert calculate_mad(vals, 3.0) == 1.0
    assert calculate_mad([], 0.0) == 0.0

    mean, std = calculate_mean_std(vals)
    assert mean == 3.0
    assert abs(std - 2.0**0.5) < 1e-7
    assert calculate_mean_std([]) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# Anomaly Detector Unit Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_anomaly_detector_zero_baseline_spike(initialized_db: str):
    """With an empty past baseline, a sudden request exceeding limits triggers a cost spike."""
    config = BurnLensConfig(
        db_path=initialized_db,
        alerts=AlertsConfig(terminal=False, slack_webhook=None)
    )
    detector = AnomalyDetector(config, initialized_db)

    # Insert a single request costing $0.20 (min threshold for 1m is $0.10)
    now = datetime.now(timezone.utc)
    record = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        cost_usd=0.20,
        timestamp=now,
    )
    await insert_request(initialized_db, record)

    # Run check on scope org
    await detector.check_scope("org", "*")

    # Verify anomaly is logged
    events = await get_recent_anomaly_events(initialized_db)
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "cost_spike"
    assert event.scope == "org"
    assert event.target == "*"
    assert event.severity == "critical"  # Z-score fallback defaults to 10.0 (> 5.0)
    assert event.details["window"] == "1m"
    assert event.details["current_value"] == 0.20


@pytest.mark.asyncio
async def test_anomaly_detector_runaway_loop(initialized_db: str):
    """12 requests with 91.6% duplicate system prompt hashes trigger runaway loop."""
    config = BurnLensConfig(
        db_path=initialized_db,
        alerts=AlertsConfig(terminal=False, slack_webhook=None)
    )
    detector = AnomalyDetector(config, initialized_db)

    now = datetime.now(timezone.utc)
    for _ in range(12):
        record = RequestRecord(
            provider="openai",
            model="gpt-4o",
            request_path="/v1/chat/completions",
            cost_usd=0.01,
            system_prompt_hash="runaway_hash",
            timestamp=now,
        )
        await insert_request(initialized_db, record)

    # Run check on scope model
    await detector.check_scope("model", "gpt-4o")

    # Verify runaway loop is logged
    events = await get_recent_anomaly_events(initialized_db)
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "runaway_loop"
    assert event.scope == "model"
    assert event.target == "gpt-4o"
    assert event.severity == "critical"
    assert event.details["window"] == "1m"
    assert event.details["current_value"] == 12
    assert event.details["duplicate_ratio"] > 0.8


@pytest.mark.asyncio
async def test_anomaly_detector_deduplication(initialized_db: str):
    """Anomalies on the same scope/target/window are deduplicated within an hour."""
    config = BurnLensConfig(
        db_path=initialized_db,
        alerts=AlertsConfig(terminal=False, slack_webhook=None)
    )
    detector = AnomalyDetector(config, initialized_db)

    now = datetime.now(timezone.utc)
    record = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        cost_usd=0.20,
        timestamp=now,
    )
    await insert_request(initialized_db, record)

    # First check triggers alert
    await detector.check_scope("org", "*")
    events = await get_recent_anomaly_events(initialized_db)
    assert len(events) == 1

    # Second check should NOT trigger alert (deduplicated)
    await detector.check_scope("org", "*")
    events = await get_recent_anomaly_events(initialized_db)
    assert len(events) == 1


# ---------------------------------------------------------------------------
# Dashboard API Router Integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dashboard_api_anomalies_endpoint(initialized_db: str):
    """GET /api/anomalies returns the logged anomaly events."""
    from burnlens.dashboard.routes import router as dashboard_router

    # Insert a dummy anomaly event
    event = AnomalyEvent(
        event_type="cost_spike",
        scope="team",
        target="engineering",
        severity="warning",
        details={"window": "5m", "description": "Test warning"},
    )
    await insert_anomaly_event(initialized_db, event)

    # Build FastAPI test app
    app = FastAPI()
    app.state.db_path = initialized_db
    app.include_router(dashboard_router, prefix="/api")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/anomalies")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["event_type"] == "cost_spike"
    assert data[0]["scope"] == "team"
    assert data[0]["target"] == "engineering"
    assert data[0]["severity"] == "warning"
    assert data[0]["details"]["window"] == "5m"
    assert data[0]["details"]["description"] == "Test warning"


# ---------------------------------------------------------------------------
# Interceptor Integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_interceptor_anomaly_bg_task(initialized_db: str):
    """_run_anomaly_detection helper initiates detection successfully."""
    from burnlens.proxy.interceptor import _run_anomaly_detection

    config = BurnLensConfig(
        db_path=initialized_db,
        alerts=AlertsConfig(terminal=False, slack_webhook=None)
    )

    # Insert a dummy record
    record = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        cost_usd=0.50,
        timestamp=datetime.now(timezone.utc),
    )
    await insert_request(initialized_db, record)

    # Run check
    _run_anomaly_detection(record, config, initialized_db)

    # Wait for the asyncio background task to finish executing
    await settle_background_tasks()

    events = await get_recent_anomaly_events(initialized_db)
    assert len(events) == 4
    assert events[0].event_type == "cost_spike"
