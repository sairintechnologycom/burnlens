"""CODE-2: API key registration store + `burnlens key` CLI."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import aiosqlite
import pytest
from typer.testing import CliRunner

from burnlens.cli import app
from burnlens.config import BurnLensConfig
from burnlens.keys import (
    KeyAlreadyExists,
    get_label_by_hash,
    hash_api_key,
    key_prefix,
    list_keys,
    register_key,
    remove_key,
    touch_last_used,
)
from burnlens.storage.database import init_db


runner = CliRunner()


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def test_hash_api_key_is_sha256_hex() -> None:
    digest = hash_api_key("sk-ant-foo")
    # SHA-256 hex digest is 64 chars
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)
    # Stable across calls
    assert digest == hash_api_key("sk-ant-foo")
    # Different input → different output
    assert digest != hash_api_key("sk-ant-bar")


def test_key_prefix_is_first_eight_chars() -> None:
    assert key_prefix("sk-ant-real-key-12345") == "sk-ant-r"


# ---------------------------------------------------------------------------
# Storage CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_key_persists_hash_and_prefix(tmp_path: Path) -> None:
    db_path = str(tmp_path / "burnlens.db")
    await init_db(db_path)

    raw_key = "sk-ant-supersecret-12345"
    row = await register_key(db_path, "cursor-main", "anthropic", raw_key)

    assert row["label"] == "cursor-main"
    assert row["provider"] == "anthropic"
    assert row["key_prefix"] == "sk-ant-s"

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT label, provider, key_hash, key_prefix FROM api_keys"
        )
        rows = await cursor.fetchall()

    assert len(rows) == 1
    assert rows[0][2] == hash_api_key(raw_key)


@pytest.mark.asyncio
async def test_register_key_never_stores_raw_key(tmp_path: Path) -> None:
    """Raw key MUST NOT appear anywhere in the api_keys table."""
    db_path = str(tmp_path / "burnlens.db")
    await init_db(db_path)

    raw_key = "sk-ant-supersecret-NEVER-LOG-ME"
    await register_key(db_path, "k", "anthropic", raw_key)

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT * FROM api_keys")
        rows = await cursor.fetchall()

    blob = repr(rows)
    assert "supersecret-NEVER-LOG-ME" not in blob


@pytest.mark.asyncio
async def test_register_key_rejects_duplicate_label(tmp_path: Path) -> None:
    db_path = str(tmp_path / "burnlens.db")
    await init_db(db_path)

    await register_key(db_path, "dup", "anthropic", "sk-ant-1")
    with pytest.raises(KeyAlreadyExists):
        await register_key(db_path, "dup", "openai", "sk-2")


@pytest.mark.asyncio
async def test_register_key_validates_required_fields(tmp_path: Path) -> None:
    db_path = str(tmp_path / "burnlens.db")
    await init_db(db_path)

    with pytest.raises(ValueError):
        await register_key(db_path, "", "anthropic", "sk-x")
    with pytest.raises(ValueError):
        await register_key(db_path, "x", "", "sk-x")
    with pytest.raises(ValueError):
        await register_key(db_path, "x", "anthropic", "")


@pytest.mark.asyncio
async def test_list_keys_returns_newest_first(tmp_path: Path) -> None:
    db_path = str(tmp_path / "burnlens.db")
    await init_db(db_path)

    await register_key(db_path, "older", "anthropic", "sk-1")
    # Force a different timestamp ordering
    await asyncio.sleep(0.01)
    await register_key(db_path, "newer", "openai", "sk-2")

    rows = await list_keys(db_path)
    labels = [r["label"] for r in rows]
    assert labels == ["newer", "older"]
    # Hash must not leak via list_keys
    assert all("key_hash" not in r for r in rows)


@pytest.mark.asyncio
async def test_remove_key_returns_true_when_present(tmp_path: Path) -> None:
    db_path = str(tmp_path / "burnlens.db")
    await init_db(db_path)

    await register_key(db_path, "doomed", "anthropic", "sk-x")
    assert await remove_key(db_path, "doomed") is True
    assert await remove_key(db_path, "doomed") is False


@pytest.mark.asyncio
async def test_get_label_by_hash_roundtrip(tmp_path: Path) -> None:
    db_path = str(tmp_path / "burnlens.db")
    await init_db(db_path)

    raw_key = "sk-ant-roundtrip-9999"
    await register_key(db_path, "rt", "anthropic", raw_key)

    digest = hash_api_key(raw_key)
    assert await get_label_by_hash(db_path, digest) == "rt"
    assert await get_label_by_hash(db_path, "0" * 64) is None


@pytest.mark.asyncio
async def test_touch_last_used_updates_column(tmp_path: Path) -> None:
    db_path = str(tmp_path / "burnlens.db")
    await init_db(db_path)
    await register_key(db_path, "tk", "anthropic", "sk-x")

    rows_before = await list_keys(db_path)
    assert rows_before[0]["last_used_at"] is None

    await touch_last_used(db_path, "tk")
    rows_after = await list_keys(db_path)
    assert rows_after[0]["last_used_at"] is not None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _patched_cfg(db_path: str):
    return patch("burnlens.cli.load_config", return_value=BurnLensConfig(db_path=db_path))


def test_cli_key_register_with_inline_key(tmp_path: Path) -> None:
    db = str(tmp_path / "burnlens.db")
    with _patched_cfg(db):
        result = runner.invoke(
            app,
            ["key", "register", "--label", "cli-test", "--provider", "anthropic", "--key", "sk-ant-cli"],
        )
    assert result.exit_code == 0, result.output
    assert "Registered" in result.output
    assert "cli-test" in result.output


def test_cli_key_register_prompts_when_key_missing(tmp_path: Path) -> None:
    db = str(tmp_path / "burnlens.db")
    with _patched_cfg(db):
        result = runner.invoke(
            app,
            ["key", "register", "--label", "prompted", "--provider", "openai"],
            input="sk-from-prompt\n",
        )
    assert result.exit_code == 0, result.output
    assert "Registered" in result.output
    # Raw key must not echo back into CLI output
    assert "sk-from-prompt" not in result.output


def test_cli_key_register_rejects_empty_prompt(tmp_path: Path) -> None:
    db = str(tmp_path / "burnlens.db")
    with _patched_cfg(db):
        result = runner.invoke(
            app,
            ["key", "register", "--label", "empty", "--provider", "openai"],
            input="\n",
        )
    # typer.prompt re-asks on empty input then aborts; our own empty check
    # also raises Exit(1). Either way, exit must be non-zero and nothing
    # should land in the table.
    assert result.exit_code != 0

    async def _count() -> int:
        await init_db(db)
        rows = await list_keys(db)
        return len(rows)

    assert asyncio.run(_count()) == 0


def test_cli_key_register_duplicate_label_exits_nonzero(tmp_path: Path) -> None:
    db = str(tmp_path / "burnlens.db")
    with _patched_cfg(db):
        first = runner.invoke(
            app,
            ["key", "register", "--label", "dup", "--provider", "anthropic", "--key", "sk-1"],
        )
        assert first.exit_code == 0

        second = runner.invoke(
            app,
            ["key", "register", "--label", "dup", "--provider", "openai", "--key", "sk-2"],
        )
    assert second.exit_code == 1
    assert "already registered" in second.output


def test_cli_key_list_empty(tmp_path: Path) -> None:
    db = str(tmp_path / "burnlens.db")
    with _patched_cfg(db):
        result = runner.invoke(app, ["key", "list"])
    assert result.exit_code == 0
    assert "No API keys registered" in result.output


def test_cli_key_list_shows_registered_keys(tmp_path: Path) -> None:
    db = str(tmp_path / "burnlens.db")
    with _patched_cfg(db):
        runner.invoke(
            app,
            ["key", "register", "--label", "cursor-main", "--provider", "anthropic", "--key", "sk-ant-zzz"],
        )
        result = runner.invoke(app, ["key", "list"])

    assert result.exit_code == 0
    assert "cursor-main" in result.output
    assert "anthropic" in result.output
    assert "sk-ant-z" in result.output  # prefix only
    # Nothing past the prefix should leak
    assert "sk-ant-zzz" not in result.output


def test_cli_key_remove_existing(tmp_path: Path) -> None:
    db = str(tmp_path / "burnlens.db")
    with _patched_cfg(db):
        runner.invoke(
            app,
            ["key", "register", "--label", "kill-me", "--provider", "openai", "--key", "sk-x"],
        )
        result = runner.invoke(app, ["key", "remove", "--label", "kill-me"])

    assert result.exit_code == 0
    assert "Removed" in result.output


def test_cli_key_remove_missing_exits_nonzero(tmp_path: Path) -> None:
    db = str(tmp_path / "burnlens.db")
    with _patched_cfg(db):
        result = runner.invoke(app, ["key", "remove", "--label", "ghost"])
    assert result.exit_code == 1
    assert "No key registered" in result.output
