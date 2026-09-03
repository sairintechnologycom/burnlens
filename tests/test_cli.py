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


def test_scan_prints_the_local_first_funnel(tmp_path):
    """After import, the next commands have to be on screen or the loop dies."""
    from unittest.mock import AsyncMock, patch

    from burnlens.config import BurnLensConfig

    cfg = BurnLensConfig(db_path=str(tmp_path / "scan.db"))
    with patch("burnlens.cli.load_config", return_value=cfg), patch(
        "burnlens.cli._run_claude_scan", new_callable=AsyncMock
    ), patch(
        "burnlens.cli._run_scan_derive", new_callable=AsyncMock
    ) as mock_derive:
        result = runner.invoke(app, ["scan", "--provider", "claude", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "today's bundled pricing table" in result.output
    assert "burnlens economics" in result.output
    assert "burnlens repos" in result.output
    assert "burnlens outcome derive" in result.output
    mock_derive.assert_not_called()


def test_scan_derives_outcomes_when_gh_is_present(tmp_path):
    """The coding-agent loop: scan import is followed by derive, not a hunt."""
    from unittest.mock import AsyncMock, patch

    from burnlens.config import BurnLensConfig
    from burnlens.outcomes import DeriveResult

    cfg = BurnLensConfig(db_path=str(tmp_path / "scan.db"))
    derived = DeriveResult(
        repo="proj",
        workflow_id="repo:proj",
        inserted=3,
        accepted=2,
        rejected=1,
    )
    with patch("burnlens.cli.load_config", return_value=cfg), patch(
        "burnlens.cli._run_claude_scan", new_callable=AsyncMock
    ), patch(
        "burnlens.outcomes.derive_pr_outcomes",
        new_callable=AsyncMock,
        return_value=derived,
    ) as mock_derive:
        result = runner.invoke(app, ["scan", "--provider", "claude"])
    assert result.exit_code == 0, result.output
    mock_derive.assert_awaited_once()
    assert "Derived" in result.output
    assert "3 new outcome" in result.output
    assert "burnlens outcome show" in result.output
    assert "burnlens outcome derive" not in result.output


def test_scan_reports_missing_gh_as_a_fact(tmp_path):
    """A missing gh is the error, not a silent skip and not a new scanner."""
    from unittest.mock import AsyncMock, patch

    from burnlens.config import BurnLensConfig

    cfg = BurnLensConfig(db_path=str(tmp_path / "scan.db"))
    with patch("burnlens.cli.load_config", return_value=cfg), patch(
        "burnlens.cli._run_claude_scan", new_callable=AsyncMock
    ), patch("burnlens.outcomes.shutil.which", return_value=None):
        result = runner.invoke(app, ["scan", "--provider", "claude"])
    assert result.exit_code == 0, result.output
    assert "Could not derive outcomes" in result.output
    assert "cli.github.com" in result.output
    assert "burnlens outcome derive" in result.output


def test_outcome_derive_fails_when_gh_is_missing(tmp_path):
    from unittest.mock import patch

    from burnlens.config import BurnLensConfig

    cfg = BurnLensConfig(db_path=str(tmp_path / "derive.db"))
    with patch("burnlens.cli.load_config", return_value=cfg), patch(
        "burnlens.outcomes.shutil.which", return_value=None
    ):
        result = runner.invoke(app, ["outcome", "derive", "--repo", str(tmp_path)])
    assert result.exit_code == 1
    assert "cli.github.com" in result.output
