"""Tests for weekly report generation."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from burnlens.reports.weekly import (
    WeeklyReport,
    generate_text_report,
    generate_weekly_report,
    send_report_email,
)
from burnlens.storage.database import init_db, insert_request
from burnlens.storage.models import RequestRecord


def _make_record(
    model: str = "gpt-4o-mini",
    provider: str = "openai",
    cost: float = 1.0,
    input_tokens: int = 100,
    output_tokens: int = 50,
    team: str | None = None,
    feature: str | None = None,
    timestamp: datetime | None = None,
) -> RequestRecord:
    tags: dict[str, str] = {}
    if team:
        tags["team"] = team
    if feature:
        tags["feature"] = feature
    return RequestRecord(
        timestamp=timestamp or datetime.now(timezone.utc),
        provider=provider,
        model=model,
        request_path="/v1/chat/completions",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        tags=tags,
    )


@pytest_asyncio.fixture
async def seeded_db(initialized_db: str) -> str:
    """Insert sample requests and return the db path."""
    now = datetime.now(timezone.utc)
    records = [
        _make_record(model="gpt-4o-mini", cost=10.0, team="backend", feature="chat", timestamp=now - timedelta(hours=1)),
        _make_record(model="gpt-4o-mini", cost=4.0, team="backend", feature="chat", timestamp=now - timedelta(hours=2)),
        _make_record(model="claude-haiku", cost=6.0, team="research", feature="search", timestamp=now - timedelta(hours=3)),
        # Prior period — 8 days ago
        _make_record(model="gpt-4o-mini", cost=15.0, team="backend", timestamp=now - timedelta(days=8)),
    ]
    for r in records:
        await insert_request(initialized_db, r)
    return initialized_db


@pytest.mark.asyncio
async def test_weekly_report_math_correct(seeded_db: str) -> None:
    """Total cost and request count should match inserted data."""
    report = await generate_weekly_report(seeded_db, days=7)

    assert report.total_cost == pytest.approx(20.0)
    assert report.total_requests == 3


@pytest.mark.asyncio
async def test_vs_prior_week_percent_change(seeded_db: str) -> None:
    """Percent change should reflect current vs prior period."""
    report = await generate_weekly_report(seeded_db, days=7)

    # Current = 20.0, prior = 15.0 → +33%
    expected = ((20.0 - 15.0) / 15.0) * 100
    assert report.vs_prior_week == pytest.approx(expected, abs=1.0)


@pytest.mark.asyncio
async def test_text_report_contains_all_sections(seeded_db: str) -> None:
    """The text report should contain all expected sections."""
    report = await generate_weekly_report(seeded_db, days=7)
    text = generate_text_report(report)

    assert "BurnLens Weekly Report" in text
    assert "Total spend:" in text
    assert "Total requests:" in text
    assert "By model:" in text
    assert "By team:" in text
    assert "Waste alerts:" in text
    # Model names should appear
    assert "gpt-4o-mini" in text
    assert "claude-haiku" in text


@pytest.mark.asyncio
async def test_empty_week_no_crash(initialized_db: str) -> None:
    """Report generation should not crash with an empty database."""
    report = await generate_weekly_report(initialized_db, days=7)

    assert report.total_cost == 0.0
    assert report.total_requests == 0
    assert report.vs_prior_week == 0.0

    text = generate_text_report(report)
    assert "BurnLens Weekly Report" in text
    assert "Total spend:    $0.00" in text


def test_email_config_missing_prints_helpful_error(capsys: pytest.CaptureFixture[str]) -> None:
    """When email config is missing, send_report_email should raise, not silently fail."""
    # The CLI checks config before calling send_report_email, but we verify
    # that send_report_email itself raises on bad connection (no silent pass).
    with pytest.raises(Exception):
        send_report_email(
            report_text="test",
            to_email="test@example.com",
            smtp_host="nonexistent.invalid",
            smtp_port=587,
            smtp_user="user",
            smtp_password="pass",
            from_addr="from@example.com",
        )


@pytest.mark.asyncio
async def test_cost_by_team_correct(seeded_db: str) -> None:
    """Cost by team should aggregate correctly."""
    report = await generate_weekly_report(seeded_db, days=7)

    assert report.cost_by_team["backend"] == pytest.approx(14.0)
    assert report.cost_by_team["research"] == pytest.approx(6.0)


@pytest.mark.asyncio
async def test_cost_by_model_correct(seeded_db: str) -> None:
    """Cost by model should aggregate correctly."""
    report = await generate_weekly_report(seeded_db, days=7)

    assert report.cost_by_model["gpt-4o-mini"] == pytest.approx(14.0)
    assert report.cost_by_model["claude-haiku"] == pytest.approx(6.0)
