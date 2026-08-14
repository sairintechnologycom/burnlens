"""Basic CLI smoke tests."""
from __future__ import annotations

from typer.testing import CliRunner

from burnlens.cli import app

runner = CliRunner()


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "burnlens" in result.output.lower()


def test_pricing_csv():
    from burnlens.cost.pricing import all_pricing

    result = runner.invoke(app, ["pricing", "--csv"])
    assert result.exit_code == 0
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    assert lines[0].startswith("provider,model,input_per_million")
    # header + one row per priced model
    assert len(lines) == 1 + len(all_pricing())
    assert any(ln.startswith("openai,gpt-5.6-sol,") for ln in lines)


def test_pricing_csv_to_file(tmp_path):
    out = tmp_path / "prices.csv"
    result = runner.invoke(app, ["pricing", "--output", str(out)])
    assert result.exit_code == 0
    assert out.read_text().startswith("provider,model,input_per_million")


def test_top_no_db(tmp_path):
    """top command should not crash even with no database."""
    import asyncio

    from burnlens.storage.database import init_db

    db = str(tmp_path / "test.db")
    asyncio.run(init_db(db))

    # Patch config to use tmp db, and mock Live to avoid the infinite loop
    from unittest.mock import patch, MagicMock

    from burnlens.config import BurnLensConfig

    cfg = BurnLensConfig(db_path=db)

    mock_live = MagicMock()
    mock_live.__enter__ = MagicMock(return_value=mock_live)
    mock_live.__exit__ = MagicMock(return_value=False)

    with patch("burnlens.cli.load_config", return_value=cfg), \
         patch("burnlens.cli.Live", return_value=mock_live), \
         patch("burnlens.cli.time.sleep", side_effect=KeyboardInterrupt):
        result = runner.invoke(app, ["top"])
    assert result.exit_code == 0


def test_sync_now_on_fresh_db(tmp_path):
    """`sync --now` must work on a machine where the proxy has never run.

    Two bugs met here. CloudSync takes the whole BurnLensConfig and reads
    `.cloud` itself, but the CLI passed `cfg.cloud`, so every invocation died
    with `AttributeError: 'CloudConfig' object has no attribute 'cloud'`. Once
    that was fixed the command still traceback-dumped on a db_path with no
    schema — it ran the synced_at migration alone instead of init_db, and
    aiosqlite creates the missing file, so the ALTER hit "no such table:
    requests".

    Every test in test_cloud_sync.py builds CloudSync directly with the right
    argument against a prepared DB, so neither was visible there. This drives
    the real command against an uninitialised path — deliberately no init_db.
    """
    from unittest.mock import patch

    from burnlens.config import BurnLensConfig, CloudConfig

    db = str(tmp_path / "never-created.db")
    cfg = BurnLensConfig(db_path=db, cloud=CloudConfig(enabled=True, api_key="bl_test"))

    # Empty DB — no unsynced rows, so the run completes without any network I/O.
    with patch("burnlens.cli.load_config", return_value=cfg):
        result = runner.invoke(app, ["sync", "--now"])

    assert result.exit_code == 0, result.output
    assert "No un-synced records" in result.output

    with patch("burnlens.cli.load_config", return_value=cfg):
        status = runner.invoke(app, ["sync", "--status"])

    assert status.exit_code == 0, status.output
    assert "Un-synced: 0" in status.output
