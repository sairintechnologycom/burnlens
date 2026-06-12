import pytest
import json
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

@pytest.mark.asyncio
async def test_wal_non_existent(tmp_path):
    wal_path = tmp_path / "non_existent_wal.jsonl"
    dlq_path = tmp_path / "dlq.jsonl"
    wal = WriteAheadLog(str(wal_path), str(dlq_path))
    
    records = []
    async for r in wal.read_events():
        records.append(r)
    assert len(records) == 0

@pytest.mark.asyncio
async def test_wal_empty_and_whitespace_lines(tmp_path):
    wal_path = tmp_path / "wal.jsonl"
    dlq_path = tmp_path / "dlq.jsonl"
    
    # Write some empty and whitespace-only lines manually
    wal_path.write_text("\n\n   \n\n", encoding="utf-8")
    
    wal = WriteAheadLog(str(wal_path), str(dlq_path))
    records = []
    async for r in wal.read_events():
        records.append(r)
    assert len(records) == 0

@pytest.mark.asyncio
async def test_wal_corrupted_json_lines(tmp_path):
    wal_path = tmp_path / "wal.jsonl"
    dlq_path = tmp_path / "dlq.jsonl"
    
    # Write a valid line, a corrupted line, and another valid line
    valid_data_1 = {
        "provider": "openai",
        "model": "gpt-4o",
        "request_path": "/v1/chat/completions",
        "input_tokens": 10,
    }
    corrupt_line = "{invalid-json: \n"
    valid_data_2 = {
        "provider": "anthropic",
        "model": "claude-3-opus",
        "request_path": "/v1/messages",
        "input_tokens": 20,
    }
    
    with open(wal_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(valid_data_1) + "\n")
        f.write(corrupt_line + "\n")
        f.write(json.dumps(valid_data_2) + "\n")
        
    wal = WriteAheadLog(str(wal_path), str(dlq_path))
    records = []
    async for r in wal.read_events():
        records.append(r)
        
    assert len(records) == 2
    assert records[0].provider == "openai"
    assert records[1].provider == "anthropic"

@pytest.mark.asyncio
async def test_wal_schema_evolution_keys(tmp_path):
    wal_path = tmp_path / "wal.jsonl"
    dlq_path = tmp_path / "dlq.jsonl"
    
    # Write record with extra keys that are not present in RequestRecord definition
    data = {
        "provider": "openai",
        "model": "gpt-4o",
        "request_path": "/v1/chat/completions",
        "input_tokens": 100,
        "some_new_future_field": "some-value",
        "another_extra_field": 12345,
    }
    
    wal_path.write_text(json.dumps(data) + "\n", encoding="utf-8")
    
    wal = WriteAheadLog(str(wal_path), str(dlq_path))
    records = []
    async for r in wal.read_events():
        records.append(r)
        
    assert len(records) == 1
    assert records[0].provider == "openai"
    assert records[0].model == "gpt-4o"
    assert not hasattr(records[0], "some_new_future_field")
