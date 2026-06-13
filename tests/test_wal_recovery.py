import pytest
from datetime import datetime, timezone
from burnlens.storage.models import RequestRecord
from burnlens.storage.wal import WriteAheadLog, recover_wal
from burnlens.storage.database import init_db

@pytest.mark.asyncio
async def test_recovery_flow(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    
    wal_path = tmp_path / "wal.jsonl"
    dlq_path = tmp_path / "dlq.jsonl"
    
    wal = WriteAheadLog(str(wal_path), str(dlq_path))
    
    # Simulate non-persisted events in WAL
    rec1 = RequestRecord(
        provider="openai", model="gpt-4o", request_path="/v1", event_id="evt-1", timestamp=datetime.now(timezone.utc)
    )
    rec2 = RequestRecord(
        provider="anthropic", model="claude-3-opus", request_path="/v1", event_id="evt-2", timestamp=datetime.now(timezone.utc)
    )
    
    await wal.append_event(rec1)
    await wal.append_event(rec2)
    
    # Run recovery
    replayed = await recover_wal(wal, db_path)
    assert replayed == 2
    
    # Verify events are in SQLite
    import aiosqlite
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM requests")
        count = (await cursor.fetchone())[0]
    assert count == 2
    
    # Verify WAL is truncated
    assert wal_path.stat().st_size == 0


@pytest.mark.asyncio
async def test_recovery_partial_failure(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    
    wal_path = tmp_path / "wal.jsonl"
    dlq_path = tmp_path / "dlq.jsonl"
    
    wal = WriteAheadLog(str(wal_path), str(dlq_path))
    
    # Simulate non-persisted events in WAL
    rec1 = RequestRecord(
        provider="openai", model="gpt-4o", request_path="/v1", event_id="evt-1", timestamp=datetime.now(timezone.utc)
    )
    rec2 = RequestRecord(
        provider="anthropic", model="claude-3-opus", request_path="/v1", event_id="evt-2", timestamp=datetime.now(timezone.utc)
    )
    
    await wal.append_event(rec1)
    await wal.append_event(rec2)
    
    # Patch insert_request to fail on the second event
    call_count = 0
    from burnlens.storage.wal import insert_request
    from unittest.mock import patch
    
    async def mock_insert_request(path, record):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("Database error on second insert")
        # Call the original insert_request
        await insert_request(path, record)
        
    with patch("burnlens.storage.wal.insert_request", side_effect=mock_insert_request):
        replayed = await recover_wal(wal, db_path)
        
    assert replayed == 1
    # Verify WAL is NOT truncated
    assert wal_path.stat().st_size > 0
    
    # Verify the first event was written to SQLite
    import aiosqlite
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT COUNT(*), model FROM requests")
        row = await cursor.fetchone()
    assert row[0] == 1
    assert row[1] == "gpt-4o"

