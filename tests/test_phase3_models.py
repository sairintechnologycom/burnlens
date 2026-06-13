import pytest
from datetime import datetime, timezone
from burnlens.storage.models import RequestRecord
from burnlens.storage.database import init_db, insert_request, aiosqlite

@pytest.mark.asyncio
async def test_ttft_field_in_models_and_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    
    # 1. Test model instantiation and mapping
    record = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        timestamp=datetime.now(timezone.utc),
        ttft_ms=120.5
    )
    
    assert record.ttft_ms == 120.5
    event = record.to_event()
    assert event.ttft_ms == 120.5
    
    record2 = RequestRecord.from_event(event)
    assert record2.ttft_ms == 120.5

    # 2. Test database migration and persistence
    await init_db(db_path)
    
    # Verify the ttft_ms column exists in the requests table
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA table_info(requests)")
        columns = {row[1] for row in await cursor.fetchall()}
        assert "ttft_ms" in columns

    # Insert request and read it back
    row_id = await insert_request(db_path, record)
    assert row_id > 0
    
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM requests WHERE id = ?", (row_id,))
        row = await cursor.fetchone()
        assert row["ttft_ms"] == 120.5
