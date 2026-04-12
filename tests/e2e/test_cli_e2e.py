"""CLI integration tests using Typer's test runner with a seeded DB.

Tests validate budgets, export, report, and customers commands produce
correct output consistent with seeded data.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from burnlens.cli import app
from burnlens.cost.calculator import TokenUsage, calculate_cost
from burnlens.storage.models import RequestRecord

# Typer wraps Click's test runner
from typer.testing import CliRunner

runner = CliRunner()

# ---------------------------------------------------------------------------
# Seed constants (mirrors conftest_e2e)
# ---------------------------------------------------------------------------

_MODELS = {
    "openai": ["gpt-4o-mini", "gpt-4o"],
    "anthropic": ["claude-haiku-4-5-20251001"],
    "google": ["gemini-1.5-flash"],
}
_REQUEST_PATHS = {
    "openai": "/v1/chat/completions",
    "anthropic": "/v1/messages",
    "google": "/v1beta/models/gemini-1.5-flash:generateContent",
}
_FEATURES = ["chat", "search", "summarise"]
_TEAMS = ["backend", "research", "infra"]
_CUSTOMERS = ["acme-corp", "beta-user", "unknown-co"]
_SEED_COUNT = 30


def _calc_cost(provider: str, model: str, inp: int, out: int) -> float:
    return calculate_cost(provider, model, TokenUsage(input_tokens=inp, output_tokens=out))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def seeded_env(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Create a temp DB, seed 30 rows, write a config YAML, return env dict.

    The returned dict contains:
      - db_path: path to the seeded SQLite DB
      - config_path: path to the YAML config file
      - export_dir: temp directory for export files
    """
    import asyncio
    from burnlens.storage.database import init_db, insert_request

    base = tmp_path_factory.mktemp("cli_e2e")
    db_path = str(base / "test.db")
    config_path = str(base / "burnlens.yaml")
    export_dir = str(base / "exports")
    os.makedirs(export_dir, exist_ok=True)

    # Seed DB
    async def _seed() -> None:
        await init_db(db_path)
        now = datetime.now(timezone.utc)
        rng = random.Random(42)

        for i in range(_SEED_COUNT):
            provider = ["openai", "openai", "anthropic", "google"][i % 4]
            model = _MODELS[provider][i % len(_MODELS[provider])]
            input_tokens = rng.randint(50, 8000)
            output_tokens = rng.randint(10, 500)
            days_ago = rng.uniform(0, 14)

            record = RequestRecord(
                provider=provider,
                model=model,
                request_path=_REQUEST_PATHS[provider],
                timestamp=now - timedelta(days=days_ago),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=_calc_cost(provider, model, input_tokens, output_tokens),
                duration_ms=rng.randint(200, 5000),
                status_code=200,
                tags={
                    "feature": _FEATURES[i % len(_FEATURES)],
                    "team": _TEAMS[i % len(_TEAMS)],
                    "customer": _CUSTOMERS[i % len(_CUSTOMERS)],
                    "streaming": str(rng.choice([True, False])).lower(),
                },
                system_prompt_hash=hashlib.sha256(
                    f"system-prompt-{i}".encode()
                ).hexdigest(),
            )
            await insert_request(db_path, record)

    asyncio.run(_seed())

    # Write config YAML with team budgets and customer budgets
    config = {
        "db_path": db_path,
        "budgets": {
            "teams": {
                "backend": 10.00,
                "research": 10.00,
                "infra": 10.00,
            },
        },
        "customer_budgets": {
            "default": 5.00,
            "acme-corp": 0.001,  # tiny limit → will be EXCEEDED
            "beta-user": 5.00,
            "unknown-co": 5.00,
        },
    }
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return {
        "db_path": db_path,
        "config_path": config_path,
        "export_dir": export_dir,
    }


# ---------------------------------------------------------------------------
# 1. Budgets table shows all teams
# ---------------------------------------------------------------------------

def test_budgets_table_output_has_all_teams(seeded_env: dict[str, str]):
    result = runner.invoke(app, ["budgets", "--config", seeded_env["config_path"]])
    assert result.exit_code == 0, result.output

    for team in _TEAMS:
        assert team in result.output, f"Team {team!r} not found in output"

    # Check table columns exist (Rich renders them)
    for col in ("Spent", "Limit", "% Used"):
        assert col in result.output, f"Column {col!r} not found in output"


# ---------------------------------------------------------------------------
# 2. Budgets --json is valid JSON
# ---------------------------------------------------------------------------

def test_budgets_json_is_valid_json(seeded_env: dict[str, str]):
    result = runner.invoke(app, ["budgets", "--json", "--config", seeded_env["config_path"]])
    assert result.exit_code == 0, result.output

    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 3  # 3 teams

    for entry in data:
        for key in ("team", "spent", "limit", "pct_used", "status"):
            assert key in entry, f"Missing key {key!r} in budget entry"


# ---------------------------------------------------------------------------
# 3. Export creates CSV with correct header
# ---------------------------------------------------------------------------

def test_export_creates_csv_file(seeded_env: dict[str, str]):
    out_path = os.path.join(seeded_env["export_dir"], "test_export.csv")
    result = runner.invoke(app, [
        "export", "--config", seeded_env["config_path"],
        "--days", "30", "--output", out_path,
    ])
    assert result.exit_code == 0, result.output
    assert os.path.exists(out_path), "CSV file was not created"

    with open(out_path) as f:
        reader = csv.reader(f)
        header = next(reader)

    expected_header = [
        "timestamp", "provider", "model", "feature", "team", "customer",
        "tokens_in", "tokens_out", "reasoning_tokens", "cache_read_tokens",
        "cache_write_tokens", "cost_usd", "latency_ms", "status_code",
    ]
    assert header == expected_header


# ---------------------------------------------------------------------------
# 4. Export cost_usd has no scientific notation
# ---------------------------------------------------------------------------

def test_export_cost_usd_no_scientific_notation(seeded_env: dict[str, str]):
    out_path = os.path.join(seeded_env["export_dir"], "test_export_notation.csv")
    result = runner.invoke(app, [
        "export", "--config", seeded_env["config_path"],
        "--days", "30", "--output", out_path,
    ])
    assert result.exit_code == 0, result.output

    with open(out_path) as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            cost_str = row["cost_usd"]
            assert "e" not in cost_str.lower(), (
                f"Row {i}: cost_usd in scientific notation: {cost_str}"
            )
            cost_val = float(cost_str)
            assert cost_val >= 0, f"Row {i}: cost_usd is negative: {cost_val}"


# ---------------------------------------------------------------------------
# 5. Export --days filter
# ---------------------------------------------------------------------------

def test_export_days_filter(seeded_env: dict[str, str]):
    out_path = os.path.join(seeded_env["export_dir"], "test_export_3d.csv")
    result = runner.invoke(app, [
        "export", "--config", seeded_env["config_path"],
        "--days", "3", "--output", out_path,
    ])
    assert result.exit_code == 0, result.output

    cutoff = datetime.now(timezone.utc) - timedelta(days=3)

    with open(out_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # May have 0 rows if RNG didn't place any in the 3-day window — that's valid
    for i, row in enumerate(rows):
        ts = datetime.fromisoformat(row["timestamp"])
        assert ts >= cutoff, (
            f"Row {i}: timestamp {row['timestamp']} is older than 3 days"
        )


# ---------------------------------------------------------------------------
# 6. Export --team filter
# ---------------------------------------------------------------------------

def test_export_team_filter(seeded_env: dict[str, str]):
    out_path = os.path.join(seeded_env["export_dir"], "test_export_backend.csv")
    result = runner.invoke(app, [
        "export", "--config", seeded_env["config_path"],
        "--days", "30", "--team", "backend", "--output", out_path,
    ])
    assert result.exit_code == 0, result.output

    with open(out_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) > 0, "Expected at least one backend row"
    for i, row in enumerate(rows):
        assert row["team"] == "backend", (
            f"Row {i}: expected team='backend', got {row['team']!r}"
        )


# ---------------------------------------------------------------------------
# 7. Report contains required sections
# ---------------------------------------------------------------------------

def test_report_contains_required_sections(seeded_env: dict[str, str]):
    result = runner.invoke(app, [
        "report", "--config", seeded_env["config_path"], "--days", "30",
    ])
    assert result.exit_code == 0, result.output

    output = result.output
    for section in ("Total spend", "Total requests", "By model", "By team"):
        assert section in output, f"Section {section!r} not found in report output"


# ---------------------------------------------------------------------------
# 8. Report shows % for vs prior period
# ---------------------------------------------------------------------------

def test_report_vs_prior_week_shows_percent(seeded_env: dict[str, str]):
    result = runner.invoke(app, [
        "report", "--config", seeded_env["config_path"], "--days", "30",
    ])
    assert result.exit_code == 0, result.output

    # The report line contains "vs prior period" with a percent value
    assert "%" in result.output, "Report should contain '%' for vs prior period"
    assert "vs prior" in result.output.lower(), "Report should mention 'vs prior'"


# ---------------------------------------------------------------------------
# 9. Customers table shows all customers
# ---------------------------------------------------------------------------

def test_customers_table_shows_all_customers(seeded_env: dict[str, str]):
    result = runner.invoke(app, [
        "customers", "--config", seeded_env["config_path"],
    ])
    assert result.exit_code == 0, result.output

    for customer in _CUSTOMERS:
        assert customer in result.output, (
            f"Customer {customer!r} not found in output"
        )


# ---------------------------------------------------------------------------
# 10. Customers --over-budget shows only exceeded
# ---------------------------------------------------------------------------

def test_customers_over_budget_flag(seeded_env: dict[str, str]):
    result = runner.invoke(app, [
        "customers", "--over-budget", "--json", "--config", seeded_env["config_path"],
    ])
    assert result.exit_code == 0, result.output

    data = json.loads(result.output)
    assert isinstance(data, list)

    # acme-corp has a $0.001 budget and should be EXCEEDED
    exceeded_names = {entry["customer"] for entry in data}
    assert "acme-corp" in exceeded_names, (
        "acme-corp should be over budget with $0.001 limit"
    )

    # All entries in the result should be EXCEEDED
    for entry in data:
        assert entry["status"] == "EXCEEDED", (
            f"Customer {entry['customer']} has status {entry['status']!r}, expected EXCEEDED"
        )
