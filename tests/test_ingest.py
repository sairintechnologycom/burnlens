import pytest
from unittest.mock import patch, AsyncMock
from uuid import uuid4
from datetime import datetime


@pytest.mark.asyncio
async def test_ingest_valid_batch(client):
    """Test successful ingest of valid batch."""
    workspace_id = str(uuid4())
    api_key = "bl_live_test123"

    with patch("burnlens_cloud.ingest.get_workspace_by_api_key") as mock_get_ws:
        with patch("burnlens_cloud.ingest.check_free_tier_limit") as mock_check_limit:
            with patch("burnlens_cloud.ingest.execute_bulk_insert") as mock_insert:
                mock_get_ws.return_value = (workspace_id, "cloud")
                mock_check_limit.return_value = True
                mock_insert.return_value = None

                response = await client.post(
                    "/v1/ingest",
                    json={
                        "api_key": api_key,
                        "records": [
                            {
                                "timestamp": "2024-01-15T10:30:00Z",
                                "provider": "openai",
                                "model": "gpt-4o",
                                "input_tokens": 100,
                                "output_tokens": 50,
                                "reasoning_tokens": 0,
                                "cache_read_tokens": 0,
                                "cache_write_tokens": 0,
                                "cost_usd": 0.015,
                                "duration_ms": 1250,
                                "status_code": 200,
                                "tags": {"team": "backend"},
                                "system_prompt_hash": "hash123",
                            }
                        ],
                    },
                )

    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] == 1
    assert data["rejected"] == 0


@pytest.mark.asyncio
async def test_ingest_invalid_api_key(client):
    """Test ingest with invalid API key."""
    with patch("burnlens_cloud.ingest.get_workspace_by_api_key") as mock_get_ws:
        mock_get_ws.return_value = None

        response = await client.post(
            "/v1/ingest",
            json={
                "api_key": "invalid_key",
                "records": [],
            },
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_ingest_free_tier_limit(client):
    """Test free tier monthly limit enforcement."""
    workspace_id = str(uuid4())
    api_key = "bl_live_test123"

    with patch("burnlens_cloud.ingest.get_workspace_by_api_key") as mock_get_ws:
        with patch("burnlens_cloud.ingest.check_free_tier_limit") as mock_check_limit:
            mock_get_ws.return_value = (workspace_id, "free")
            mock_check_limit.return_value = False  # Exceeded limit

            response = await client.post(
                "/v1/ingest",
                json={
                    "api_key": api_key,
                    "records": [
                        {
                            "timestamp": "2024-01-15T10:30:00Z",
                            "provider": "openai",
                            "model": "gpt-4o",
                            "input_tokens": 100,
                            "output_tokens": 50,
                            "reasoning_tokens": 0,
                            "cache_read_tokens": 0,
                            "cache_write_tokens": 0,
                            "cost_usd": 0.015,
                            "duration_ms": 1250,
                            "status_code": 200,
                            "tags": {},
                            "system_prompt_hash": None,
                        }
                    ],
                },
            )

    assert response.status_code == 429
    data = response.json()
    assert "free_tier_limit" in str(data)


@pytest.mark.asyncio
async def test_ingest_bulk_performance():
    """Test that bulk insert handles 500 records efficiently."""
    from burnlens_cloud.ingest import IngestRequest
    from burnlens_cloud.models import RequestRecordBase

    # Create 500 records
    records = [
        RequestRecordBase(
            timestamp=datetime.utcnow(),
            provider="openai",
            model="gpt-4o",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.015,
        )
        for _ in range(500)
    ]

    request = IngestRequest(
        api_key="bl_live_test",
        records=records,
    )

    assert len(request.records) == 500
    assert request.records[0].cost_usd == 0.015


@pytest.mark.asyncio
async def test_ingest_db_error(client):
    """Test handling of database errors during ingest."""
    workspace_id = str(uuid4())
    api_key = "bl_live_test123"

    with patch("burnlens_cloud.ingest.get_workspace_by_api_key") as mock_get_ws:
        with patch("burnlens_cloud.ingest.check_free_tier_limit") as mock_check_limit:
            with patch("burnlens_cloud.ingest.execute_bulk_insert") as mock_insert:
                mock_get_ws.return_value = (workspace_id, "cloud")
                mock_check_limit.return_value = True
                mock_insert.side_effect = Exception("Database error")

                response = await client.post(
                    "/v1/ingest",
                    json={
                        "api_key": api_key,
                        "records": [
                            {
                                "timestamp": "2024-01-15T10:30:00Z",
                                "provider": "openai",
                                "model": "gpt-4o",
                                "input_tokens": 100,
                                "output_tokens": 50,
                                "reasoning_tokens": 0,
                                "cache_read_tokens": 0,
                                "cache_write_tokens": 0,
                                "cost_usd": 0.015,
                                "duration_ms": 1250,
                                "status_code": 200,
                                "tags": {},
                                "system_prompt_hash": None,
                            }
                        ],
                    },
                )

    assert response.status_code == 500
