from __future__ import annotations

import asyncio
from dataclasses import fields
from datetime import datetime
import json
import logging
import os
from pathlib import Path
from typing import AsyncIterator

from burnlens.storage.database import insert_request
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
            try:
                data = json.loads(line)
                yield self._dict_to_record(data)
            except json.JSONDecodeError as e:
                logger.warning("Skipping corrupted WAL line: %s. Error: %s", line, e)

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
        # Filter keys to match only valid fields of RequestRecord for compatibility
        valid_fields = {f.name for f in fields(RequestRecord)}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}

        if "timestamp" in filtered_data and isinstance(filtered_data["timestamp"], str):
            # Strip Z suffix if present for fromisoformat compatibility
            ts_str = filtered_data["timestamp"]
            if ts_str.endswith("Z"):
                ts_str = ts_str[:-1] + "+00:00"
            filtered_data["timestamp"] = datetime.fromisoformat(ts_str)
        return RequestRecord(**filtered_data)


class SQLitePersistenceWorker:
    """Asynchronously drains a queue and persists records to SQLite with retries."""

    def __init__(self, wal: WriteAheadLog, db_path: str, queue_size: int = 1000) -> None:
        self.wal = wal
        self.db_path = db_path
        self.queue: asyncio.Queue[RequestRecord] = asyncio.Queue(maxsize=queue_size)
        self.worker_task: asyncio.Task | None = None
        self._running = False
        self._active_record: RequestRecord | None = None

    async def start(self) -> None:
        """Start the background persistence worker loop."""
        self._running = True
        self.worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> bool:
        """Drains remaining queue items and stops cleanly.
        Returns True if all records (active + queued) were successfully persisted, or False if any insert failed.
        """
        self._running = False
        success = True

        # Stop worker task first to prevent concurrent consumption
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
            self.worker_task = None

        # Persist the record that was active when cancelled
        if self._active_record:
            try:
                await insert_request(self.db_path, self._active_record)
                self._active_record = None
            except Exception as e:
                logger.error("Failed to persist active record during shutdown: %s", e)
                success = False

        # Process remaining queue items
        while not self.queue.empty():
            try:
                record = self.queue.get_nowait()
                try:
                    await insert_request(self.db_path, record)
                except Exception as e:
                    logger.error("Failed to persist remaining queue item during shutdown: %s", e)
                    success = False
                self.queue.task_done()
            except asyncio.QueueEmpty:
                break

        return success

    async def enqueue(self, record: RequestRecord) -> None:
        """Enqueue record for DB persistence."""
        await self.queue.put(record)

    async def _worker_loop(self) -> None:
        while self._running:
            try:
                record = await self.queue.get()
                self._active_record = record
                inserted = False
                backoff = 0.1
                while not inserted and self._running:
                    try:
                        await insert_request(self.db_path, record)
                        inserted = True
                        self._active_record = None
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
