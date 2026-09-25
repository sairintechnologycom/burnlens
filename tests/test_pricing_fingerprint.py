from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite
import pytest

from burnlens.cost.calculator import pricing_fingerprint_for
from burnlens.storage.database import (
    init_db,
    insert_request,
    migrate_add_pricing_fingerprint,
)
from burnlens.storage.models import RequestRecord


def test_fingerprint_is_deterministic_and_unknown_stays_unknown():
    first = pricing_fingerprint_for("openai", "gpt-5", 1)
    assert first is not None and len(first) == 64
    assert first == pricing_fingerprint_for("openai", "gpt-5", 1)
    assert first != pricing_fingerprint_for("openai", "gpt-5-mini", 1)
    assert pricing_fingerprint_for("openai", "not-a-known-model") is None


@pytest.mark.asyncio
async def test_new_request_persists_version_and_fingerprint_without_changing_cost(tmp_path):
    db = str(tmp_path / "pricing.db")
    await init_db(db)
    record = RequestRecord(
        provider="openai",
        model="gpt-5",
        request_path="/v1/responses",
        timestamp=datetime.now(timezone.utc),
        input_tokens=100,
        output_tokens=20,
        cost_usd=0.123456,
        pricing_version="test-snapshot",
    )

    await insert_request(db, record)

    async with aiosqlite.connect(db) as conn:
        row = await (await conn.execute(
            "SELECT cost_usd, pricing_version, pricing_fingerprint FROM requests"
        )).fetchone()
    assert row[0] == 0.123456
    assert row[1] == "test-snapshot"
    assert row[2] == pricing_fingerprint_for(
        "openai", "gpt-5", 100, "test-snapshot"
    )


@pytest.mark.asyncio
async def test_migration_does_not_backfill_legacy_provenance(tmp_path):
    db = str(tmp_path / "legacy.db")
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "CREATE TABLE requests (id INTEGER PRIMARY KEY, pricing_version TEXT)"
        )
        await conn.execute(
            "INSERT INTO requests (pricing_version) VALUES ('historical-snapshot')"
        )
        await conn.commit()

    await migrate_add_pricing_fingerprint(db)
    await migrate_add_pricing_fingerprint(db)

    async with aiosqlite.connect(db) as conn:
        row = await (await conn.execute(
            "SELECT pricing_version, pricing_fingerprint FROM requests"
        )).fetchone()
    assert row == ("historical-snapshot", None)
