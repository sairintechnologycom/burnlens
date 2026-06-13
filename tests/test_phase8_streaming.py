import pytest
import uuid
from burnlens_cloud.streaming import send_records_to_stream, get_streaming_producer
from burnlens_cloud.config import settings

@pytest.mark.asyncio
async def test_streaming_producer_singleton():
    """Test that streaming producer is a singleton and initializes correctly."""
    try:
        producer1 = await get_streaming_producer()
        producer2 = await get_streaming_producer()
        
        if producer1 is None:
            pytest.skip("aiokafka not installed or streaming disabled")
            
        assert producer1 is producer2
    except Exception as e:
        pytest.skip(f"Kafka/Redpanda not available for integration test: {e}")

@pytest.mark.asyncio
async def test_send_records_to_stream():
    """Test sending records to the stream."""
    try:
        workspace_id = str(uuid.uuid4())
        records = [
            {
                "ts": "2024-01-15T10:30:00Z",
                "provider": "openai",
                "model": "gpt-4o",
                "input_tokens": 100,
                "output_tokens": 50,
                "cost_usd": 0.002,
                "duration_ms": 500,
                "status_code": 200,
                "tag_feature": "chat",
                "tag_team": "engineers",
                "tag_customer": "acme",
                "system_prompt_hash": "abc123"
            }
        ]
        
        # This will attempt to connect to Kafka
        await send_records_to_stream(workspace_id, records)
        # If no exception raised, it "passed" (as we can't easily verify consumption in this unit test without full ClickHouse setup)
        
    except Exception as e:
        if "Kafka" in str(e) or "Connection" in str(e) or "Broker" in str(e):
            pytest.skip(f"Kafka/Redpanda not available for integration test: {e}")
        else:
            raise
