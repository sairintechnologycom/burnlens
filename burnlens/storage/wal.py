from __future__ import annotations

import asyncio
from dataclasses import fields
from datetime import datetime
import json
import logging
import os
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
