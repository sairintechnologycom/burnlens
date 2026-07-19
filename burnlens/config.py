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
class KeyBudgetEntry:
    """Per-API-key budget thresholds.

    ``daily_usd`` is hard-enforced (HTTP 429). ``monthly_usd`` is a soft
    warning only — used for alerts but not for blocking.
    """

    daily_usd: float | None = None
    monthly_usd: float | None = None


@dataclass
class ApiKeyBudgetsConfig:
    """Per-API-key daily hard caps (CODE-2).

    ``keys`` maps a registered label → its budget. ``default`` applies to
    registered labels that don't have an explicit override. ``reset_timezone``
    is an IANA name (e.g. ``"Asia/Kolkata"``); invalid values fall back to
    UTC at startup with a logged warning.
    """

    keys: dict[str, KeyBudgetEntry] = field(default_factory=dict)
    default: KeyBudgetEntry | None = None
    reset_timezone: str = "UTC"

    def daily_cap_for(self, label: str | None) -> float | None:
        """Return the daily USD cap for a label, falling back to ``default``."""
        if not label:
            return None
        entry = self.keys.get(label)
        if entry and entry.daily_usd is not None:
            return entry.daily_usd
        if self.default and self.default.daily_usd is not None:
            return self.default.daily_usd
        return None


@dataclass
class GoogleBillingConfig:
    """Google Cloud Billing API configuration for Shadow AI discovery."""

    enabled: bool = False
    auth_mode: str = "api_key"  # "api_key" | "service_account"
    api_key: str | None = None
    service_account_json_path: str | None = None
    billing_account_id: str | None = None  # format: "XXXXXX-XXXXXX-XXXXXX"
    project_id: str | None = None
    lookback_days: int = 30


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
    terminal: bool = True
    budget_limit_usd: float | None = None
    per_request_limit_usd: float | None = None
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    budgets: TeamBudgetsConfig = field(default_factory=TeamBudgetsConfig)
    customer_budgets: CustomerBudgetsConfig = field(default_factory=CustomerBudgetsConfig)
    api_key_budgets: ApiKeyBudgetsConfig = field(default_factory=ApiKeyBudgetsConfig)
    alert_recipients: list[str] = field(default_factory=list)


@dataclass
class BudgetPolicy:
    """Policy config for hierarchical budget enforcement."""

    name: str
    scope: str  # "org", "team", "app", "customer", "model"
    target: str  # e.g., "devops", "gpt-4o", or "*" for wildcard
    limit_usd: float
    period: str = "monthly"  # "daily", "weekly", "monthly"


@dataclass
class RoutingConfig:
    """Budget-aware routing configuration."""

    budget_downgrade: bool = True
    downgrade_threshold_pct: float = 20.0
    downgrade_threshold_usd: float = 5.00
    log_downgrades: bool = True


@dataclass
class RetryConfig:
    """Automatic retry of upstream requests on transient provider failures.

    Defaults are billing-safe: only statuses where the provider rejected the
    request without processing it (429, 503) plus connection-level errors are
    retried, so a retry can never double-bill. Add 502/504 via config only if
    you accept the small chance the origin already processed the request.
    """

    enabled: bool = True
    max_retries: int = 2
    backoff_base_seconds: float = 0.5
    retry_on_status: frozenset[int] = frozenset({429, 503})


@dataclass
class CacheEmbeddingConfig:
    """Configuration for cache embedding generator."""

    provider: str = "auto"  # "openai" | "google" | "ollama" | "auto"
    model: str = "text-embedding-3-small"


@dataclass
class CacheConfig:
    """Configuration for semantic cache."""

    enabled: bool = False
    similarity_threshold: float = 0.96
    ttl_seconds: int = 86400
    embedding: CacheEmbeddingConfig = field(default_factory=CacheEmbeddingConfig)


@dataclass
class BurnLensConfig:
    """BurnLens runtime configuration."""

    port: int = 8420
    host: str = "127.0.0.1"
    db_path: str = str(Path.home() / ".burnlens" / "burnlens.db")
    wal_path: str = str(Path.home() / ".burnlens" / "wal.jsonl")
    dlq_path: str = str(Path.home() / ".burnlens" / "wal_dlq.jsonl")
    log_level: str = "info"
    openai_upstream: str = "https://api.openai.com"
    anthropic_upstream: str = "https://api.anthropic.com"
    google_upstream: str = "https://generativelanguage.googleapis.com"
    openai_admin_key: str | None = None
    anthropic_admin_key: str | None = None
    secret_key: str | None = None
    dashboard_user: str | None = None
    dashboard_pass: str | None = None
    alerts: AlertsConfig = field(default_factory=AlertsConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    cloud: CloudConfig = field(default_factory=CloudConfig)
    google_billing: GoogleBillingConfig = field(default_factory=GoogleBillingConfig)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    budget_policies: list[BudgetPolicy] = field(default_factory=list)
    cache: CacheConfig = field(default_factory=CacheConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)


_FIELD_TYPES: dict[str, type] = {
    "port": int,
    "host": str,
    "db_path": str,
    "wal_path": str,
    "dlq_path": str,
    "log_level": str,
    "openai_upstream": str,
    "anthropic_upstream": str,
    "google_upstream": str,
    "openai_admin_key": str,
    "anthropic_admin_key": str,
    "secret_key": str,
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

    env_config = os.environ.get("BURNLENS_CONFIG_PATH")
    if env_config:
        config_path = env_config

    if config_path is None:
        candidates = [
            Path("burnlens.yaml"),
            Path("burnlens.yml"),
            Path.home() / ".burnlens" / "config.yaml",
        ]
        for candidate in candidates:
            if candidate.exists():
                config_path = candidate
                break

    if config_path is None or not Path(config_path).exists():
        cfg = BurnLensConfig()
        _apply_env_overrides(cfg)
        return cfg

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    kwargs: dict[str, Any] = {}
    for key, cast in _FIELD_TYPES.items():
        if key in data:
            kwargs[key] = cast(data[key])

    # Parse alerts config
    alerts_data = data.get("alerts")
    if alerts_data:
        budget_data = alerts_data.get("budget")
        budget = BudgetConfig(
            daily_usd=_optional_float(budget_data.get("daily_usd")) if budget_data else None,
            weekly_usd=_optional_float(budget_data.get("weekly_usd")) if budget_data else None,
            monthly_usd=_optional_float(budget_data.get("monthly_usd")) if budget_data else None,
        ) if budget_data else BudgetConfig()

        budgets_data = alerts_data.get("budgets")
        if budgets_data:
            teams_raw = budgets_data.get("teams", {})
            team_budgets = TeamBudgetsConfig(
                global_usd=_optional_float(budgets_data.get("global")),
                teams={str(k): float(v) for k, v in teams_raw.items()},
            )
        else:
            team_budgets = TeamBudgetsConfig()

        cust_data = alerts_data.get("customer_budgets")
        if cust_data:
            cust_customers = cust_data.get("customers", {})
            cust_default = _optional_float(cust_data.get("default"))
            customer_budgets = CustomerBudgetsConfig(
                default=cust_default,
                customers={str(k): float(v) for k, v in cust_customers.items()},
            )
        else:
            customer_budgets = CustomerBudgetsConfig()

        api_key_data = alerts_data.get("api_key_budgets")
        if api_key_data:
            reset_tz = str(api_key_data.get("reset_timezone", "UTC"))
            entries: dict[str, KeyBudgetEntry] = {}
            default_entry: KeyBudgetEntry | None = None
            for label, raw in api_key_data.items():
                if label == "reset_timezone":
                    continue
                if not isinstance(raw, dict):
                    continue
                entry = KeyBudgetEntry(
                    daily_usd=_optional_float(raw.get("daily_usd")),
                    monthly_usd=_optional_float(raw.get("monthly_usd")),
                )
                if label == "default":
                    default_entry = entry
                else:
                    entries[str(label)] = entry
            api_key_budgets = ApiKeyBudgetsConfig(
                keys=entries,
                default=default_entry,
                reset_timezone=reset_tz,
            )
        else:
            api_key_budgets = ApiKeyBudgetsConfig()

        raw_recipients = alerts_data.get("alert_recipients", [])
        alert_recipients = [str(r) for r in raw_recipients]

        alerts = AlertsConfig(
            slack_webhook=alerts_data.get("slack_webhook"),
            terminal=bool(alerts_data.get("terminal", True)),
            budget_limit_usd=_optional_float(alerts_data.get("budget_limit_usd")),
            per_request_limit_usd=_optional_float(alerts_data.get("per_request_limit_usd")),
            budget=budget,
            budgets=team_budgets,
            customer_budgets=customer_budgets,
            api_key_budgets=api_key_budgets,
            alert_recipients=alert_recipients,
        )
        kwargs["alerts"] = alerts

    # Parse email config
    email_data = data.get("email")
    if email_data:
        email = EmailConfig(
            smtp_host=email_data.get("smtp_host"),
            smtp_port=int(email_data.get("smtp_port", 587)),
            smtp_user=email_data.get("smtp_user"),
            smtp_password=email_data.get("smtp_password"),
            from_addr=email_data.get("from"),
        )
        kwargs["email"] = email

    # Parse telemetry config
    telem_data = data.get("telemetry")
    if telem_data:
        telemetry = TelemetryConfig(
            enabled=bool(telem_data.get("enabled", False)),
            otel_endpoint=str(telem_data.get("otel_endpoint", "http://localhost:4317")),
            service_name=str(telem_data.get("service_name", "burnlens")),
        )
        kwargs["telemetry"] = telemetry

    # Parse cloud config
    cloud_data = data.get("cloud")
    if cloud_data:
        cloud = CloudConfig(
            enabled=bool(cloud_data.get("enabled", False)),
            api_key=cloud_data.get("api_key"),
            endpoint=str(cloud_data.get("endpoint", "https://api.burnlens.app/v1/ingest")),
            sync_interval_seconds=int(cloud_data.get("sync_interval_seconds", 60)),
            anonymise_prompts=bool(cloud_data.get("anonymise_prompts", True)),
        )
        kwargs["cloud"] = cloud

    # Parse google_billing config
    gb_data = data.get("google_billing")
    if gb_data:
        google_billing = GoogleBillingConfig(
            enabled=bool(gb_data.get("enabled", False)),
            auth_mode=str(gb_data.get("auth_mode", "api_key")),
            api_key=gb_data.get("api_key"),
            service_account_json_path=gb_data.get("service_account_json_path"),
            billing_account_id=gb_data.get("billing_account_id"),
            project_id=gb_data.get("project_id"),
            lookback_days=int(gb_data.get("lookback_days", 30)),
        )
        kwargs["google_billing"] = google_billing

    # Parse routing config
    routing_data = data.get("routing")
    if routing_data:
        routing = RoutingConfig(
            budget_downgrade=bool(routing_data.get("budget_downgrade", True)),
            downgrade_threshold_pct=float(routing_data.get("downgrade_threshold_pct", 20.0)),
            downgrade_threshold_usd=float(routing_data.get("downgrade_threshold_usd", 5.00)),
            log_downgrades=bool(routing_data.get("log_downgrades", True)),
        )
        kwargs["routing"] = routing

    # Parse budget policies
    policies_data = data.get("budget_policies")
    if policies_data:
        budget_policies = []
        for p in policies_data:
            if isinstance(p, dict):
                budget_policies.append(BudgetPolicy(
                    name=str(p.get("name", "unnamed")),
                    scope=str(p.get("scope", "org")),
                    target=str(p.get("target", "*")),
                    limit_usd=float(p.get("limit_usd", 0.0)),
                    period=str(p.get("period", "monthly")),
                ))
        kwargs["budget_policies"] = budget_policies

    # Parse cache config
    cache_data = data.get("cache")
    if cache_data:
        embed_data = cache_data.get("embedding") or {}
        embedding = CacheEmbeddingConfig(
            provider=str(embed_data.get("provider", "auto")),
            model=str(embed_data.get("model", "text-embedding-3-small")),
        )
        cache = CacheConfig(
            enabled=bool(cache_data.get("enabled", False)),
            similarity_threshold=float(cache_data.get("similarity_threshold", 0.96)),
            ttl_seconds=int(cache_data.get("ttl_seconds", 86400)),
            embedding=embedding,
        )
        kwargs["cache"] = cache
    else:
        kwargs["cache"] = CacheConfig()

    # Parse retry config
    retry_data = data.get("retry")
    if retry_data:
        kwargs["retry"] = RetryConfig(
            enabled=bool(retry_data.get("enabled", True)),
            max_retries=int(retry_data.get("max_retries", 2)),
            backoff_base_seconds=float(retry_data.get("backoff_base_seconds", 0.5)),
            retry_on_status=frozenset(
                int(s) for s in retry_data.get("retry_on_status", [429, 503])
            ),
        )

    cfg = BurnLensConfig(**kwargs)
    _apply_env_overrides(cfg)
    return cfg


def _apply_env_overrides(cfg: BurnLensConfig) -> BurnLensConfig:
    """Apply environment variable overrides (highest priority)."""
    import os

    port_str = os.environ.get("PORT")
    if port_str:
        try:
            cfg.port = int(port_str)
        except ValueError:
            pass

    db_path = os.environ.get("BURNLENS_DB_PATH")
    if db_path:
        cfg.db_path = db_path

    log_level = os.environ.get("LOG_LEVEL")
    if log_level:
        cfg.log_level = log_level

    openai_admin = os.environ.get("OPENAI_ADMIN_KEY")
    if openai_admin:
        cfg.openai_admin_key = openai_admin

    anthropic_admin = os.environ.get("ANTHROPIC_ADMIN_KEY")
    if anthropic_admin:
        cfg.anthropic_admin_key = anthropic_admin

    dash_user = os.environ.get("DASHBOARD_USER")
    if dash_user:
        cfg.dashboard_user = dash_user

    dash_pass = os.environ.get("DASHBOARD_PASS")
    if dash_pass:
        cfg.dashboard_pass = dash_pass

    secret_key = os.environ.get("SECRET_KEY")
    if secret_key:
        cfg.secret_key = secret_key

    return cfg


def _optional_float(value: Any) -> float | None:
    """Convert a value to float, returning None if the value is None."""
    if value is None:
        return None
    return float(value)
