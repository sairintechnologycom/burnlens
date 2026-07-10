import pytest
import asyncio
from unittest.mock import patch
from burnlens.storage.wal import WriteAheadLog, SQLitePersistenceWorker
from burnlens.storage.models import RequestRecord
from burnlens.storage.database import init_db

@pytest.mark.asyncio
async def test_worker_persistence(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    
    wal_path = tmp_path / "wal.jsonl"
    dlq_path = tmp_path / "dlq.jsonl"
    
    wal = WriteAheadLog(str(wal_path), str(dlq_path))
    worker = SQLitePersistenceWorker(wal, db_path)
    
    await worker.start()
    
    record = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        input_tokens=100,
        output_tokens=50,
        event_id="evt-123",
    )
    
    await worker.enqueue(record)
    
    # Wait for queue to drain
    await asyncio.sleep(0.2)
    await worker.stop()
    
    # Verify row was inserted in SQLite
    import aiosqlite
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT model, input_tokens FROM requests WHERE event_id='evt-123'")
        row = await cursor.fetchone()
        
    assert row is not None
    assert row[0] == "gpt-4o"
    assert row[1] == 100

@pytest.mark.asyncio
async def test_worker_retry_mechanism(tmp_path):
    db_path = str(tmp_path / "test.db")
    wal_path = tmp_path / "wal.jsonl"
    dlq_path = tmp_path / "dlq.jsonl"
    
    wal = WriteAheadLog(str(wal_path), str(dlq_path))
    worker = SQLitePersistenceWorker(wal, db_path)
    
    record = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        input_tokens=100,
        output_tokens=50,
        event_id="evt-retry",
    )
    
    # Mock insert_request to raise an exception twice, then succeed
    call_count = 0
    
    async def mock_insert(path, rec):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise RuntimeError("Database temporary failure")
        return None
        
    with patch("burnlens.storage.wal.insert_request", side_effect=mock_insert):
        await worker.start()
        await worker.enqueue(record)
        
        # Allow loop to run and execute retry logic (which starts with 0.1s backoff)
        await asyncio.sleep(0.5)
        
        status = await worker.stop()
        
    assert call_count >= 3
    assert status is True

@pytest.mark.asyncio
async def test_worker_stop_drain_success(tmp_path):
    db_path = str(tmp_path / "test.db")
    wal_path = tmp_path / "wal.jsonl"
    dlq_path = tmp_path / "dlq.jsonl"
    
    wal = WriteAheadLog(str(wal_path), str(dlq_path))
    worker = SQLitePersistenceWorker(wal, db_path)
    
    records = [
        RequestRecord(provider="openai", model="gpt-4o", request_path="/v1", event_id=f"evt-stop-{i}")
        for i in range(5)
    ]
    for r in records:
        await worker.enqueue(r)
        
    persisted_ids = []
    async def mock_insert(path, rec):
        persisted_ids.append(rec.event_id)
        
    with patch("burnlens.storage.wal.insert_request", side_effect=mock_insert):
        status = await worker.stop()
        
    assert status is True
    assert len(persisted_ids) == 5
    assert set(persisted_ids) == {f"evt-stop-{i}" for i in range(5)}

@pytest.mark.asyncio
async def test_worker_stop_drain_failure(tmp_path):
    db_path = str(tmp_path / "test.db")
    wal_path = tmp_path / "wal.jsonl"
    dlq_path = tmp_path / "dlq.jsonl"
    
    wal = WriteAheadLog(str(wal_path), str(dlq_path))
    worker = SQLitePersistenceWorker(wal, db_path)
    
    record = RequestRecord(provider="openai", model="gpt-4o", request_path="/v1", event_id="evt-fail")
    await worker.enqueue(record)
    
    async def mock_insert_fail(path, rec):
        raise RuntimeError("Persistent database error")
        
    with patch("burnlens.storage.wal.insert_request", side_effect=mock_insert_fail):
        status = await worker.stop()
        
    assert status is False

@pytest.mark.asyncio
async def test_worker_active_record_on_shutdown(tmp_path):
    db_path = str(tmp_path / "test.db")
    wal_path = tmp_path / "wal.jsonl"
    dlq_path = tmp_path / "dlq.jsonl"
    
    wal = WriteAheadLog(str(wal_path), str(dlq_path))
    worker = SQLitePersistenceWorker(wal, db_path)
    
    record = RequestRecord(provider="openai", model="gpt-4o", request_path="/v1", event_id="evt-active-shutdown")
    
    started_insert = asyncio.Event()
    finish_mock = asyncio.Event()
    persisted_ids = []
    
    async def mock_insert(path, rec):
        if rec.event_id == "evt-active-shutdown":
            started_insert.set()
            await finish_mock.wait()
        persisted_ids.append(rec.event_id)
        
    with patch("burnlens.storage.wal.insert_request", side_effect=mock_insert):
        await worker.start()
        await worker.enqueue(record)
        
        await started_insert.wait()
        
        finish_mock.set()
        status = await worker.stop()
        
    assert status is True
    assert persisted_ids == ["evt-active-shutdown"]
