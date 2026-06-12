"""Lightweight feature-flag helper module for BurnLens.

Gates new capabilities behind flags driven by environment variables.
"""
from __future__ import annotations

import os


def is_enabled(flag_name: str) -> bool:
    """Check if a feature flag is enabled.

    Looks for an environment variable named: BURNLENS_<FLAG_NAME>_ENABLED.
    Accepts truthy values: "true", "1", "yes", "on".

    Example:
        `is_enabled("otel")` checks `BURNLENS_OTEL_ENABLED`.
    """
    env_var = f"BURNLENS_{flag_name.upper()}_ENABLED"
    val = os.environ.get(env_var, "").lower()
    return val in ("true", "1", "yes", "on")
