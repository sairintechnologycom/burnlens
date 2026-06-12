import pytest
import asyncio
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
