"""Alert evaluation engine -- checks cost thresholds after each request."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from dataclasses import dataclass

from burnlens.analysis.budget import BudgetAlert, BudgetTracker, DEFAULT_THRESHOLDS
from burnlens.alerts.slack import SlackWebhookAlert
from burnlens.alerts.terminal import TerminalAlert
from burnlens.keys import list_keys
from burnlens.key_budget import resolve_timezone, today_window_utc, next_midnight_in_tz
from burnlens.storage.database import (
    get_all_keys_today_spend,
    get_spend_by_customer_this_month,
    get_spend_by_team_this_month,
)
from burnlens.storage.queries import get_usage_by_model
from burnlens.config import BurnLensConfig


# CODE-2 STEP 7: per-API-key daily-cap warning thresholds.
KEY_BUDGET_THRESHOLDS: tuple[int, ...] = (50, 80, 100)


@dataclass
class TeamBudgetAlert:
    """Alert for a team exceeding its budget threshold."""

    team: str
    spent: float
    limit: float
    severity: str


@dataclass
class CustomerBudgetAlert:
    """Alert for a customer approaching or exceeding their budget."""

    customer: str
    spent: float
    limit: float
    pct: float
    severity: str


@dataclass
class KeyBudgetAlert:
    """Per-API-key daily-cap alert at the 50% / 80% / 100% threshold."""

    key_label: str
    provider: str
    spent_today: float
    daily_budget: float
    pct: float
    threshold: int      # 50, 80, or 100 — used for dedup
    severity: str       # WARNING (50, 80) | CRITICAL (100)
    resets_at: datetime
    resets_tz: str


logger = logging.getLogger(__name__)


class AlertEngine:
    """Evaluates budget thresholds and dispatches notifications.

    Designed to be called via asyncio.create_task -- it must never raise
    or block the proxy response path.

    Deduplication: each (period, threshold, period_start_date) triple is only
    alerted once per proxy process lifetime, preventing alert storms when the
    proxy is busy.
    """

    def __init__(self, config: BurnLensConfig, db_path: str) -> None:
        self._config = config
        self._db_path = db_path
        self._tracker = BudgetTracker(config)
        self._terminal = TerminalAlert()

        if config.alerts.slack_webhook:
            self._slack = SlackWebhookAlert(config.alerts.slack_webhook)
        else:
            self._slack = None

        self._fired: set = set()

    async def check_and_dispatch(self) -> None:
        """Run budget checks and dispatch any new threshold alerts.

        This method is safe to call with asyncio.create_task -- all errors
        are caught and logged.
        """
        try:
            await self._run()
        except Exception as exc:
            logger.error("AlertEngine error: %s", exc)

    async def _run(self) -> None:
        alerts = self._tracker.check_thresholds(thresholds=DEFAULT_THRESHOLDS)
        new_alerts = [a for a in alerts if not self._is_fired(a)]
        top_model = await self._get_top_model()
        for alert in new_alerts:
            self._mark_fired(alert)
            await self._dispatch(alert, top_model)

    def _is_fired(self, alert: BudgetAlert) -> bool:
        key = (alert.period, alert.threshold, alert.period_start)
        return key in self._fired

    def _mark_fired(self, alert: BudgetAlert) -> None:
        key = (alert.period, alert.threshold, alert.period_start)
        self._fired.add(key)

    async def _get_top_model(self) -> str | None:
        try:
            rows = await get_usage_by_model(self._db_path)
            if rows:
                return rows[0].model
        except Exception:
            pass
        return None

    async def check_and_dispatch_team_budgets(self) -> None:
        """Check per-team budgets and dispatch any alerts.

        Safe to call with asyncio.create_task -- all errors are caught.
        """
        try:
            await self._run_team_checks()
        except Exception as exc:
            logger.error("Team budget check error: %s", exc)

    async def _run_team_checks(self) -> None:
        alerts = await check_team_budgets(self._config, self._db_path)

        for alert in alerts:
            logger.warning(
                "Team budget %s: %s spent $%.4f / $%.2f",
                alert.severity,
                alert.team,
                alert.spent,
                alert.limit,
            )

        if not alerts:
            return

        if self._config.alerts.terminal:
            from rich.console import Console

            _console = Console(stderr=True)
            for alert in alerts:
                if alert.severity == "CRITICAL":
                    color = "red"
                else:
                    color = "yellow"
                _console.print(
                    f"[{color}][{alert.severity}][/{color}]"
                    f" Team '{alert.team}': ${alert.spent:.4f} / ${alert.limit:.2f}"
                )

    async def _dispatch(self, alert: BudgetAlert, top_model: str | None) -> None:
        """Send alert to all configured channels."""
        logger.warning(
            "Budget threshold crossed: %s period at %.1f%% ($%.4f / $%.2f)",
            alert.period,
            alert.pct_used,
            alert.spent_usd,
            alert.budget_usd,
        )

        if self._config.alerts.terminal:
            self._terminal.send(alert)

        if self._slack:
            await self._slack.send(alert, top_model)

    async def check_and_dispatch_key_budgets(self) -> None:
        """Check per-API-key daily caps and fire 50/80/100% alerts.

        Safe to call with asyncio.create_task -- all errors are caught.
        """
        try:
            await self._run_key_checks()
        except Exception as exc:
            logger.error("Key budget check error: %s", exc)

    async def _run_key_checks(self) -> None:
        alerts = await check_key_budgets(self._config, self._db_path)
        if not alerts:
            return

        new_alerts: list[KeyBudgetAlert] = []
        for alert in alerts:
            day_iso = today_window_utc(
                resolve_timezone(self._config.alerts.api_key_budgets.reset_timezone)
            )[0].date().isoformat()
            key = ("key_budget", alert.key_label, alert.threshold, day_iso)
            if key in self._fired:
                continue
            self._fired.add(key)
            new_alerts.append(alert)

        for alert in new_alerts:
            logger.warning(
                "Key budget %s: %s (%s) spent $%.4f / $%.2f (%.1f%%)",
                alert.severity,
                alert.key_label,
                alert.provider,
                alert.spent_today,
                alert.daily_budget,
                alert.pct,
            )

        if self._config.alerts.terminal:
            from rich.console import Console

            _console = Console(stderr=True)
            for alert in new_alerts:
                color = "red" if alert.severity == "CRITICAL" else "yellow"
                _console.print(
                    f"[{color}][{alert.severity}][/{color}]"
                    f" Key '{alert.key_label}' ({alert.provider}):"
                    f" ${alert.spent_today:.4f} / ${alert.daily_budget:.2f}"
                    f" ({alert.pct:.1f}%) — resets 00:00 {alert.resets_tz}"
                )

        if self._slack:
            for alert in new_alerts:
                await self._slack.send_key_budget(alert)

    async def check_and_dispatch_customer_budgets(self) -> None:
        """Check per-customer budgets and dispatch any alerts.

        Safe to call with asyncio.create_task -- all errors are caught.
        """
        try:
            await self._run_customer_checks()
        except Exception as exc:
            logger.error("Customer budget check error: %s", exc)

    async def _run_customer_checks(self) -> None:
        alerts = await check_customer_budgets(self._config, self._db_path)

        for alert in alerts:
            key = ("customer", alert.customer, alert.severity)
            if key in self._fired:
                continue
            self._fired.add(key)

            logger.warning(
                "Customer budget %s: %s spent $%.4f / $%.2f (%.1f%%)",
                alert.severity,
                alert.customer,
                alert.spent,
                alert.limit,
                alert.pct,
            )

        if not alerts:
            return

        if self._config.alerts.terminal:
            from rich.console import Console

            _console = Console(stderr=True)
            for alert in alerts:
                if alert.severity == "CRITICAL":
                    color = "red"
                else:
                    color = "yellow"
                _console.print(
                    f"[{color}][{alert.severity}][/{color}]"
                    f" Customer '{alert.customer}': ${alert.spent:.4f} / ${alert.limit:.2f}"
                    f" ({alert.pct:.1f}%)"
                )


async def check_customer_budgets(
    config: BurnLensConfig,
    db_path: str,
) -> list[CustomerBudgetAlert]:
    """Check per-customer spend against configured limits.

    Returns alerts for customers at:
    - WARNING at 80% of limit
    - CRITICAL at 100% of limit
    """
    cust_cfg = config.alerts.customer_budgets
    if not cust_cfg.customers and not cust_cfg.default:
        return []

    spend_by_customer = await get_spend_by_customer_this_month(db_path)
    alerts: list[CustomerBudgetAlert] = []

    for customer, spent in spend_by_customer.items():
        limit = cust_cfg.customers.get(customer, cust_cfg.default)
        if limit is None or limit == 0:
            continue

        pct = spent / limit * 100
        if pct >= 100:
            alerts.append(CustomerBudgetAlert(
                customer=customer,
                spent=spent,
                limit=limit,
                pct=pct,
                severity="CRITICAL",
            ))
        elif pct >= 80:
            alerts.append(CustomerBudgetAlert(
                customer=customer,
                spent=spent,
                limit=limit,
                pct=pct,
                severity="WARNING",
            ))

    return alerts


async def check_key_budgets(
    config: BurnLensConfig,
    db_path: str,
) -> list[KeyBudgetAlert]:
    """Per-API-key daily-cap thresholds at 50% / 80% / 100%.

    Returns a list of ``KeyBudgetAlert`` for every label that has crossed
    a threshold today, where "today" is measured in the configured
    ``reset_timezone``. The 100% case is a CRITICAL alert that complements
    (but does not replace) the inline 429 enforcement in the interceptor.
    """
    api_key_budgets = config.alerts.api_key_budgets
    has_caps = bool(api_key_budgets.keys) or (
        api_key_budgets.default and api_key_budgets.default.daily_usd is not None
    )
    if not has_caps:
        return []

    tz = resolve_timezone(api_key_budgets.reset_timezone)
    spend_by_label = await get_all_keys_today_spend(db_path, tz)
    if not spend_by_label:
        return []

    providers = {row["label"]: row["provider"] for row in await list_keys(db_path)}
    resets_at = next_midnight_in_tz(tz)
    tz_name = api_key_budgets.reset_timezone or "UTC"

    alerts: list[KeyBudgetAlert] = []
    for label, spent in spend_by_label.items():
        cap = api_key_budgets.daily_cap_for(label)
        if cap is None or cap <= 0:
            continue

        pct = spent / cap * 100
        # Pick the highest crossed threshold for this label.
        threshold: int | None = None
        for t in KEY_BUDGET_THRESHOLDS:
            if pct >= t:
                threshold = t
        if threshold is None:
            continue

        severity = "CRITICAL" if threshold == 100 else "WARNING"
        alerts.append(KeyBudgetAlert(
            key_label=label,
            provider=providers.get(label, "unknown"),
            spent_today=spent,
            daily_budget=cap,
            pct=pct,
            threshold=threshold,
            severity=severity,
            resets_at=resets_at,
            resets_tz=tz_name,
        ))

    return alerts


async def check_team_budgets(
    config: BurnLensConfig,
    db_path: str,
) -> list[TeamBudgetAlert]:
    """Check per-team spend against configured limits.

    Returns a list of alerts for teams that have crossed thresholds:
    - WARNING at 80% of limit
    - CRITICAL at 100% of limit
    """
    team_limits = config.alerts.budgets.teams
    if not team_limits:
        return []

    spend_by_team = await get_spend_by_team_this_month(db_path)
    alerts: list[TeamBudgetAlert] = []

    for team, limit in team_limits.items():
        spent = spend_by_team.get(team, 0.0)
        if spent >= limit:
            alerts.append(TeamBudgetAlert(
                team=team,
                spent=spent,
                limit=limit,
                severity="CRITICAL",
            ))
        elif spent >= 0.8 * limit:
            alerts.append(TeamBudgetAlert(
                team=team,
                spent=spent,
                limit=limit,
                severity="WARNING",
            ))

    return alerts
