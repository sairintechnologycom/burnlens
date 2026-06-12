import pytest
from pathlib import Path
from datetime import datetime, timezone
from burnlens.storage.models import RequestRecord
from burnlens.storage.wal import WriteAheadLog

@pytest.mark.asyncio
async def test_wal_append_and_read(tmp_path):
    wal_path = tmp_path / "wal.jsonl"
    dlq_path = tmp_path / "dlq.jsonl"
    
    wal = WriteAheadLog(str(wal_path), str(dlq_path))
    record = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        input_tokens=100,
        output_tokens=50,
        timestamp=datetime.now(timezone.utc),
    )
    
    await wal.append_event(record)
    
    # Verify file was written
    assert wal_path.exists()
    
    # Read back and compare
    records = []
    async for r in wal.read_events():
        records.append(r)
        
    assert len(records) == 1
    assert records[0].provider == "openai"
    assert records[0].model == "gpt-4o"
    assert records[0].input_tokens == 100
    
    # Test truncate
    await wal.truncate()
    assert wal_path.stat().st_size == 0
