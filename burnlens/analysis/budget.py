"""Budget tracking and forecasting."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class BudgetStatus:
    """Current budget status and forecast."""

    budget_usd: float | None        # configured limit, None if unset
    spent_usd: float                # amount spent in the period
    period_days: int                # number of days in the period
    elapsed_days: float             # days elapsed so far
    forecast_usd: float             # projected spend at end of period

    @property
    def has_budget(self) -> bool:
        return self.budget_usd is not None

    @property
    def pct_used(self) -> float | None:
        if not self.has_budget or self.budget_usd == 0:
            return None
        return (self.spent_usd / self.budget_usd) * 100.0

    @property
    def is_over_budget(self) -> bool:
        if not self.has_budget:
            return False
        return self.spent_usd >= (self.budget_usd or 0.0)

    @property
    def is_on_pace_to_exceed(self) -> bool:
        if not self.has_budget:
            return False
        return self.forecast_usd > (self.budget_usd or 0.0)

    @property
    def remaining_usd(self) -> float | None:
        if not self.has_budget:
            return None
        return max(0.0, (self.budget_usd or 0.0) - self.spent_usd)


def compute_budget_status(
    spent_usd: float,
    budget_usd: float | None,
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
    # Use day-of-month as a simple proxy for elapsed days in a monthly budget
    day_of_month = now.day
    elapsed_days = max(day_of_month, 1)

    daily_rate = spent_usd / elapsed_days if elapsed_days > 0 else 0.0
    forecast_usd = daily_rate * period_days

    return BudgetStatus(
        budget_usd=budget_usd,
        spent_usd=spent_usd,
        period_days=period_days,
        elapsed_days=float(elapsed_days),
        forecast_usd=forecast_usd,
    )
