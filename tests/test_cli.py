"""Basic CLI smoke tests."""
from __future__ import annotations

from typer.testing import CliRunner

from burnlens.cli import app

runner = CliRunner()


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "burnlens" in result.output.lower()


def test_top_no_db(tmp_path):
    """top command should not crash even with no database."""
    import asyncio

    from burnlens.storage.database import init_db

    db = str(tmp_path / "test.db")
    asyncio.run(init_db(db))

    # Patch config to use tmp db
    from unittest.mock import patch

    from burnlens.config import BurnLensConfig

    cfg = BurnLensConfig(db_path=db)
    with patch("burnlens.cli.load_config", return_value=cfg):
        result = runner.invoke(app, ["top"])
    assert result.exit_code == 0
