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
class CustomerBudgetsConfig:
    """Per-customer monthly budget limits."""

    default: float | None = None
    customers: dict[str, float] = field(default_factory=dict)


@dataclass
class CloudConfig:
    """Cloud sync configuration for burnlens.app SaaS backend."""

    enabled: bool = False
    api_key: str | None = None
    endpoint: str = "https://api.burnlens.app/v1/ingest"
    sync_interval_seconds: int = 60
    anonymise_prompts: bool = True


@dataclass
class TelemetryConfig:
    """OpenTelemetry export configuration."""

    enabled: bool = False
    otel_endpoint: str = "http://localhost:4317"
    service_name: str = "burnlens"


@dataclass
class AlertsConfig:
    """Alert configuration."""

    slack_webhook: str | None = None
    terminal: bool = True                  # Print alerts to the proxy terminal
    budget_limit_usd: float | None = None  # Legacy: treated as monthly limit
    per_request_limit_usd: float | None = None
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    budgets: TeamBudgetsConfig = field(default_factory=TeamBudgetsConfig)
    customer_budgets: CustomerBudgetsConfig = field(default_factory=CustomerBudgetsConfig)
    alert_recipients: list[str] = field(default_factory=list)  # Email addresses for discovery alerts


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

    # Admin API keys for billing detection (never logged or stored raw)
    openai_admin_key: str | None = None
    anthropic_admin_key: str | None = None

    # Dashboard basic auth (recommended for public deployments)
    dashboard_user: str | None = None
    dashboard_pass: str | None = None

    alerts: AlertsConfig = field(default_factory=AlertsConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    cloud: CloudConfig = field(default_factory=CloudConfig)


_FIELD_TYPES: dict[str, type] = {
    "port": int,
    "host": str,
    "db_path": str,
    "log_level": str,
    "openai_upstream": str,
    "anthropic_upstream": str,
    "google_upstream": str,
    "openai_admin_key": str,
    "anthropic_admin_key": str,
    "dashboard_user": str,
    "dashboard_pass": str,
}


def load_config(config_path: str | Path | None = None) -> BurnLensConfig:
    """Load config from YAML file, falling back to defaults for missing keys.

    Searches current directory and ~/.burnlens/ when no path given.
    Environment variable overrides (highest priority):
    - PORT: proxy port
    - BURNLENS_DB_PATH: SQLite database path
    - BURNLENS_CONFIG_PATH: YAML config file path
    - ALLOWED_ORIGINS: CORS allowed origins (comma-separated)
    - LOG_LEVEL: logging verbosity
    Admin keys can also be supplied via OPENAI_ADMIN_KEY and ANTHROPIC_ADMIN_KEY env vars.
    """
    import os

    # BURNLENS_CONFIG_PATH env var overrides the config_path argument
    if config_path is None:
        env_config = os.environ.get("BURNLENS_CONFIG_PATH")
        if env_config and Path(env_config).exists():
            config_path = Path(env_config)

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
        cfg = BurnLensConfig()
        # Apply env var overrides even when no YAML file exists
        return _apply_env_overrides(cfg)

    config_path = Path(config_path)
    if not config_path.exists():
        cfg = BurnLensConfig()
        return _apply_env_overrides(cfg)

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

    # Customer budgets — top-level "customer_budgets" key in YAML
    cust_data = data.get("customer_budgets", {}) or {}
    cust_customers: dict[str, float] = {}
    cust_default: float | None = None
    for k, v in cust_data.items():
        if k == "default":
            cust_default = float(v)
        else:
            cust_customers[str(k)] = float(v)
    customer_budgets = CustomerBudgetsConfig(
        default=cust_default,
        customers=cust_customers,
    )

    # Parse alert_recipients as a list of strings; default to empty list
    raw_recipients = alerts_data.get("alert_recipients", [])
    alert_recipients: list[str] = [str(r) for r in raw_recipients] if raw_recipients else []

    alerts = AlertsConfig(
        slack_webhook=alerts_data.get("slack_webhook"),
        terminal=bool(alerts_data.get("terminal", True)),
        budget_limit_usd=_optional_float(alerts_data.get("budget_limit_usd")),
        per_request_limit_usd=_optional_float(alerts_data.get("per_request_limit_usd")),
        budget=budget,
        budgets=team_budgets,
        customer_budgets=customer_budgets,
        alert_recipients=alert_recipients,
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

    # Telemetry config
    telem_data = data.get("telemetry", {}) or {}
    if telem_data:
        telemetry = TelemetryConfig(
            enabled=bool(telem_data.get("enabled", False)),
            otel_endpoint=str(telem_data.get("otel_endpoint", "http://localhost:4317")),
            service_name=str(telem_data.get("service_name", "burnlens")),
        )
        kwargs["telemetry"] = telemetry

    # Cloud sync config
    cloud_data = data.get("cloud", {}) or {}
    if cloud_data:
        cloud = CloudConfig(
            enabled=bool(cloud_data.get("enabled", False)),
            api_key=cloud_data.get("api_key"),
            endpoint=str(cloud_data.get("endpoint", "https://api.burnlens.app/v1/ingest")),
            sync_interval_seconds=int(cloud_data.get("sync_interval_seconds", 60)),
            anonymise_prompts=bool(cloud_data.get("anonymise_prompts", True)),
        )
        kwargs["cloud"] = cloud

    return _apply_env_overrides(BurnLensConfig(**kwargs))


def _apply_env_overrides(cfg: BurnLensConfig) -> BurnLensConfig:
    """Apply environment variable overrides (highest priority)."""
    import os

    if port_str := os.environ.get("PORT"):
        try:
            cfg.port = int(port_str)
        except ValueError:
            pass
    if db_path := os.environ.get("BURNLENS_DB_PATH"):
        cfg.db_path = db_path
    if log_level := os.environ.get("LOG_LEVEL"):
        cfg.log_level = log_level

    # Admin key env var overrides
    if openai_admin := os.environ.get("OPENAI_ADMIN_KEY"):
        cfg.openai_admin_key = openai_admin
    if anthropic_admin := os.environ.get("ANTHROPIC_ADMIN_KEY"):
        cfg.anthropic_admin_key = anthropic_admin

    # Dashboard basic auth env var overrides
    if dash_user := os.environ.get("DASHBOARD_USER"):
        cfg.dashboard_user = dash_user
    if dash_pass := os.environ.get("DASHBOARD_PASS"):
        cfg.dashboard_pass = dash_pass

    return cfg


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
