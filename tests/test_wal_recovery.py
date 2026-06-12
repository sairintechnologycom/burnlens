import pytest
from pathlib import Path
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
