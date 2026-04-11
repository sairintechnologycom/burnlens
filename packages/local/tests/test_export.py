"""Tests for the CSV export feature."""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from burnlens.export import CSV_COLUMNS, export_to_csv
from burnlens.storage.database import get_requests_for_export, init_db, insert_request
from burnlens.storage.models import RequestRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record(
    provider: str = "openai",
    model: str = "gpt-4o",
    cost_usd: float = 0.01,
    tags: dict | None = None,
    timestamp: datetime | None = None,
) -> RequestRecord:
    return RequestRecord(
        provider=provider,
        model=model,
        request_path="/v1/chat/completions",
        input_tokens=100,
        output_tokens=50,
        cost_usd=cost_usd,
        tags=tags or {},
        timestamp=timestamp or datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_creates_file(initialized_db: str, tmp_path: Path) -> None:
    """export_to_csv creates a CSV file on disk."""
    await insert_request(initialized_db, _record())
    rows = await get_requests_for_export(initialized_db, days=7)
    out = tmp_path / "out.csv"

    export_to_csv(rows, out)

    assert out.exists()
    assert out.stat().st_size > 0


@pytest.mark.asyncio
async def test_export_correct_columns(initialized_db: str, tmp_path: Path) -> None:
    """CSV header matches the specified column order."""
    await insert_request(initialized_db, _record(tags={"feature": "chat", "team": "backend"}))
    rows = await get_requests_for_export(initialized_db, days=7)
    out = tmp_path / "out.csv"

    export_to_csv(rows, out)

    with open(out) as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == CSV_COLUMNS
        data = list(reader)
        assert len(data) == 1
        assert data[0]["feature"] == "chat"
        assert data[0]["team"] == "backend"
        assert data[0]["provider"] == "openai"


@pytest.mark.asyncio
async def test_export_filter_by_team(initialized_db: str, tmp_path: Path) -> None:
    """Filtering by team returns only matching rows."""
    await insert_request(initialized_db, _record(tags={"team": "backend"}))
    await insert_request(initialized_db, _record(tags={"team": "frontend"}))
    await insert_request(initialized_db, _record(tags={}))

    rows = await get_requests_for_export(initialized_db, days=7, team="backend")

    assert len(rows) == 1
    out = tmp_path / "out.csv"
    export_to_csv(rows, out)

    with open(out) as f:
        data = list(csv.DictReader(f))
        assert len(data) == 1
        assert data[0]["team"] == "backend"


@pytest.mark.asyncio
async def test_export_filter_by_days(initialized_db: str, tmp_path: Path) -> None:
    """Only requests within the day window are exported."""
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    old = datetime.now(timezone.utc) - timedelta(days=15)

    await insert_request(initialized_db, _record(timestamp=recent))
    await insert_request(initialized_db, _record(timestamp=old))

    rows = await get_requests_for_export(initialized_db, days=7)

    assert len(rows) == 1


@pytest.mark.asyncio
async def test_export_empty_result_no_crash(initialized_db: str, tmp_path: Path) -> None:
    """Empty result set produces a CSV with only a header and no errors."""
    rows = await get_requests_for_export(initialized_db, days=7)
    assert rows == []

    out = tmp_path / "out.csv"
    export_to_csv(rows, out)

    assert out.exists()
    with open(out) as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == CSV_COLUMNS
        assert list(reader) == []
