"""YAML config loader with sensible defaults."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class AlertsConfig:
    """Alert configuration."""

    slack_webhook: str | None = None
    budget_limit_usd: float | None = None
    per_request_limit_usd: float | None = None


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
    alerts = AlertsConfig(
        slack_webhook=alerts_data.get("slack_webhook"),
        budget_limit_usd=alerts_data.get("budget_limit_usd"),
        per_request_limit_usd=alerts_data.get("per_request_limit_usd"),
    )
    kwargs["alerts"] = alerts

    return BurnLensConfig(**kwargs)
