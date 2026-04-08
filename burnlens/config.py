"""YAML config loader with sensible defaults."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class EmailConfig:
    """SMTP email configuration for sending reports."""

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    from_addr: str | None = None


@dataclass
class BudgetConfig:
    """Per-period budget limits."""

    daily_usd: float | None = None
    weekly_usd: float | None = None
    monthly_usd: float | None = None


@dataclass
class TeamBudgetsConfig:
    """Per-team monthly budget limits."""

    global_usd: float | None = None
    teams: dict[str, float] = field(default_factory=dict)


@dataclass
class AlertsConfig:
    """Alert configuration."""

    slack_webhook: str | None = None
    terminal: bool = True                  # Print alerts to the proxy terminal
    budget_limit_usd: float | None = None  # Legacy: treated as monthly limit
    per_request_limit_usd: float | None = None
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    budgets: TeamBudgetsConfig = field(default_factory=TeamBudgetsConfig)


@dataclass
class BurnLensConfig:
    """BurnLens runtime configuration."""

    port: int = 8420
    host: str = "127.0.0.1"
    db_path: str = str(Path.home() / ".burnlens" / "burnlens.db")
    log_level: str = "info"

    # Provider upstream base URLs (no trailing slash)
    openai_upstream: str = "https://api.openai.com"
    anthropic_upstream: str = "https://api.anthropic.com"
    google_upstream: str = "https://generativelanguage.googleapis.com"

    alerts: AlertsConfig = field(default_factory=AlertsConfig)
    email: EmailConfig = field(default_factory=EmailConfig)


_FIELD_TYPES: dict[str, type] = {
    "port": int,
    "host": str,
    "db_path": str,
    "log_level": str,
    "openai_upstream": str,
    "anthropic_upstream": str,
    "google_upstream": str,
}


def load_config(config_path: str | Path | None = None) -> BurnLensConfig:
    """Load config from YAML file, falling back to defaults for missing keys.

    Searches current directory and ~/.burnlens/ when no path given.
    """
    if config_path is None:
        candidates = [
            Path.cwd() / "burnlens.yaml",
            Path.cwd() / "burnlens.yml",
            Path.home() / ".burnlens" / "config.yaml",
        ]
        for candidate in candidates:
            if candidate.exists():
                config_path = candidate
                break

    if config_path is None:
        return BurnLensConfig()

    config_path = Path(config_path)
    if not config_path.exists():
        return BurnLensConfig()

    with open(config_path) as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    kwargs: dict[str, Any] = {}
    for key, cast in _FIELD_TYPES.items():
        if key in data:
            kwargs[key] = cast(data[key])

    alerts_data = data.get("alerts", {}) or {}
    budget_data = alerts_data.get("budget", {}) or {}

    budget = BudgetConfig(
        daily_usd=_optional_float(budget_data.get("daily_usd")),
        weekly_usd=_optional_float(budget_data.get("weekly_usd")),
        monthly_usd=_optional_float(budget_data.get("monthly_usd")),
    )

    # Team budgets — top-level "budgets" key in YAML
    budgets_data = data.get("budgets", {}) or {}
    teams_raw = budgets_data.get("teams", {}) or {}
    team_budgets = TeamBudgetsConfig(
        global_usd=_optional_float(budgets_data.get("global")),
        teams={str(k): float(v) for k, v in teams_raw.items()},
    )

    alerts = AlertsConfig(
        slack_webhook=alerts_data.get("slack_webhook"),
        terminal=bool(alerts_data.get("terminal", True)),
        budget_limit_usd=_optional_float(alerts_data.get("budget_limit_usd")),
        per_request_limit_usd=_optional_float(alerts_data.get("per_request_limit_usd")),
        budget=budget,
        budgets=team_budgets,
    )
    kwargs["alerts"] = alerts

    # Email config
    email_data = data.get("email", {}) or {}
    if email_data:
        email = EmailConfig(
            smtp_host=email_data.get("smtp_host"),
            smtp_port=int(email_data.get("smtp_port", 587)),
            smtp_user=email_data.get("smtp_user"),
            smtp_password=email_data.get("smtp_password"),
            from_addr=email_data.get("from"),
        )
        kwargs["email"] = email

    return BurnLensConfig(**kwargs)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
