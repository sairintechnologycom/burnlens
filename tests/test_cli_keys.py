"""CODE-2 STEP 9: ``burnlens keys`` CLI — today's spend roll-up."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from typer.testing import CliRunner

from burnlens.cli import app
from burnlens.config import (
    AlertsConfig,
    ApiKeyBudgetsConfig,
    BurnLensConfig,
    KeyBudgetEntry,
)
from burnlens.keys import register_key
from burnlens.storage.database import init_db, insert_request
from burnlens.storage.models import RequestRecord


runner = CliRunner()


def _cfg(
    db_path: str,
    keys: dict[str, KeyBudgetEntry] | None = None,
    default: KeyBudgetEntry | None = None,
    tz: str = "UTC",
) -> BurnLensConfig:
    return BurnLensConfig(
        db_path=db_path,
        alerts=AlertsConfig(
            api_key_budgets=ApiKeyBudgetsConfig(
                keys=keys or {},
                default=default,
                reset_timezone=tz,
            ),
        ),
    )


def _patched(cfg: BurnLensConfig):
    return patch("burnlens.cli.load_config", return_value=cfg)


async def _seed(db: str, label: str | None, cost: float) -> None:
    tags: dict[str, Any] = {}
    if label is not None:
        tags["key_label"] = label
    await insert_request(
        db,
        RequestRecord(
            provider="openai",
            model="gpt-4o",
            request_path="/v1/chat",
            timestamp=datetime.now(timezone.utc),
            input_tokens=0,
            output_tokens=0,
            reasoning_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=0,
            cost_usd=cost,
            duration_ms=0,
            status_code=200,
            tags=tags,
        ),
    )


# ---------------------------------------------------------------------------


def test_keys_empty_state(tmp_path: Path) -> None:
    db = str(tmp_path / "burnlens.db")
    asyncio.run(init_db(db))
    with _patched(_cfg(db)):
        result = runner.invoke(app, ["keys"])
    assert result.exit_code == 0, result.output
    assert "No registered keys" in result.output


def test_keys_renders_table_with_caps_and_status(tmp_path: Path) -> None:
    db = str(tmp_path / "burnlens.db")
    asyncio.run(init_db(db))

    cfg = _cfg(
        db,
        keys={
            "ok": KeyBudgetEntry(daily_usd=10.0),
            "warn": KeyBudgetEntry(daily_usd=10.0),
            "crit": KeyBudgetEntry(daily_usd=10.0),
        },
    )

    async def _seed_all() -> None:
        await _seed(db, "ok", 4.0)
        await _seed(db, "warn", 8.0)
        await _seed(db, "crit", 12.0)

    asyncio.run(_seed_all())

    with _patched(cfg):
        result = runner.invoke(app, ["keys"])

    assert result.exit_code == 0, result.output
    out = result.output
    assert "ok" in out
    assert "warn" in out
    assert "crit" in out
    assert "OK" in out
    assert "WARNING" in out
    assert "CRITICAL" in out
    # Most-exhausted label sorts above least-exhausted in the table.
    assert out.index("crit") < out.index("warn") < out.index("ok")


def test_keys_json_output(tmp_path: Path) -> None:
    db = str(tmp_path / "burnlens.db")
    asyncio.run(init_db(db))
    cfg = _cfg(db, keys={"k": KeyBudgetEntry(daily_usd=10.0)})
    asyncio.run(register_key(db, "k", "openai", "sk-test"))

    with _patched(cfg):
        result = runner.invoke(app, ["keys", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert len(payload) == 1
    row = payload[0]
    assert row["label"] == "k"
    assert row["daily_cap"] == 10.0
    assert row["spent_usd"] == 0.0
    assert row["status"] == "OK"
    assert row["reset_timezone"] == "UTC"


def test_keys_no_cap_label_appears_with_no_cap_status(tmp_path: Path) -> None:
    db = str(tmp_path / "burnlens.db")
    asyncio.run(init_db(db))
    asyncio.run(_seed(db, "stray", 3.0))

    with _patched(_cfg(db)):
        result = runner.invoke(app, ["keys"])

    assert result.exit_code == 0, result.output
    assert "stray" in result.output
    assert "NO CAP" in result.output


def test_keys_registered_label_with_no_traffic_is_zero_and_ok(tmp_path: Path) -> None:
    db = str(tmp_path / "burnlens.db")
    asyncio.run(init_db(db))
    asyncio.run(register_key(db, "fresh", "anthropic", "sk-ant-fresh"))

    cfg = _cfg(db, keys={"fresh": KeyBudgetEntry(daily_usd=25.0)})
    with _patched(cfg):
        result = runner.invoke(app, ["keys", "--json"])

    payload = json.loads(result.output)
    assert len(payload) == 1
    assert payload[0]["label"] == "fresh"
    assert payload[0]["spent_usd"] == 0.0
    assert payload[0]["status"] == "OK"


def test_keys_default_cap_applies_to_unregistered_traffic(tmp_path: Path) -> None:
    db = str(tmp_path / "burnlens.db")
    asyncio.run(init_db(db))
    asyncio.run(_seed(db, "ad-hoc", 5.0))

    cfg = _cfg(db, default=KeyBudgetEntry(daily_usd=20.0))
    with _patched(cfg):
        result = runner.invoke(app, ["keys", "--json"])

    payload = json.loads(result.output)
    assert len(payload) == 1
    assert payload[0]["label"] == "ad-hoc"
    assert payload[0]["daily_cap"] == 20.0
    assert payload[0]["pct_used"] == 25.0
    assert payload[0]["status"] == "OK"


def test_keys_timezone_label_in_table_header(tmp_path: Path) -> None:
    db = str(tmp_path / "burnlens.db")
    asyncio.run(init_db(db))
    asyncio.run(register_key(db, "tz", "openai", "sk-tz"))

    cfg = _cfg(db, keys={"tz": KeyBudgetEntry(daily_usd=5.0)}, tz="Asia/Kolkata")
    with _patched(cfg):
        result = runner.invoke(app, ["keys"])

    assert result.exit_code == 0, result.output
    assert "Asia/Kolkata" in result.output
