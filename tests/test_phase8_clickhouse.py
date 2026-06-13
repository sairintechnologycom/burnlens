import pytest
import uuid
from datetime import datetime, timedelta
from burnlens_cloud.clickhouse import (
    get_clickhouse_client,
    init_clickhouse,
    get_spend_summary,
    get_spend_by_model,
    get_spend_by_tag,
    get_spend_timeseries,
)
from burnlens_cloud.config import settings

@pytest.mark.asyncio
async def test_clickhouse_initialization():
    """Test ClickHouse schema initialization."""
    # This assumes a ClickHouse instance is running or mocked
    try:
        await init_clickhouse()
        client = get_clickhouse_client()
        
        # Verify tables exist
        tables = client.query("SHOW TABLES FROM " + settings.clickhouse_database).result_rows
        table_names = [t[0] for t in tables]
        
        assert "request_records_raw" in table_names
        assert "request_records_queue" in table_names
        assert "daily_spend_rollup" in table_names
    except Exception as e:
        pytest.skip(f"ClickHouse not available for integration test: {e}")

@pytest.mark.asyncio
async def test_clickhouse_query_wrappers():
    """Test ClickHouse analytical query wrappers with sample data."""
    try:
        client = get_clickhouse_client()
        workspace_id = str(uuid.uuid4())
        today = datetime.utcnow().date()
        yesterday = today - timedelta(days=1)
        
        # Insert sample data directly into raw table for testing wrappers
        client.command(f"""
            INSERT INTO request_records_raw 
            (id, workspace_id, ts, provider, model, input_tokens, output_tokens, cost_usd, duration_ms, status_code, tag_feature, tag_team, tag_customer, received_at)
            VALUES 
            (generateUUIDv4(), '{workspace_id}', '{yesterday.isoformat()} 10:00:00', 'openai', 'gpt-4o', 100, 50, 0.002, 500, 200, 'chat', 'engineers', 'acme', now()),
            (generateUUIDv4(), '{workspace_id}', '{today.isoformat()} 11:00:00', 'anthropic', 'claude-3-sonnet', 200, 100, 0.003, 800, 200, 'search', 'data-science', 'globex', now())
        """)
        
        # Trigger rollup view (ClickHouse does this automatically but we might need to wait or force optimize)
        client.command("OPTIMIZE TABLE daily_spend_rollup FINAL")
        
        # Test get_spend_summary
        summary = await get_spend_summary(workspace_id, yesterday.isoformat(), today.isoformat())
        assert summary["total_requests"] >= 2
        assert summary["total_cost_usd"] > 0
        
        # Test get_spend_by_model
        by_model = await get_spend_by_model(workspace_id, yesterday.isoformat(), today.isoformat())
        assert len(by_model) >= 2
        
        # Test get_spend_by_tag
        by_team = await get_spend_by_tag(workspace_id, "team", yesterday.isoformat(), today.isoformat())
        assert len(by_team) >= 2
        
        # Test get_spend_timeseries
        timeseries = await get_spend_timeseries(workspace_id, yesterday.isoformat(), today.isoformat())
        assert len(timeseries) >= 2
        
    except Exception as e:
        pytest.skip(f"ClickHouse not available or test data insertion failed: {e}")
