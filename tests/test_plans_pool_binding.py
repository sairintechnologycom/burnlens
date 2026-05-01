"""Regression: burnlens_cloud.plans must NOT capture `pool` at module-import
time. The original code did `from .database import pool`, which binds to the
None value present before init_db() runs. Subsequent reassignment of
`database.pool` doesn't propagate to the plans module's local reference, so
resolve_limits() raised RuntimeError("Database pool not initialized") in
prod for any newly-signed-up workspace. See QA report 2026-05-01 evening.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path


PLANS_PATH = Path(__file__).resolve().parents[1] / "burnlens_cloud" / "plans.py"


def test_plans_does_not_directly_import_pool_symbol():
    """Static AST check — fails immediately if anyone reintroduces the bug."""
    src = PLANS_PATH.read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("database"):
            imported = {alias.name for alias in node.names}
            assert "pool" not in imported, (
                "burnlens_cloud.plans must not import `pool` directly from "
                ".database — that captures None at import time. Use "
                "execute_query (or another helper that reads database.pool "
                "at call time) instead."
            )


def test_plans_uses_execute_query():
    """Sanity: plans must route through a helper that reads pool dynamically."""
    src = PLANS_PATH.read_text()
    assert "execute_query" in src, "plans.resolve_limits must use execute_query"
