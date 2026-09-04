"""BLU-815 requested vs effective model provenance."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import aiosqlite
import pytest
from typer.testing import CliRunner

from burnlens.cli import app
from burnlens.config import BurnLensConfig
from burnlens.cloud.sync import _row_to_payload, _sanitize_record
from burnlens.proxy.interceptor import _apply_model_provenance
from burnlens.storage.database import (
    get_routing_events,
    init_db,
    insert_request,
    migrate_add_requested_model,
)
from burnlens.storage.models import RequestRecord

runner = CliRunner()


def _record(**over) -> RequestRecord:
    base = dict(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        timestamp=datetime.now(timezone.utc),
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.001,
        duration_ms=80,
    )
    base.update(over)
    return RequestRecord(**base)


@pytest.mark.asyncio
async def test_no_routing_requested_equals_effective(tmp_path):
    db = str(tmp_path / "p.db")
    await init_db(db)
    rec = _record(model="gpt-4o", requested_model="gpt-4o", routed_model="gpt-4o")
    await insert_request(db, rec)
    async with aiosqlite.connect(db) as conn:
        conn.row_factory = aiosqlite.Row
        row = await (await conn.execute(
            "SELECT model, requested_model, routed_model, downgrade_reason FROM requests"
        )).fetchone()
    assert row["requested_model"] == row["model"] == "gpt-4o"
    assert row["downgrade_reason"] is None


@pytest.mark.asyncio
async def test_routed_request_keeps_requested_and_effective(tmp_path):
    db = str(tmp_path / "p.db")
    await init_db(db)
    rec = _record(
        model="gpt-4o-mini",
        requested_model="gpt-4o",
        routed_model="gpt-4o-mini",
        downgrade_reason="budget_pct",
    )
    await insert_request(db, rec)
    async with aiosqlite.connect(db) as conn:
        conn.row_factory = aiosqlite.Row
        row = await (await conn.execute(
            "SELECT model, requested_model, routed_model, downgrade_reason FROM requests"
        )).fetchone()
    assert row["requested_model"] == "gpt-4o"
    assert row["model"] == "gpt-4o-mini"
    assert row["requested_model"] != row["model"]
    assert row["routed_model"] == "gpt-4o-mini"
    assert row["downgrade_reason"] == "budget_pct"


@pytest.mark.asyncio
async def test_historic_ambiguous_row_is_not_fabricated(tmp_path):
    db = str(tmp_path / "p.db")
    await init_db(db)
    async with aiosqlite.connect(db) as conn:
        await conn.execute("ALTER TABLE requests DROP COLUMN requested_model")
        await conn.execute(
            "INSERT INTO requests (timestamp, provider, model, request_path, "
            "routed_model, downgrade_reason, cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                "openai",
                "gpt-4o-mini",
                "/v1/chat/completions",
                "gpt-4o-mini",
                "budget_pct",
                0.001,
            ),
        )
        await conn.execute(
            "INSERT INTO requests (timestamp, provider, model, request_path, "
            "cost_usd) VALUES (?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                "openai",
                "gpt-4o",
                "/v1/chat/completions",
                0.002,
            ),
        )
        await conn.commit()

    await migrate_add_requested_model(db)

    async with aiosqlite.connect(db) as conn:
        conn.row_factory = aiosqlite.Row
        rows = await (await conn.execute(
            "SELECT model, requested_model, downgrade_reason FROM requests ORDER BY cost_usd"
        )).fetchall()

    routed = next(r for r in rows if r["downgrade_reason"] == "budget_pct")
    plain = next(r for r in rows if r["downgrade_reason"] is None)
    assert routed["requested_model"] is None
    assert plain["requested_model"] == "gpt-4o"


def test_apply_provenance_helper_no_decision():
    rec = _record(model="gpt-4o")
    _apply_model_provenance(
        rec, requested_model="gpt-4o", effective_model="gpt-4o", decision=None
    )
    assert rec.requested_model == rec.model == rec.routed_model == "gpt-4o"
    assert rec.downgrade_reason is None


def test_cli_routing_labels_requested_and_effective(tmp_path):
    db = str(tmp_path / "p.db")
    import asyncio
    asyncio.run(init_db(db))
    asyncio.run(insert_request(
        db,
        _record(
            model="gpt-4o-mini",
            requested_model="gpt-4o",
            routed_model="gpt-4o-mini",
            downgrade_reason="budget_pct",
        ),
    ))
    asyncio.run(insert_request(
        db,
        _record(
            model="gpt-4o-mini",
            requested_model=None,
            routed_model="gpt-4o-mini",
            downgrade_reason="budget_usd",
            cost_usd=0.002,
        ),
    ))
    events = asyncio.run(get_routing_events(db))
    assert len(events) == 2
    known = next(e for e in events if e["requested_model"] == "gpt-4o")
    historic = next(e for e in events if e["requested_model"] is None)
    assert known["model"] == "gpt-4o-mini"
    assert historic["requested_model"] is None

    cfg = BurnLensConfig(db_path=db)
    with patch("burnlens.cli.load_config", return_value=cfg):
        result = runner.invoke(app, ["routing", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert any(r.get("requested_model") == "gpt-4o" for r in payload)
    assert any(r.get("requested_model") is None for r in payload)
    assert all(r.get("model") == "gpt-4o-mini" for r in payload)

    src = Path(__file__).resolve().parents[1].joinpath("burnlens", "cli.py").read_text()
    assert 'table.add_column("Requested Model"' in src
    assert 'table.add_column("Effective Model"' in src
    assert "unknown (historic)" in src
    assert "Original Model" not in src
    assert "routing.budget_downgrade" in src


def test_cloud_sync_payload_includes_provenance():
    payload = _row_to_payload(
        {
            "timestamp": "2026-09-04T00:00:00",
            "provider": "openai",
            "model": "gpt-4o-mini",
            "requested_model": "gpt-4o",
            "routed_model": "gpt-4o-mini",
            "downgrade_reason": "budget_pct",
            "pricing_class": "calculated",
            "tags": "{}",
        }
    )
    sanitized = _sanitize_record(payload)
    assert sanitized["requested_model"] == "gpt-4o"
    assert sanitized["model"] == "gpt-4o-mini"
    assert sanitized["routed_model"] == "gpt-4o-mini"
    assert sanitized["downgrade_reason"] == "budget_pct"
    assert json.dumps(sanitized)


def test_cloud_sync_historic_null_requested_model_is_preserved():
    payload = _row_to_payload(
        {
            "timestamp": "2026-09-04T00:00:00",
            "provider": "openai",
            "model": "gpt-4o-mini",
            "requested_model": None,
            "routed_model": "gpt-4o-mini",
            "downgrade_reason": "budget_pct",
            "tags": "{}",
        }
    )
    assert payload["requested_model"] is None
    assert payload["model"] == "gpt-4o-mini"
