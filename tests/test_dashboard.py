"""Tests for dashboard API endpoints."""
from __future__ import annotations

import time
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_stats_scoped_to_workspace(authed_client):
    ac, mock_conn, token, ws_id = authed_client

    # First call: get_current_workspace lookup (already mocked in fixture)
    # Second call: the stats query
    mock_conn.fetchrow.side_effect = [
        {"id": ws_id, "name": "Test WS", "plan": "cloud", "active": True},
        {"total_cost": 12.34, "total_requests": 500, "avg_cost": 0.02468},
    ]

    resp = await ac.get("/api/stats?days=7", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cost"] == 12.34
    assert data["total_requests"] == 500


@pytest.mark.asyncio
async def test_cost_by_model_correct_aggregation(authed_client):
    ac, mock_conn, token, ws_id = authed_client

    mock_conn.fetchrow.return_value = {"id": ws_id, "name": "Test WS", "plan": "cloud", "active": True}
    mock_conn.fetch = AsyncMock(return_value=[
        {"model": "gpt-4o-mini", "cost": 0.45},
        {"model": "claude-haiku", "cost": 0.12},
    ])

    resp = await ac.get("/api/cost-by-model?days=7", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["gpt-4o-mini"] == 0.45
    assert data["claude-haiku"] == 0.12


@pytest.mark.asyncio
async def test_history_clamped_by_plan():
    from api.dashboard import _effective_days

    assert _effective_days(30, "free") == 7
    assert _effective_days(7, "free") == 7
    assert _effective_days(180, "cloud") == 90
    assert _effective_days(1000, "teams") == 365
    assert _effective_days(5000, "enterprise") == 3650


@pytest.mark.asyncio
async def test_unauthenticated_request_401(client):
    ac, _ = client

    resp = await ac.get("/api/stats")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cost_timeline_zero_filled(authed_client):
    ac, mock_conn, token, ws_id = authed_client

    mock_conn.fetchrow.return_value = {"id": ws_id, "name": "Test WS", "plan": "cloud", "active": True}
    # Return data for only 1 out of 3 days
    mock_conn.fetch = AsyncMock(return_value=[
        {"day": date(2026, 4, 13), "cost": 1.50},
    ])

    resp = await ac.get("/api/cost-timeline?days=3", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    data = resp.json()
    # Should have entries for each day in the range, zero-filled
    assert len(data) >= 3
    costs = [d["cost"] for d in data]
    assert 1.50 in costs
    # At least some zero-filled entries
    assert 0.0 in costs
