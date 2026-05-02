"""Budget tracking and forecasting."""
from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from burnlens.storage.queries import get_total_cost
from burnlens.config import BurnLensConfig

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLDS = (80.0, 90.0, 100.0)


@dataclass
class BudgetStatus:
    """Current budget status and forecast."""

    budget_usd: float | None
    spent_usd: float
    period_days: int
    elapsed_days: float
    forecast_usd: float

    @property
    def has_budget(self) -> bool:
        return self.budget_usd is not None

    @property
    def pct_used(self) -> float | None:
        if not self.has_budget or self.budget_usd == 0:
            return None
        return self.spent_usd / self.budget_usd * 100.0

    @property
    def is_over_budget(self) -> bool:
        if not self.has_budget:
            return False
        return self.spent_usd > (self.budget_usd or 0.0)

    @property
    def is_on_pace_to_exceed(self) -> bool:
        if not self.has_budget:
            return False
        return self.forecast_usd > (self.budget_usd or 0.0)

    @property
    def remaining_usd(self) -> float | None:
        if not self.has_budget:
            return None
        return max(0.0, self.budget_usd - self.spent_usd)


@dataclass
class BudgetAlert:
    """A threshold crossing that should be dispatched to alert channels."""

    period: str
    budget_usd: float
    spent_usd: float
    pct_used: float
    threshold: float
    forecast_usd: float
    period_start: str


def compute_budget_status(
    spent_usd: float,
    budget_usd: float | None = None,
    period_days: int = 30,
    reference_time: datetime | None = None,
) -> BudgetStatus:
    """Compute budget status and end-of-period forecast.

    Args:
        spent_usd: Amount spent so far.
        budget_usd: Configured budget limit (None = no budget set).
        period_days: Length of the budget period in days.
        reference_time: Override 'now' for testing.
    """
    now = reference_time or datetime.now(timezone.utc)
    day_of_month = now.day
    elapsed_days = max(1, day_of_month)

    daily_rate = spent_usd / elapsed_days if elapsed_days > 0 else 0
    forecast_usd = daily_rate * period_days

    return BudgetStatus(
        budget_usd=budget_usd,
        spent_usd=spent_usd,
        period_days=period_days,
        elapsed_days=float(elapsed_days),
        forecast_usd=forecast_usd,
    )


def _period_start_iso(period: str, now: datetime) -> str:
    """Return ISO timestamp for the start of the given period."""
    if period == "daily":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "weekly":
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start.isoformat()


def _period_days(period: str, now: datetime) -> int:
    """Return total days in the budget period."""
    if period == "daily":
        return 1
    if period == "weekly":
        return 7
    return calendar.monthrange(now.year, now.month)[1]


def _elapsed_days(period: str, now: datetime) -> float:
    """Return how many days have elapsed in the current period."""
    if period == "daily":
        return (now.hour * 3600 + now.minute * 60 + now.second) / 86400 + 0.0006944444444444445
    if period == "weekly":
        return now.weekday() + 1.0
    return float(now.day)


class BudgetTracker:
    """Checks configured budget periods against actual spend and returns alerts."""

    def __init__(self, config: BurnLensConfig, db_path: str = "") -> None:
        self._config = config
        self._db_path = db_path

    def _budget_map(self) -> dict[str, float | None]:
        """Return {period: budget_usd} for all configured periods."""
        cfg = self._config
        budget_cfg = cfg.alerts.budget

        result: dict[str, float | None] = {}
        for period, value in zip(
            ("daily", "weekly", "monthly"),
            (budget_cfg.daily_usd, budget_cfg.weekly_usd, budget_cfg.monthly_usd),
        ):
            if value is not None:
                result[period] = value

        if cfg.alerts.budget_limit_usd is not None and "monthly" not in result:
            result["monthly"] = cfg.alerts.budget_limit_usd

        return result

    async def check_thresholds(
        self,
        thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
    ) -> list[BudgetAlert]:
        """Query DB spend per period and return any threshold crossings.

        Only returns alerts for thresholds the caller hasn't already seen
        (deduplication is the caller's responsibility).
        """
        budgets = self._budget_map()
        alerts: list[BudgetAlert] = []
        now = datetime.now(timezone.utc)

        for period, budget_usd in budgets.items():
            if budget_usd is None:
                continue

            since = _period_start_iso(period, now)
            try:
                spent = await get_total_cost(self._db_path, since=since)
            except Exception as exc:
                logger.warning("budget check failed for %s period: %s", period, exc)
                continue

            if spent == 0:
                continue

            total_days = _period_days(period, now)
            elapsed = _elapsed_days(period, now)
            daily_rate = spent / elapsed if elapsed > 0 else 0.0
            forecast = daily_rate * total_days
            pct = spent / budget_usd * 100.0

            for threshold in sorted(thresholds):
                if pct >= threshold:
                    alerts.append(BudgetAlert(
                        period=period,
                        budget_usd=budget_usd,
                        spent_usd=spent,
                        pct_used=pct,
                        threshold=threshold,
                        forecast_usd=forecast,
                        period_start=since,
                    ))

        return alerts
