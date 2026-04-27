"""Tests for waste detectors and budget tracking."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from burnlens.analysis.budget import (
    BudgetStatus,
    BudgetTracker,
    compute_budget_status,
)
from burnlens.analysis.waste import (
    ContextBloatDetector,
    DuplicateRequestDetector,
    ModelOverkillDetector,
    SystemPromptWasteDetector,
    run_all_detectors,
)
from burnlens.config import AlertsConfig, BudgetConfig, BurnLensConfig
from burnlens.storage.database import insert_request
from burnlens.storage.models import RequestRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _req(
    model: str = "gpt-4o",
    input_tokens: int = 500,
    output_tokens: int = 100,
    cost_usd: float = 0.01,
    system_prompt_hash: str | None = None,
    cache_read_tokens: int = 0,
) -> dict:
    return {
        "id": 1,
        "timestamp": datetime.utcnow().isoformat(),
        "provider": "openai",
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "duration_ms": 300,
        "tags": {},
        "system_prompt_hash": system_prompt_hash,
        "cache_read_tokens": cache_read_tokens,
    }


def _make_config(
    db_path: str,
    daily_usd: float | None = None,
    weekly_usd: float | None = None,
    monthly_usd: float | None = None,
) -> BurnLensConfig:
    budget = BudgetConfig(
        daily_usd=daily_usd,
        weekly_usd=weekly_usd,
        monthly_usd=monthly_usd,
    )
    alerts = AlertsConfig(budget=budget)
    cfg = BurnLensConfig(db_path=db_path, alerts=alerts)
    return cfg


# ---------------------------------------------------------------------------
# ContextBloatDetector
# ---------------------------------------------------------------------------


class TestContextBloatDetector:
    def test_empty_requests_returns_low(self):
        finding = ContextBloatDetector().run([])
        assert finding.severity == "low"
        assert finding.affected_count == 0

    def test_normal_requests_not_flagged(self):
        # input=500, output=100 → ratio=0.2 well above 0.05 threshold
        requests = [_req(input_tokens=500, output_tokens=100) for _ in range(5)]
        finding = ContextBloatDetector().run(requests)
        assert finding.affected_count == 0
        assert finding.severity == "low"

    def test_bloated_request_triggers(self):
        # input=10_000, output=100 → ratio=0.01 < 0.05, input >= 8_000
        bloated = _req(input_tokens=10_000, output_tokens=100, cost_usd=0.10)
        finding = ContextBloatDetector().run([bloated])
        assert finding.affected_count == 1
        assert finding.severity == "medium"
        assert finding.estimated_waste_usd > 0

    def test_bloated_waste_is_50_percent_of_cost(self):
        bloated = _req(input_tokens=10_000, output_tokens=100, cost_usd=0.20)
        finding = ContextBloatDetector().run([bloated])
        assert abs(finding.estimated_waste_usd - 0.10) < 1e-9

    def test_high_output_ratio_not_flagged(self):
        # Large input but output ratio is fine: output/input = 0.5 > 0.05
        req = _req(input_tokens=10_000, output_tokens=5_000)
        finding = ContextBloatDetector().run([req])
        assert finding.affected_count == 0

    def test_small_input_not_flagged_even_if_low_ratio(self):
        # input=100 < 8_000 threshold, output=1
        req = _req(input_tokens=100, output_tokens=1)
        finding = ContextBloatDetector().run([req])
        assert finding.affected_count == 0

    def test_high_count_returns_high_severity(self):
        bloated = [_req(input_tokens=10_000, output_tokens=50) for _ in range(11)]
        finding = ContextBloatDetector().run(bloated)
        assert finding.severity == "high"
        assert finding.affected_count == 11

    def test_examples_capped_at_three(self):
        bloated = [_req(input_tokens=10_000, output_tokens=50) for _ in range(10)]
        finding = ContextBloatDetector().run(bloated)
        assert len(finding.examples) <= 3


# ---------------------------------------------------------------------------
# DuplicateRequestDetector
# ---------------------------------------------------------------------------


class TestDuplicateRequestDetector:
    def test_empty_requests_returns_low(self):
        finding = DuplicateRequestDetector().run([])
        assert finding.severity == "low"

    def test_no_system_hash_not_counted(self):
        # Requests without system_prompt_hash should be skipped
        requests = [_req(system_prompt_hash=None) for _ in range(10)]
        finding = DuplicateRequestDetector().run(requests)
        assert finding.affected_count == 0

    def test_below_threshold_not_flagged(self):
        # MIN_OCCURRENCES = 3 — two calls with same hash should not trigger
        reqs = [_req(model="gpt-4o", system_prompt_hash="hash-a") for _ in range(2)]
        finding = DuplicateRequestDetector().run(reqs)
        assert finding.affected_count == 0

    def test_at_threshold_triggers(self):
        # Exactly 3 calls with same (model, hash) → 2 redundant calls
        reqs = [_req(model="gpt-4o", system_prompt_hash="hash-a", cost_usd=0.01) for _ in range(3)]
        finding = DuplicateRequestDetector().run(reqs)
        assert finding.affected_count == 2
        assert finding.estimated_waste_usd > 0

    def test_multiple_duplicate_pairs(self):
        reqs = (
            [_req(model="gpt-4o", system_prompt_hash="hash-a") for _ in range(5)]
            + [_req(model="gpt-4o-mini", system_prompt_hash="hash-b") for _ in range(4)]
        )
        finding = DuplicateRequestDetector().run(reqs)
        # Affected = (5-1) + (4-1) = 7
        assert finding.affected_count == 7

    def test_different_models_same_hash_treated_separately(self):
        # Same hash but different model → separate duplicate groups
        reqs = (
            [_req(model="gpt-4o", system_prompt_hash="hash-x") for _ in range(3)]
            + [_req(model="gpt-4o-mini", system_prompt_hash="hash-x") for _ in range(3)]
        )
        finding = DuplicateRequestDetector().run(reqs)
        assert finding.affected_count == 4  # (3-1) + (3-1)

    def test_high_severity_when_many_affected(self):
        reqs = [_req(model="gpt-4o", system_prompt_hash="hash-a") for _ in range(25)]
        finding = DuplicateRequestDetector().run(reqs)
        assert finding.severity == "high"  # affected > 20

    def test_medium_severity_with_some_duplicates(self):
        reqs = [_req(model="gpt-4o", system_prompt_hash="hash-b") for _ in range(5)]
        finding = DuplicateRequestDetector().run(reqs)
        assert finding.severity == "medium"  # duplicates exist but affected <= 20


# ---------------------------------------------------------------------------
# ModelOverkillDetector
# ---------------------------------------------------------------------------


class TestModelOverkillDetector:
    def test_empty_requests_returns_low(self):
        finding = ModelOverkillDetector().run([])
        assert finding.severity == "low"

    def test_cheap_model_not_flagged(self):
        # "gpt-4o-mini" is "cheap" tier → should not be flagged
        req = _req(model="gpt-4o-mini", output_tokens=50, cost_usd=0.01)
        finding = ModelOverkillDetector().run([req])
        assert finding.affected_count == 0

    def test_expensive_model_long_output_not_flagged(self):
        # "claude-opus" is expensive but output >= 200 → not overkill
        req = _req(model="claude-opus", output_tokens=300, cost_usd=0.01)
        finding = ModelOverkillDetector().run([req])
        assert finding.affected_count == 0

    def test_expensive_model_short_output_flagged(self):
        # "claude-opus" expensive + output < 200 + cost >= 0.001
        req = _req(model="claude-opus", output_tokens=50, cost_usd=0.01)
        finding = ModelOverkillDetector().run([req])
        assert finding.affected_count == 1
        assert finding.severity == "medium"

    def test_waste_is_70_percent(self):
        req = _req(model="claude-opus", output_tokens=50, cost_usd=0.10)
        finding = ModelOverkillDetector().run([req])
        assert abs(finding.estimated_waste_usd - 0.07) < 1e-9

    def test_cost_below_min_not_flagged(self):
        # cost < 0.001 should not be flagged (not meaningful)
        req = _req(model="claude-opus", output_tokens=50, cost_usd=0.0009)
        finding = ModelOverkillDetector().run([req])
        assert finding.affected_count == 0

    def test_o1_model_flagged_as_expensive(self):
        req = _req(model="o1", output_tokens=100, cost_usd=0.05)
        finding = ModelOverkillDetector().run([req])
        assert finding.affected_count == 1

    def test_o3_model_flagged_as_expensive(self):
        req = _req(model="o3-mini", output_tokens=100, cost_usd=0.005)
        finding = ModelOverkillDetector().run([req])
        assert finding.affected_count == 1

    def test_high_severity_when_many_overkill(self):
        reqs = [_req(model="claude-opus", output_tokens=50, cost_usd=0.01) for _ in range(16)]
        finding = ModelOverkillDetector().run(reqs)
        assert finding.severity == "high"

    def test_examples_capped_at_three(self):
        reqs = [_req(model="claude-opus", output_tokens=50, cost_usd=0.01) for _ in range(10)]
        finding = ModelOverkillDetector().run(reqs)
        assert len(finding.examples) <= 3

    def test_gpt4_turbo_flagged_as_expensive(self):
        req = _req(model="gpt-4-turbo", output_tokens=100, cost_usd=0.01)
        finding = ModelOverkillDetector().run([req])
        assert finding.affected_count == 1


# ---------------------------------------------------------------------------
# SystemPromptWasteDetector
# ---------------------------------------------------------------------------


class TestSystemPromptWasteDetector:
    def test_empty_requests_returns_low(self):
        finding = SystemPromptWasteDetector().run([])
        assert finding.severity == "low"

    def test_no_system_hashes_returns_low(self):
        requests = [_req(system_prompt_hash=None) for _ in range(10)]
        finding = SystemPromptWasteDetector().run(requests)
        assert finding.severity == "low"
        assert finding.affected_count == 0

    def test_few_repeats_not_flagged(self):
        # < 5 occurrences — below threshold
        reqs = [_req(system_prompt_hash="hash-a") for _ in range(4)]
        finding = SystemPromptWasteDetector().run(reqs)
        assert finding.severity == "low"

    def test_five_repeats_triggers(self):
        reqs = [_req(system_prompt_hash="hash-a", cost_usd=0.01) for _ in range(5)]
        finding = SystemPromptWasteDetector().run(reqs)
        assert finding.severity == "medium"
        assert finding.affected_count == 5

    def test_estimated_waste_is_30_percent(self):
        # 5 requests, each $0.10, total cost $0.50
        # 30% of $0.50 = $0.15
        reqs = [_req(system_prompt_hash="hash-b", cost_usd=0.10) for _ in range(5)]
        finding = SystemPromptWasteDetector().run(reqs)
        assert abs(finding.estimated_waste_usd - 0.15) < 1e-9

    def test_multiple_repeated_hashes(self):
        reqs = (
            [_req(system_prompt_hash="hash-a") for _ in range(5)]
            + [_req(system_prompt_hash="hash-b") for _ in range(7)]
        )
        finding = SystemPromptWasteDetector().run(reqs)
        assert finding.severity == "medium"
        assert finding.affected_count == 12


# ---------------------------------------------------------------------------
# run_all_detectors
# ---------------------------------------------------------------------------


class TestRunAllDetectors:
    def test_returns_four_findings(self):
        findings = run_all_detectors([])
        assert len(findings) == 4

    def test_all_low_severity_on_empty(self):
        findings = run_all_detectors([])
        for f in findings:
            assert f.severity == "low"

    def test_sorted_by_severity(self):
        # Seed data that triggers high severity for context bloat (11+ requests)
        bloated = [_req(input_tokens=10_000, output_tokens=50, cost_usd=0.01) for _ in range(12)]
        findings = run_all_detectors(bloated)
        severity_order = {"high": 0, "medium": 1, "low": 2}
        severities = [severity_order[f.severity] for f in findings]
        assert severities == sorted(severities)

    def test_correct_detector_names(self):
        findings = run_all_detectors([])
        names = {f.detector for f in findings}
        assert "ContextBloatDetector" in names
        assert "DuplicateRequestDetector" in names
        assert "ModelOverkillDetector" in names
        assert "SystemPromptWasteDetector" in names


# ---------------------------------------------------------------------------
# compute_budget_status
# ---------------------------------------------------------------------------


class TestComputeBudgetStatus:
    def test_basic_forecast(self):
        # $10 spent in 5 days of a 30-day period → daily rate = $2/day
        # forecast = $2 * 30 = $60
        ref = datetime(2026, 4, 5, 12, 0, 0, tzinfo=timezone.utc)  # day 5 of month
        status = compute_budget_status(
            spent_usd=10.0,
            budget_usd=100.0,
            period_days=30,
            reference_time=ref,
        )
        assert abs(status.forecast_usd - 60.0) < 1e-9
        assert status.spent_usd == 10.0
        assert status.budget_usd == 100.0

    def test_pct_used(self):
        ref = datetime(2026, 4, 5, tzinfo=timezone.utc)
        status = compute_budget_status(50.0, 100.0, reference_time=ref)
        assert abs(status.pct_used - 50.0) < 1e-9

    def test_no_budget_pct_used_is_none(self):
        status = compute_budget_status(50.0, None)
        assert status.pct_used is None

    def test_is_over_budget_true(self):
        ref = datetime(2026, 4, 15, tzinfo=timezone.utc)
        status = compute_budget_status(150.0, 100.0, reference_time=ref)
        assert status.is_over_budget is True

    def test_is_over_budget_false(self):
        ref = datetime(2026, 4, 15, tzinfo=timezone.utc)
        status = compute_budget_status(50.0, 100.0, reference_time=ref)
        assert status.is_over_budget is False

    def test_is_on_pace_to_exceed(self):
        # day 5 of month, spent $10 → forecast $60 > budget $50
        ref = datetime(2026, 4, 5, tzinfo=timezone.utc)
        status = compute_budget_status(10.0, 50.0, period_days=30, reference_time=ref)
        assert status.is_on_pace_to_exceed is True

    def test_is_not_on_pace_to_exceed(self):
        # day 15 of month, spent $1 → forecast $2 << budget $100
        ref = datetime(2026, 4, 15, tzinfo=timezone.utc)
        status = compute_budget_status(1.0, 100.0, period_days=30, reference_time=ref)
        assert status.is_on_pace_to_exceed is False

    def test_remaining_usd(self):
        ref = datetime(2026, 4, 10, tzinfo=timezone.utc)
        status = compute_budget_status(30.0, 100.0, reference_time=ref)
        assert abs(status.remaining_usd - 70.0) < 1e-9

    def test_remaining_usd_clamped_at_zero(self):
        ref = datetime(2026, 4, 10, tzinfo=timezone.utc)
        status = compute_budget_status(150.0, 100.0, reference_time=ref)
        assert status.remaining_usd == 0.0

    def test_no_budget_remaining_is_none(self):
        status = compute_budget_status(50.0, None)
        assert status.remaining_usd is None

    def test_has_budget_false(self):
        status = compute_budget_status(50.0, None)
        assert status.has_budget is False

    def test_has_budget_true(self):
        ref = datetime(2026, 4, 10, tzinfo=timezone.utc)
        status = compute_budget_status(50.0, 100.0, reference_time=ref)
        assert status.has_budget is True


# ---------------------------------------------------------------------------
# BudgetTracker.check_thresholds
# ---------------------------------------------------------------------------


class TestBudgetTracker:
    async def test_no_budget_configured_returns_empty(self, initialized_db: str):
        cfg = _make_config(initialized_db)  # no budgets set
        tracker = BudgetTracker(cfg, initialized_db)
        alerts = await tracker.check_thresholds()
        assert alerts == []

    async def test_below_threshold_no_alert(self, initialized_db: str):
        # Budget $10, spend $1 → 10% < 80% threshold
        cfg = _make_config(initialized_db, monthly_usd=10.0)

        record = RequestRecord(
            provider="openai", model="gpt-4o",
            request_path="/v1/chat/completions",
            cost_usd=1.0,
        )
        await insert_request(initialized_db, record)

        tracker = BudgetTracker(cfg, initialized_db)
        alerts = await tracker.check_thresholds()
        assert alerts == []

    async def test_above_80_threshold_triggers_alert(self, initialized_db: str):
        # Budget $10, spend $9 → 90% > 80% threshold
        cfg = _make_config(initialized_db, monthly_usd=10.0)

        record = RequestRecord(
            provider="openai", model="gpt-4o",
            request_path="/v1/chat/completions",
            cost_usd=9.0,
        )
        await insert_request(initialized_db, record)

        tracker = BudgetTracker(cfg, initialized_db)
        alerts = await tracker.check_thresholds()
        assert len(alerts) >= 1
        # Should have 80% and 90% thresholds crossed
        thresholds_crossed = {a.threshold for a in alerts}
        assert 80.0 in thresholds_crossed

    async def test_over_budget_triggers_100_threshold(self, initialized_db: str):
        # Budget $10, spend $11 → 110% > 100% threshold
        cfg = _make_config(initialized_db, monthly_usd=10.0)

        record = RequestRecord(
            provider="openai", model="gpt-4o",
            request_path="/v1/chat/completions",
            cost_usd=11.0,
        )
        await insert_request(initialized_db, record)

        tracker = BudgetTracker(cfg, initialized_db)
        alerts = await tracker.check_thresholds()
        thresholds_crossed = {a.threshold for a in alerts}
        assert 100.0 in thresholds_crossed

    async def test_alert_has_correct_period_fields(self, initialized_db: str):
        cfg = _make_config(initialized_db, monthly_usd=5.0)

        record = RequestRecord(
            provider="openai", model="gpt-4o",
            request_path="/v1/chat/completions",
            cost_usd=5.0,
        )
        await insert_request(initialized_db, record)

        tracker = BudgetTracker(cfg, initialized_db)
        alerts = await tracker.check_thresholds()
        assert len(alerts) >= 1
        alert = next(a for a in alerts if a.period == "monthly")
        assert alert.budget_usd == 5.0
        assert alert.spent_usd >= 5.0
        assert alert.period_start != ""

    async def test_daily_budget_checked(self, initialized_db: str):
        cfg = _make_config(initialized_db, daily_usd=1.0)

        record = RequestRecord(
            provider="openai", model="gpt-4o",
            request_path="/v1/chat/completions",
            cost_usd=0.9,  # 90% of $1 daily
        )
        await insert_request(initialized_db, record)

        tracker = BudgetTracker(cfg, initialized_db)
        alerts = await tracker.check_thresholds()
        periods = {a.period for a in alerts}
        assert "daily" in periods

    async def test_backward_compat_budget_limit_usd(self, initialized_db: str):
        """alerts.budget_limit_usd should map to monthly budget."""
        alerts_cfg = AlertsConfig(budget_limit_usd=5.0)
        cfg = BurnLensConfig(db_path=initialized_db, alerts=alerts_cfg)

        record = RequestRecord(
            provider="openai", model="gpt-4o",
            request_path="/v1/chat/completions",
            cost_usd=5.0,
        )
        await insert_request(initialized_db, record)

        tracker = BudgetTracker(cfg, initialized_db)
        alerts = await tracker.check_thresholds()
        assert len(alerts) >= 1
        assert any(a.period == "monthly" for a in alerts)
