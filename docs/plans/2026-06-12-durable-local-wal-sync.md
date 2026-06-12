# Durable Local WAL & Idempotent Sync Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make BurnLens telemetry logging resilient to crashes, database locks, and network outages through a Write-Ahead Log (WAL) and idempotent background sync.

**Architecture:** Intercepted cost events are immediately written to a local append-only JSONL log file (WAL) and placed in an in-memory queue. A background worker drains the queue and writes to SQLite (using idempotent UUIDv7 event IDs to prevent duplicate inserts). On startup, a recovery worker replays any outstanding WAL entries. A doctor diagnostic checks WAL health and recovers malformed lines to a Dead Letter Queue (DLQ).

**Tech Stack:** Python 3.11+, aiosqlite, FastAPI, Typer, pytest, pytest-asyncio.

---

### Task 1: Generate Identifiers with UUIDv7

Generate RFC 9562-compatible UUIDv7 strings to ensure chronological sorting and idempotency.

**Files:**
- Modify: `burnlens/storage/models.py`
- Test: `tests/test_wal_uuid.py`

**Step 1: Write the failing test**

Create `tests/test_wal_uuid.py`:
```python
import pytest
from burnlens.storage.models import uuid7

def test_uuid7_sorting_and_format():
    id1 = uuid7()
    id2 = uuid7()
    
    # Verify format matches standard UUID (8-4-4-4-12 hex chars)
    parts1 = id1.split("-")
    assert len(parts1) == 5
    assert len(parts1[0]) == 8
    assert len(parts1[1]) == 4
    assert len(parts1[2]) == 4
    assert len(parts1[3]) == 4
    assert len(parts1[4]) == 12
    
    # Version should be 7 (first char of 3rd part)
    assert parts1[2][0] == "7"
    
    # Variant should be RFC 9562 variant 2 (top bits 10, i.e., 8, 9, a, or b)
    assert parts1[3][0] in {"8", "9", "a", "b"}
    
    # Chronological sort order: id2 should be greater than id1
    assert id2 > id1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_wal_uuid.py`
Expected: FAIL (ImportError: cannot import name 'uuid7' from 'burnlens.storage.models')

**Step 3: Write minimal implementation**

Add to `burnlens/storage/models.py`:
```python
import os
import time

def uuid7() -> str:
    """Generate an RFC 9562-compatible UUIDv7 string."""
    ts_ms = int(time.time() * 1000)
    rand_bytes = bytearray(os.urandom(16))
    
    # Write timestamp to first 6 bytes
    rand_bytes[0] = (ts_ms >> 40) & 0xFF
    rand_bytes[1] = (ts_ms >> 32) & 0xFF
    rand_bytes[2] = (ts_ms >> 24) & 0xFF
    rand_bytes[3] = (ts_ms >> 16) & 0xFF
    rand_bytes[4] = (ts_ms >> 8) & 0xFF
    rand_bytes[5] = ts_ms & 0xFF
    
    # Set version to 7 (bits 4-7 of byte 6)
    rand_bytes[6] = (rand_bytes[6] & 0x0F) | 0x70
    
    # Set variant to 2 (bits 6-7 of byte 8)
    rand_bytes[8] = (rand_bytes[8] & 0x3F) | 0x80
    
    h = rand_bytes.hex()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
```

And update `to_event` in `RequestRecord` in `burnlens/storage/models.py` to use `uuid7()` instead of `uuid.uuid4()`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_wal_uuid.py`
Expected: PASS

**Step 5: Commit**

```bash
git add burnlens/storage/models.py tests/test_wal_uuid.py
git commit -m "feat: add UUIDv7 generator and update models"
```

---

### Task 2: Append-Only Write-Ahead Log (WAL)

Implement `WriteAheadLog` to handle durable logging to a local JSONL file.

**Files:**
- Create: `burnlens/storage/wal.py`
- Test: `tests/test_wal_log.py`

**Step 1: Write the failing test**

Create `tests/test_wal_log.py`:
```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_wal_log.py`
Expected: FAIL (ModuleNotFoundError: No module named 'burnlens.storage.wal')

**Step 3: Write minimal implementation**

Create `burnlens/storage/wal.py`:
```python
from __future__ import annotations

import os
import json
import logging
import asyncio
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator
from burnlens.storage.models import RequestRecord

logger = logging.getLogger(__name__)

class WriteAheadLog:
    """Durable append-only local WAL for telemetry events."""
    
    def __init__(self, wal_path: str, dlq_path: str) -> None:
        self.wal_path = Path(wal_path)
        self.dlq_path = Path(dlq_path)
        self.lock = asyncio.Lock()

    async def append_event(self, record: RequestRecord) -> None:
        """Append a record to the WAL file in a thread-safe / crash-resistant way."""
        self.wal_path.parent.mkdir(parents=True, exist_ok=True)
        record_dict = self._record_to_dict(record)
        line = json.dumps(record_dict) + "\n"
        
        async with self.lock:
            # Run blocking file operations in thread pool
            await asyncio.to_thread(self._sync_append, line)

    def _sync_append(self, line: str) -> None:
        with open(self.wal_path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass  # Ignore sync errors on filesystems that don't support it

    async def read_events(self) -> AsyncIterator[RequestRecord]:
        """Read and parse records from the WAL file."""
        if not self.wal_path.exists():
            return
            
        # Read lines asynchronously
        lines = await asyncio.to_thread(self._read_lines)
        for line in lines:
            if not line.strip():
                continue
            data = json.loads(line)
            yield self._dict_to_record(data)

    def _read_lines(self) -> list[str]:
        with open(self.wal_path, "r", encoding="utf-8") as f:
            return f.readlines()

    async def truncate(self) -> None:
        """Empty the WAL file safely."""
        async with self.lock:
            await asyncio.to_thread(self._sync_truncate)

    def _sync_truncate(self) -> None:
        if self.wal_path.exists():
            with open(self.wal_path, "w", encoding="utf-8") as f:
                f.truncate(0)

    def _record_to_dict(self, record: RequestRecord) -> dict:
        data = {}
        for k, v in record.__dict__.items():
            if isinstance(v, datetime):
                data[k] = v.isoformat()
            else:
                data[k] = v
        return data

    def _dict_to_record(self, data: dict) -> RequestRecord:
        if "timestamp" in data and isinstance(data["timestamp"], str):
            # Strip Z suffix if present for fromisoformat compatibility
            ts_str = data["timestamp"]
            if ts_str.endswith("Z"):
                ts_str = ts_str[:-1] + "+00:00"
            data["timestamp"] = datetime.fromisoformat(ts_str)
        return RequestRecord(**data)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_wal_log.py`
Expected: PASS

**Step 5: Commit**

```bash
git add burnlens/storage/wal.py tests/test_wal_log.py
git commit -m "feat: implement WriteAheadLog class"
```

---

### Task 3: SQLite Persistence Worker

Add the async background queue and persistence worker for SQLite writes.

**Files:**
- Modify: `burnlens/storage/wal.py`
- Test: `tests/test_wal_worker.py`

**Step 1: Write the failing test**

Create `tests/test_wal_worker.py`:
```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_wal_worker.py`
Expected: FAIL (ImportError: cannot import name 'SQLitePersistenceWorker' from 'burnlens.storage.wal')

**Step 3: Write minimal implementation**

Add to `burnlens/storage/wal.py`:
```python
from burnlens.storage.database import insert_request

class SQLitePersistenceWorker:
    """Asynchronously drains a queue and persists records to SQLite with retries."""
    
    def __init__(self, wal: WriteAheadLog, db_path: str, queue_size: int = 1000) -> None:
        self.wal = wal
        self.db_path = db_path
        self.queue: asyncio.Queue[RequestRecord] = asyncio.Queue(maxsize=queue_size)
        self.worker_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the background persistence worker loop."""
        self._running = True
        self.worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        """Drains remaining queue items and stops cleanly."""
        self._running = False
        
        # Process remaining items
        while not self.queue.empty():
            try:
                record = self.queue.get_nowait()
                await insert_request(self.db_path, record)
                self.queue.task_done()
            except asyncio.QueueEmpty:
                break
            except Exception as e:
                logger.error("Failed to persist remaining queue item: %s", e)

        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
            self.worker_task = None

    async def enqueue(self, record: RequestRecord) -> None:
        """Enqueue record for DB persistence."""
        await self.queue.put(record)

    async def _worker_loop(self) -> None:
        while self._running:
            try:
                record = await self.queue.get()
                inserted = False
                backoff = 0.1
                while not inserted and self._running:
                    try:
                        await insert_request(self.db_path, record)
                        inserted = True
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.warning("SQLite insert failed, retrying in %.2fs: %s", backoff, e)
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 5.0)
                self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("SQLite Persistence Worker loop encountered error: %s", e)
                await asyncio.sleep(0.5)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_wal_worker.py`
Expected: PASS

**Step 5: Commit**

```bash
git add burnlens/storage/wal.py tests/test_wal_worker.py
git commit -m "feat: implement SQLitePersistenceWorker"
```

---

### Task 4: WAL Recovery on Startup

Implement the recovery mechanism that replays existing WAL entries into SQLite at startup, then truncates the WAL.

**Files:**
- Modify: `burnlens/storage/wal.py`
- Test: `tests/test_wal_recovery.py`

**Step 1: Write the failing test**

Create `tests/test_wal_recovery.py`:
```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_wal_recovery.py`
Expected: FAIL (ImportError: cannot import name 'recover_wal' from 'burnlens.storage.wal')

**Step 3: Write minimal implementation**

Add to `burnlens/storage/wal.py`:
```python
async def recover_wal(wal: WriteAheadLog, db_path: str) -> int:
    """Replay outstanding WAL events into SQLite and truncate WAL."""
    count = 0
    if not wal.wal_path.exists():
        return count
        
    try:
        async for record in wal.read_events():
            await insert_request(db_path, record)
            count += 1
            
        await wal.truncate()
        logger.info("WAL recovery completed: replayed %d events", count)
    except Exception as e:
        logger.error("Failed to recover WAL: %s", e)
        
    return count
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_wal_recovery.py`
Expected: PASS

**Step 5: Commit**

```bash
git add burnlens/storage/wal.py tests/test_wal_recovery.py
git commit -m "feat: implement recover_wal recovery helper"
```

---

### Task 5: Integrate Config & Server Lifespan

Add WAL paths to the configuration and initialize/manage the WAL and worker lifespan in the FastAPI server.

**Files:**
- Modify: `burnlens/config.py`
- Modify: `burnlens/proxy/server.py`
- Modify: `burnlens/proxy/interceptor.py`
- Test: `tests/test_wal_integration.py`

**Step 1: Write the failing test**

Create `tests/test_wal_integration.py` to check that starting the server runs recovery and enqueues proxy calls to WAL + database:
```python
import pytest
import asyncio
from fastapi.testclient import TestClient
from burnlens.config import BurnLensConfig
from burnlens.proxy.server import get_app
from burnlens.storage.database import init_db

@pytest.mark.asyncio
async def test_server_lifespan_wal(tmp_path):
    db_path = str(tmp_path / "test.db")
    wal_path = str(tmp_path / "wal.jsonl")
    dlq_path = str(tmp_path / "dlq.jsonl")
    
    config = BurnLensConfig(
        db_path=db_path,
    )
    # Inject WAL fields dynamically or via subclassing if not configured yet
    config.wal_path = wal_path
    config.dlq_path = dlq_path
    
    app = get_app(config)
    
    # We use TestClient as a context manager to trigger lifespan startup and shutdown
    with TestClient(app) as client:
        # Check that WAL and worker were mounted on app state
        assert hasattr(app.state, "wal")
        assert hasattr(app.state, "wal_worker")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_wal_integration.py`
Expected: FAIL (AssertionError: app.state does not have "wal" or "wal_worker")

**Step 3: Write minimal implementation**

1. Modify `burnlens/config.py` to add `wal_path` and `dlq_path` to `BurnLensConfig`:
```python
# In burnlens/config.py, inside @dataclass class BurnLensConfig:
    db_path: str = str(Path.home() / ".burnlens" / "burnlens.db")
    wal_path: str = str(Path.home() / ".burnlens" / "wal.jsonl")
    dlq_path: str = str(Path.home() / ".burnlens" / "wal_dlq.jsonl")
```

2. Modify `burnlens/proxy/server.py` to start the worker, run recovery, and shut them down:
```python
# In burnlens/proxy/server.py:
# Add imports:
from burnlens.storage.wal import WriteAheadLog, SQLitePersistenceWorker, recover_wal

# In @asynccontextmanager async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Init DB (creates tables if needed)
        await init_db(config.db_path)
        logger.info("Database ready at %s", config.db_path)
        
        # Initialize WAL and Worker
        wal = WriteAheadLog(config.wal_path, config.dlq_path)
        app.state.wal = wal
        
        # Perform WAL Recovery before starting worker
        await recover_wal(wal, config.db_path)
        
        worker = SQLitePersistenceWorker(wal, config.db_path)
        app.state.wal_worker = worker
        await worker.start()
        logger.info("WAL and SQLite persistence worker active")
        
        ...
        yield
        
        # Shut down worker cleanly
        await worker.stop()
        logger.info("SQLite persistence worker stopped")
        
        # Final WAL truncate if clean shutdown
        await wal.truncate()
```

3. Modify `burnlens/proxy/interceptor.py` to use `app.state.wal` and `app.state.wal_worker` instead of `asyncio.create_task(_log_record(db_path, record))`:
```python
# In burnlens/proxy/interceptor.py:
# Modify handle_request and _handle_non_streaming / _handle_streaming to receive the app state or wal/worker references.
# Alternatively, since handle_request is called in server.py, we can pass `app.state.wal` and `app.state.wal_worker` into handle_request!
```

Let's modify `handle_request` in `burnlens/proxy/interceptor.py` signature:
```python
async def handle_request(
    client: httpx.AsyncClient,
    provider: Provider,
    path: str,
    method: str,
    headers: dict[str, str],
    body_bytes: bytes,
    query_string: str,
    db_path: str,
    alert_engine: "AlertEngine | None" = None,
    customer_budgets: "CustomerBudgetsConfig | None" = None,
    api_key_budgets: "ApiKeyBudgetsConfig | None" = None,
    config: "BurnLensConfig | None" = None,
    wal: "WriteAheadLog | None" = None,
    worker: "SQLitePersistenceWorker | None" = None,
) -> tuple[int, dict[str, str], bytes | None, AsyncIterator[bytes] | None]:
```

And update `server.py` when it calls `handle_request`:
```python
            status, resp_headers, body, stream = await handle_request(
                client=_http_client,
                provider=provider,
                path=f"/proxy/{path}",
                method=request.method,
                headers=headers,
                body_bytes=body_bytes,
                query_string=query_string,
                db_path=_config.db_path,
                alert_engine=_alert_engine,
                customer_budgets=_config.alerts.customer_budgets,
                api_key_budgets=_config.alerts.api_key_budgets,
                config=_config,
                wal=request.app.state.wal if hasattr(request.app.state, "wal") else None,
                worker=request.app.state.wal_worker if hasattr(request.app.state, "wal_worker") else None,
            )
```

In `interceptor.py`, replace:
```python
    asyncio.create_task(_log_record(db_path, record))
```
with WAL-first logging:
```python
    if wal is not None and worker is not None:
        async def _log_via_wal():
            try:
                await wal.append_event(record)
                await worker.enqueue(record)
            except Exception as e:
                logger.error("WAL append/enqueue failed: %s", e)
                # Fallback to direct insertion so we fail open
                asyncio.create_task(_log_record(db_path, record))
        asyncio.create_task(_log_via_wal())
    else:
        asyncio.create_task(_log_record(db_path, record))
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_wal_integration.py`
Expected: PASS

**Step 5: Commit**

```bash
git add burnlens/config.py burnlens/proxy/server.py burnlens/proxy/interceptor.py tests/test_wal_integration.py
git commit -m "feat: integrate WAL and persistence worker into FastAPI lifecycle"
```

---

### Task 6: WAL Doctor and DLQ Replaying

Add health checks, repair capabilities, and DLQ replaying utilities to CLI and diagnostics.

**Files:**
- Modify: `burnlens/doctor.py`
- Modify: `burnlens/cli.py`
- Modify: `burnlens/storage/wal.py`
- Test: `tests/test_wal_doctor.py`

**Step 1: Write the failing test**

Create `tests/test_wal_doctor.py`:
```python
import pytest
import json
from pathlib import Path
from burnlens.doctor import check_wal, run_all_checks
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_wal_doctor.py`
Expected: FAIL (ImportError: cannot import name 'check_wal' from 'burnlens.doctor')

**Step 3: Write minimal implementation**

1. Add `check_wal` to `burnlens/doctor.py`:
```python
# In burnlens/doctor.py:

def check_wal(wal_path: str, dlq_path: str) -> CheckResult:
    """Verify write-ahead log (WAL) health and check for corrupt entries."""
    path = Path(wal_path)
    if not path.exists():
        return CheckResult("pass", "WAL", "WAL file does not exist (clean state)")
        
    corrupt_count = 0
    total_count = 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                total_count += 1
                try:
                    json.loads(line)
                except json.JSONDecodeError:
                    corrupt_count += 1
                    
        if corrupt_count == 0:
            return CheckResult("pass", "WAL", f"WAL file OK — {total_count} records")
        else:
            return CheckResult(
                "warn", "WAL",
                f"WAL file has {corrupt_count} corrupt entries out of {total_count} total entries",
                fix="Run `burnlens wal doctor --repair` to move corrupt records to DLQ"
            )
    except Exception as exc:
        return CheckResult("fail", "WAL", f"Cannot read WAL file: {exc}")
```
And add `check_wal` to `run_all_checks` in `burnlens/doctor.py`.

2. Add `repair_wal` and `replay_dlq` to `burnlens/storage/wal.py`:
```python
# In burnlens/storage/wal.py:

def repair_wal(wal_path: str, dlq_path: str) -> tuple[int, int]:
    """Recover valid entries from WAL and isolate corrupt ones into the DLQ.
    
    Returns (repaired_count, corrupt_count).
    """
    wal_file = Path(wal_path)
    dlq_file = Path(dlq_path)
    if not wal_file.exists():
        return 0, 0
        
    valid_lines = []
    corrupt_lines = []
    
    with open(wal_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                json.loads(line)
                valid_lines.append(line)
            except json.JSONDecodeError:
                corrupt_lines.append(line)
                
    if corrupt_lines:
        dlq_file.parent.mkdir(parents=True, exist_ok=True)
        # Write corrupt lines to DLQ
        with open(dlq_file, "a", encoding="utf-8") as df:
            for line in corrupt_lines:
                df.write(line)
                
    # Rewrite WAL with only valid lines
    with open(wal_file, "w", encoding="utf-8") as wf:
        for line in valid_lines:
            wf.write(line)
            
    return len(valid_lines), len(corrupt_lines)


async def replay_dlq(db_path: str, dlq_path: str) -> tuple[int, int]:
    """Parse and insert DLQ records into SQLite.
    
    Returns (replayed_count, failed_count).
    """
    dlq_file = Path(dlq_path)
    if not dlq_file.exists():
        return 0, 0
        
    replayed = 0
    failed = 0
    remaining_lines = []
    
    with open(dlq_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                # Parse record
                if "timestamp" in data and isinstance(data["timestamp"], str):
                    ts_str = data["timestamp"]
                    if ts_str.endswith("Z"):
                        ts_str = ts_str[:-1] + "+00:00"
                    data["timestamp"] = datetime.fromisoformat(ts_str)
                record = RequestRecord(**data)
                await insert_request(db_path, record)
                replayed += 1
            except Exception as e:
                logger.error("Failed to replay DLQ line: %s", e)
                remaining_lines.append(line)
                failed += 1
                
    # Rewrite DLQ with only the failed/unparsed lines
    if remaining_lines:
        with open(dlq_file, "w", encoding="utf-8") as f:
            for line in remaining_lines:
                f.write(line)
    else:
        if dlq_file.exists():
            dlq_file.unlink()
            
    return replayed, failed
```

3. Expose new CLI commands in `burnlens/cli.py` to allow users to view/replay DLQs and repair WALs:
Create a Typer sub-group `wal_app = typer.Typer(help="Manage Write-Ahead Log (WAL) and DLQ")` in `cli.py`:
```python
# In burnlens/cli.py:

wal_app = typer.Typer(help="Manage Write-Ahead Log (WAL) and DLQ")
app.add_typer(wal_app, name="wal")

@wal_app.command("doctor")
def wal_doctor(
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    repair: bool = typer.Option(False, "--repair", help="Automatically repair corrupt entries by moving them to the DLQ"),
) -> None:
    """Check the health of the WAL file and optionally repair it."""
    cfg = load_config(config)
    if repair:
        from burnlens.storage.wal import repair_wal
        repaired, corrupt = repair_wal(cfg.wal_path, cfg.dlq_path)
        console.print(f"[green]WAL Repair completed.[/green] Repaired: {repaired}, isolated: {corrupt} to {cfg.dlq_path}")
    else:
        from burnlens.doctor import check_wal
        res = check_wal(cfg.wal_path, cfg.dlq_path)
        if res.status == "pass":
            console.print(f"[green]PASS:[/green] {res.message}")
        else:
            console.print(f"[yellow]WARN:[/yellow] {res.message}")
            if res.fix:
                console.print(f"  Fix: [cyan]{res.fix}[/cyan]")


@wal_app.command("replay-dlq")
def wal_replay_dlq(
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
) -> None:
    """Attempt to parse and replay the Dead Letter Queue (DLQ) records into SQLite."""
    cfg = load_config(config)
    from burnlens.storage.wal import replay_dlq
    replayed, failed = asyncio.run(replay_dlq(cfg.db_path, cfg.dlq_path))
    if replayed > 0 or failed > 0:
        console.print(f"[green]DLQ Replayed.[/green] Successfully replayed: {replayed}, failed: {failed}")
    else:
        console.print("[dim]DLQ file is empty or does not exist.[/dim]")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_wal_doctor.py`
Expected: PASS

**Step 5: Commit**

```bash
git add burnlens/doctor.py burnlens/cli.py burnlens/storage/wal.py tests/test_wal_doctor.py
git commit -m "feat: add WAL doctor checks, repair mechanisms, and replay-dlq command"
```
