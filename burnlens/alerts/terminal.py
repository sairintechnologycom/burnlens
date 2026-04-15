"""Terminal notification for budget alerts."""
from __future__ import annotations

import logging

from burnlens.analysis.budget import BudgetAlert

logger = logging.getLogger(__name__)


def _threshold_style(pct: float) -> tuple[str, str]:
    """Return (Rich style, emoji) based on alert severity."""
    if pct >= 100:
        return ("bold red", "\U0001f534")
    if pct >= 90:
        return ("bold yellow", "\U0001f7e1")
    return ("bold cyan", "\U0001f535")


class TerminalAlert:
    """Prints budget alerts to the terminal using Rich."""

    def send(self, alert: BudgetAlert) -> None:
        """Print a formatted budget alert. Non-blocking (synchronous + fast)."""
        try:
            self._print(alert)
        except Exception as exc:
            logger.debug("terminal alert render failed: %s", exc)

    def _print(self, alert: BudgetAlert) -> None:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text

        style, icon = _threshold_style(alert.pct_used)
        console = Console(stderr=True)
        period_label = alert.period.capitalize()

        body = Text()
        body.append(f"{icon} BurnLens Budget Alert\n\n", style=style)
        body.append("Period:   ", style="bold")
        body.append(f"{period_label} (since {alert.period_start})\n")
        body.append("Spent:    ", style="bold")
        body.append(
            f"${alert.spent_usd:.4f} / ${alert.budget_usd:.2f}  "
            f"({alert.pct_used:.1f}%)\n"
        )
        body.append("Forecast: ", style="bold")
        body.append(f"${alert.forecast_usd:.4f} for full {period_label}\n")
        body.append("Threshold: ", style="bold")
        body.append(f"{alert.threshold:.0f}% crossed", style="dim")

        panel = Panel(
            body,
            title=f"[{style}]BurnLens — {period_label} Budget at {alert.pct_used:.0f}%[/]",
            border_style=f"bold {style.replace('bold ', '')}",
            expand=False,
        )
        console.print(panel)
