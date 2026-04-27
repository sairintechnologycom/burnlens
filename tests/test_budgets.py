"""Tests for per-team budget limits and alerts."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from burnlens.alerts.engine import TeamBudgetAlert, check_team_budgets
from burnlens.config import (
    AlertsConfig,
    BudgetConfig,
    BurnLensConfig,
    TeamBudgetsConfig,
)
from burnlens.storage.database import (
    get_spend_by_team_this_month,
    insert_request,
)
from burnlens.storage.models import RequestRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    db_path: str,
    global_usd: float | None = None,
    teams: dict[str, float] | None = None,
    budget_limit_usd: float | None = None,
) -> BurnLensConfig:
    budgets = TeamBudgetsConfig(
        global_usd=global_usd,
        teams=teams or {},
    )
    alerts = AlertsConfig(
        budgets=budgets,
        budget_limit_usd=budget_limit_usd,
    )
    return BurnLensConfig(db_path=db_path, alerts=alerts)


async def _insert_team_request(
    db_path: str,
    team: str,
    cost_usd: float,
) -> None:
    record = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        cost_usd=cost_usd,
        tags={"team": team},
    )
    await insert_request(db_path, record)


# ---------------------------------------------------------------------------
# test_team_budget_warning_at_80_percent
# ---------------------------------------------------------------------------


class TestTeamBudgetWarningAt80Percent:
    async def test_warning_fires_at_80_pct(self, initialized_db: str) -> None:
        """Spending 80%+ of a team's limit triggers a WARNING alert."""
        cfg = _make_config(initialized_db, teams={"backend": 100.0})

        # Spend $85 → 85% > 80% threshold
        await _insert_team_request(initialized_db, "backend", 85.0)

        alerts = await check_team_budgets(cfg, initialized_db)
        assert len(alerts) == 1
        assert alerts[0].team == "backend"
        assert alerts[0].severity == "WARNING"
        assert alerts[0].spent == 85.0
        assert alerts[0].limit == 100.0


# ---------------------------------------------------------------------------
# test_team_budget_critical_at_100_percent
# ---------------------------------------------------------------------------


class TestTeamBudgetCriticalAt100Percent:
    async def test_critical_fires_at_100_pct(self, initialized_db: str) -> None:
        """Spending >= 100% of a team's limit triggers a CRITICAL alert."""
        cfg = _make_config(initialized_db, teams={"research": 50.0})

        # Spend exactly $50 → 100%
        await _insert_team_request(initialized_db, "research", 50.0)

        alerts = await check_team_budgets(cfg, initialized_db)
        assert len(alerts) == 1
        assert alerts[0].severity == "CRITICAL"
        assert alerts[0].spent == 50.0

    async def test_critical_fires_over_100_pct(self, initialized_db: str) -> None:
        """Spending well over 100% is still CRITICAL."""
        cfg = _make_config(initialized_db, teams={"research": 50.0})

        await _insert_team_request(initialized_db, "research", 75.0)

        alerts = await check_team_budgets(cfg, initialized_db)
        assert len(alerts) == 1
        assert alerts[0].severity == "CRITICAL"


# ---------------------------------------------------------------------------
# test_team_budget_ok_below_threshold
# ---------------------------------------------------------------------------


class TestTeamBudgetOkBelowThreshold:
    async def test_no_alert_below_80_pct(self, initialized_db: str) -> None:
        """Spending below 80% produces no alert."""
        cfg = _make_config(initialized_db, teams={"infra": 100.0})

        # Spend $50 → 50% < 80%
        await _insert_team_request(initialized_db, "infra", 50.0)

        alerts = await check_team_budgets(cfg, initialized_db)
        assert alerts == []

    async def test_no_alert_with_zero_spend(self, initialized_db: str) -> None:
        """A team with no spend produces no alert."""
        cfg = _make_config(initialized_db, teams={"infra": 100.0})

        alerts = await check_team_budgets(cfg, initialized_db)
        assert alerts == []


# ---------------------------------------------------------------------------
# test_global_budget_fallback_when_no_team_config
# ---------------------------------------------------------------------------


class TestGlobalBudgetFallback:
    async def test_no_alerts_when_no_teams_configured(self, initialized_db: str) -> None:
        """With no teams configured, check_team_budgets returns empty."""
        cfg = _make_config(initialized_db, global_usd=500.0, teams={})

        await _insert_team_request(initialized_db, "backend", 400.0)

        alerts = await check_team_budgets(cfg, initialized_db)
        assert alerts == []

    async def test_team_budgets_config_empty_by_default(self) -> None:
        """Default config has no team budgets."""
        cfg = BurnLensConfig()
        assert cfg.alerts.budgets.teams == {}
        assert cfg.alerts.budgets.global_usd is None


# ---------------------------------------------------------------------------
# test_get_spend_by_team_this_month_correct_math
# ---------------------------------------------------------------------------


class TestGetSpendByTeamThisMonth:
    async def test_aggregates_multiple_requests(self, initialized_db: str) -> None:
        """Spend is summed correctly across multiple requests for the same team."""
        await _insert_team_request(initialized_db, "backend", 10.0)
        await _insert_team_request(initialized_db, "backend", 20.0)
        await _insert_team_request(initialized_db, "backend", 5.50)

        spend = await get_spend_by_team_this_month(initialized_db)
        assert abs(spend["backend"] - 35.50) < 1e-6

    async def test_separate_teams(self, initialized_db: str) -> None:
        """Different teams are tracked independently."""
        await _insert_team_request(initialized_db, "backend", 10.0)
        await _insert_team_request(initialized_db, "research", 25.0)

        spend = await get_spend_by_team_this_month(initialized_db)
        assert abs(spend["backend"] - 10.0) < 1e-6
        assert abs(spend["research"] - 25.0) < 1e-6

    async def test_untagged_requests_excluded(self, initialized_db: str) -> None:
        """Requests without a team tag don't appear in the result."""
        # Insert a request with no team tag
        record = RequestRecord(
            provider="openai",
            model="gpt-4o",
            request_path="/v1/chat/completions",
            cost_usd=100.0,
        )
        await insert_request(initialized_db, record)

        spend = await get_spend_by_team_this_month(initialized_db)
        assert spend == {}

    async def test_empty_db_returns_empty(self, initialized_db: str) -> None:
        """Empty database returns empty dict."""
        spend = await get_spend_by_team_this_month(initialized_db)
        assert spend == {}

    async def test_multiple_teams_with_alerts(self, initialized_db: str) -> None:
        """Integration: multiple teams at different threshold levels."""
        cfg = _make_config(
            initialized_db,
            teams={"backend": 200.0, "research": 100.0, "infra": 50.0},
        )

        await _insert_team_request(initialized_db, "backend", 167.23)  # 83.6% → WARNING
        await _insert_team_request(initialized_db, "research", 12.10)  # 12.1% → OK
        await _insert_team_request(initialized_db, "infra", 55.00)    # 110% → CRITICAL

        alerts = await check_team_budgets(cfg, initialized_db)
        alert_map = {a.team: a for a in alerts}

        assert "backend" in alert_map
        assert alert_map["backend"].severity == "WARNING"

        assert "research" not in alert_map  # OK, no alert

        assert "infra" in alert_map
        assert alert_map["infra"].severity == "CRITICAL"
