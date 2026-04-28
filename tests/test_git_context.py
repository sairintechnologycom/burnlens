"""Tests for burnlens.git_context (CODE-1)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from burnlens.git_context import _parse_pr, read_git_context


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_repo(path: Path, *, branch: str, email: str = "alice@co.com") -> None:
    """Initialise a git repo at ``path`` with one empty commit on ``branch``."""
    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", email], check=True
    )
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "--allow-empty", "-q", "-m", "init"],
        check=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_read_git_context_in_git_repo_returns_repo_name(tmp_path: Path) -> None:
    repo = tmp_path / "my-app"
    repo.mkdir()
    _init_repo(repo, branch="main")

    ctx = read_git_context(str(repo))

    assert ctx.get("repo") == "my-app"
    assert ctx.get("branch") == "main"
    assert ctx.get("dev") == "alice@co.com"


def test_read_git_context_outside_git_repo_returns_empty(tmp_path: Path) -> None:
    # tmp_path is not a git repo
    ctx = read_git_context(str(tmp_path))
    assert ctx == {}


def test_read_git_context_parses_pr_from_pr_slash_N_branch(tmp_path: Path) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    _init_repo(repo, branch="pr/1247-fix-timeout")

    ctx = read_git_context(str(repo))

    assert ctx.get("pr") == "1247"
    assert ctx.get("branch") == "pr/1247-fix-timeout"


def test_read_git_context_parses_pr_from_N_dash_feature_branch(tmp_path: Path) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    _init_repo(repo, branch="1247-some-feature")

    ctx = read_git_context(str(repo))

    assert ctx.get("pr") == "1247"


def test_read_git_context_parses_jira_style_branch(tmp_path: Path) -> None:
    repo = tmp_path / "app"
    repo.mkdir()
    _init_repo(repo, branch="feature/PROJ-123/billing")

    ctx = read_git_context(str(repo))

    assert ctx.get("pr") == "PROJ-123"


def test_read_git_context_missing_git_binary_returns_empty(tmp_path: Path) -> None:
    """Simulate `git` binary missing — _run_git catches FileNotFoundError."""
    with patch(
        "burnlens.git_context.subprocess.run",
        side_effect=FileNotFoundError("git not found"),
    ):
        ctx = read_git_context(str(tmp_path))
    assert ctx == {}


def test_read_git_context_timeout_returns_empty(tmp_path: Path) -> None:
    """Slow git invocation — _run_git catches TimeoutExpired."""
    with patch(
        "burnlens.git_context.subprocess.run",
        side_effect=subprocess.TimeoutExpired("git", 2),
    ):
        ctx = read_git_context(str(tmp_path))
    assert ctx == {}


# ---------------------------------------------------------------------------
# Branch-name parsing edge cases (table-driven)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "branch, expected",
    [
        ("pr/1247", "1247"),
        ("pr-1247", "1247"),
        ("pr_1247", "1247"),
        ("pr/1247-something", "1247"),
        ("feature/PROJ-123/foo", "PROJ-123"),
        ("PROJ-7", "PROJ-7"),
        ("1247-add-budgets", "1247"),
        ("main", None),
        ("feature/no-number", None),
    ],
)
def test_parse_pr_patterns(branch: str, expected: str | None) -> None:
    assert _parse_pr(branch) == expected
