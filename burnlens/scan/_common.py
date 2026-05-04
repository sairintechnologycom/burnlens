"""Shared helpers for disk-based scanners.

Lives in its own module so per-provider readers (claude_code.py, cursor.py,
codex.py, ...) can share the dev-identity resolution path without circular
imports between provider modules.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_DEV_IDENTITY_CACHE: dict[str, str] = {}


def _git_user_email(project_path: str) -> str | None:
    """Best-effort ``git config user.email`` lookup. Returns None on any failure."""
    if not shutil.which("git"):
        return None
    if not Path(project_path).exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", project_path, "config", "user.email"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    email = result.stdout.strip()
    return email or None


def resolve_dev_identity(project_path: str) -> str:
    """Resolve the developer identity for a project. Cached per scan run.

    Order: git ``user.email`` in ``project_path`` → ``$USER`` → ``"unknown"``.
    """
    if project_path in _DEV_IDENTITY_CACHE:
        return _DEV_IDENTITY_CACHE[project_path]

    identity = _git_user_email(project_path) or os.environ.get("USER") or "unknown"
    _DEV_IDENTITY_CACHE[project_path] = identity
    return identity


def _reset_dev_identity_cache() -> None:
    """Clear the per-run dev-identity cache. Used by scanners and tests."""
    _DEV_IDENTITY_CACHE.clear()
