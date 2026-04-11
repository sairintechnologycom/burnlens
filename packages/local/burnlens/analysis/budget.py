"""Budget tracking and forecasting.

Pure business logic (BudgetStatus, BudgetAlert, compute_budget_status) is in
burnlens_core.analysis.budget. This module re-exports those and adds the
BudgetTracker class which depends on the local SQLite database.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from burnlens_core.analysis.budget import (  # noqa: F401
    DEFAULT_THRESHOLDS,
    BudgetAlert,
    BudgetStatus,
    compute_budget_status,
    elapsed_days as _elapsed_days,
    period_days as _period_days,
    period_start_iso as _period_start_iso,
)

from burnlens.storage.queries import get_total_cost

if TYPE_CHECKING:
    from burnlens.config import BurnLensConfig

logger = logging.getLogger(__name__)


class BudgetTracker:
    """Checks configured budget periods against actual spend and returns alerts."""

    def __init__(self, config: "BurnLensConfig", db_path: str) -> None:
        self._config = config
        self._db_path = db_path

    def _budget_map(self) -> dict[str, float | None]:
        """Return {period: budget_usd} for all configured periods."""
        cfg = self._config.alerts
        budget_cfg = cfg.budget

        result: dict[str, float | None] = {
            "daily": budget_cfg.daily_usd,
            "weekly": budget_cfg.weekly_usd,
            "monthly": budget_cfg.monthly_usd,
        }

        # Backward-compat: budget_limit_usd maps to monthly if monthly not set
        if result["monthly"] is None and cfg.budget_limit_usd is not None:
            result["monthly"] = cfg.budget_limit_usd

        # Drop periods with no budget configured
        return {k: v for k, v in result.items() if v is not None}

    async def check_thresholds(
        self,
        thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
    ) -> list[BudgetAlert]:
        """Query DB spend per period and return any threshold crossings."""
        budgets = self._budget_map()
        if not budgets:
            return []

        alerts: list[BudgetAlert] = []
        now = datetime.now(timezone.utc)

        for period, budget_usd in budgets.items():
            if budget_usd is None or budget_usd <= 0:
                continue

            since = _period_start_iso(period, now)
            try:
                spent = await get_total_cost(self._db_path, since=since)
            except Exception as exc:
                logger.warning("budget check failed for %s period: %s", period, exc)
                continue

            total_days = _period_days(period, now)
            elapsed = _elapsed_days(period, now)
            daily_rate = spent / elapsed if elapsed > 0 else 0.0
            forecast = daily_rate * total_days
            pct = (spent / budget_usd) * 100.0

            for threshold in sorted(thresholds):
                if pct >= threshold:
                    alerts.append(
                        BudgetAlert(
                            period=period,
                            budget_usd=budget_usd,
                            spent_usd=spent,
                            pct_used=pct,
                            threshold=threshold,
                            forecast_usd=forecast,
                            period_start=since[:10],  # date portion only
                        )
                    )

        return alerts
