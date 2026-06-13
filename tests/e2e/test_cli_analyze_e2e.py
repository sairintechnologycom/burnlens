"""End-to-end validation of CLI waste analysis for new prompt detectors."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from typer.testing import CliRunner

from burnlens.cli import app
from burnlens.config import BurnLensConfig
from burnlens.storage.database import init_db, insert_request
from burnlens.storage.models import RequestRecord


def _create_record(
    provider="openai",
    model="gpt-4o",
    input_tokens=1000,
    output_tokens=100,
    cost_usd=0.01,
    system_prompt_hash=None,
    cache_read_tokens=0,
    prompt_system_tokens=0,
    prompt_user_tokens=0,
    prompt_tools_tokens=0,
    prompt_rag_tokens=0,
    prompt_history_tokens=0,
):
    return RequestRecord(
        provider=provider,
        model=model,
        request_path="/v1/chat/completions",
        timestamp=datetime.now(timezone.utc),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        duration_ms=500,
        status_code=200,
        tags={},
        system_prompt_hash=system_prompt_hash,
        cache_read_tokens=cache_read_tokens,
        prompt_system_tokens=prompt_system_tokens,
        prompt_user_tokens=prompt_user_tokens,
        prompt_tools_tokens=prompt_tools_tokens,
        prompt_rag_tokens=prompt_rag_tokens,
        prompt_history_tokens=prompt_history_tokens,
    )


@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "cli_analyze_test.db")


@pytest.fixture
async def seeded_db(db_path: str) -> str:
    # Initialize DB
    await init_db(db_path)

    # 1. Trigger PromptCachingOpportunityDetector:
    # 5 requests with same system prompt hash, large system tokens (1500), cache_read_tokens=0
    for _ in range(5):
        await insert_request(
            db_path,
            _create_record(
                system_prompt_hash="cache-op-hash",
                prompt_system_tokens=1500,
                cache_read_tokens=0,
                cost_usd=0.10,
            ),
        )

    # 2. Trigger OversizedToolSchemaDetector:
    # 3 requests with tools tokens >= 1000 and ratio >= 30%
    for _ in range(3):
        await insert_request(
            db_path,
            _create_record(
                input_tokens=3000,
                prompt_tools_tokens=1500,  # 50% of input
                cost_usd=0.10,
            ),
        )

    # 3. Trigger LowRAGEfficiencyDetector:
    # 3 requests with RAG tokens >= 8000 and output tokens < 100
    for _ in range(3):
        await insert_request(
            db_path,
            _create_record(
                prompt_rag_tokens=9000,
                output_tokens=50,
                cost_usd=0.20,
            ),
        )

    # 4. Trigger HistoryBloatDetector:
    # 3 requests with history tokens >= 5000 and ratio >= 50%
    for _ in range(3):
        await insert_request(
            db_path,
            _create_record(
                input_tokens=10000,
                prompt_history_tokens=6000,  # 60% of input
                cost_usd=0.20,
            ),
        )

    return db_path


def test_cli_analyze_shows_new_waste_detectors(seeded_db: str):
    runner = CliRunner()
    cfg = BurnLensConfig(db_path=seeded_db)

    with patch("burnlens.cli.load_config", return_value=cfg):
        result = runner.invoke(app, ["analyze"])

    assert result.exit_code == 0
    output = result.output

    # Check for presence of all four new detectors or titles in the output
    assert "Prompt Caching Opportunity" in output
    assert "Oversized Tool Schemas" in output
    assert "Low RAG Efficiency" in output
    assert "Chat History Bloat" in output

    # Check that estimated waste values and affected counts are printed
    assert "Estimated waste" in output
    assert "Affected" in output
