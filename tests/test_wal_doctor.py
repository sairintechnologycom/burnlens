import pytest
from burnlens.doctor import check_wal
from burnlens.storage.wal import repair_wal, replay_dlq
from burnlens.storage.database import init_db

@pytest.mark.asyncio
async def test_wal_doctor_and_dlq(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    
    wal_path = tmp_path / "wal.jsonl"
    dlq_path = tmp_path / "dlq.jsonl"
    
    # Write a corrupt file (one valid JSON, one corrupt line)
    with open(wal_path, "w", encoding="utf-8") as f:
        f.write('{"provider": "openai", "model": "gpt-4o", "input_tokens": 100}\n')
        f.write('{"provider": "anthropic", "model": \n')  # Corrupt JSON
        
    # Check doctor diagnostics
    result = check_wal(str(wal_path), str(dlq_path))
    assert result.status == "warn"
    assert "corrupt" in result.message
    
    # Repair WAL
    repaired, corrupt = repair_wal(str(wal_path), str(dlq_path))
    assert repaired == 1
    assert corrupt == 1
    
    # Verify DLQ contains the corrupt line
    assert dlq_path.exists()
    with open(dlq_path, "r", encoding="utf-8") as df:
        lines = df.readlines()
    assert len(lines) == 1
    assert "anthropic" in lines[0]


@pytest.mark.asyncio
async def test_wal_replay_dlq(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    
    dlq_path = tmp_path / "dlq.jsonl"
    
    # Write one valid JSON line (repaired/fixed by user) and one corrupt line
    with open(dlq_path, "w", encoding="utf-8") as f:
        f.write('{"provider": "openai", "model": "gpt-4o", "request_path": "/v1", "input_tokens": 150}\n')
        f.write('{"provider": "anthropic", "model": \n')
        
    replayed, remaining = await replay_dlq(str(dlq_path), db_path)
    assert replayed == 1
    assert remaining == 1
    
    # Verify DB has 1 request with 150 tokens
    import aiosqlite
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT COUNT(*), input_tokens FROM requests")
        row = await cursor.fetchone()
    assert row[0] == 1
    assert row[1] == 150
    
    # Verify DLQ contains only the corrupt line now
    with open(dlq_path, "r", encoding="utf-8") as df:
        lines = df.readlines()
    assert len(lines) == 1
    assert "anthropic" in lines[0]

