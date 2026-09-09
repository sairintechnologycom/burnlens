"""Read git context (repo, branch, dev, pr) from the working directory.

Used by :mod:`burnlens.cli_wrapper` to auto-tag every proxied request
with PR / repo / branch / dev attribution — zero manual configuration.

Failure modes are silent: if ``git`` is missing, or the cwd is not a git
repo, or any subprocess raises / times out, we return an empty dict.
The proxy must never block on git reads.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

# Branch-name → PR-number patterns, evaluated in order. First match wins.
_PR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(?:^|/)pr[/_-](\d+)(?:[/_-]|$)"),     # pr/1247, pr-1247, pr_1247
    re.compile(r"(?i)(?:^|/)([A-Z][A-Z0-9]+-\d+)(?:[/_-]|$)"),  # PROJ-123 anywhere
    re.compile(r"^(\d+)[-_]"),                              # 1247-some-feature
)

_GIT_TIMEOUT = 2  # seconds; never block the wrapper on a slow repo


def _run_git(cwd: str, *args: str) -> str | None:
    """Run a git subcommand and return stdout stripped, or None on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _parse_pr(branch: str) -> str | None:
    """Extract a PR / ticket identifier from a branch name."""
    for pattern in _PR_PATTERNS:
        match = pattern.search(branch)
        if match:
            return match.group(1)
    return None


def _repo_identity(remote: str | None) -> str | None:
    """Return a canonical remote identity while leaving display names local."""
    if not remote:
        return None
    value = remote.strip()
    if value.startswith("git@") and ":" in value:
        host, path = value[4:].split(":", 1)
    else:
        parsed = urlsplit(value)
        host, path = parsed.hostname, parsed.path
    if not host or not path:
        return None
    path = path.strip("/").removesuffix(".git")
    if not path:
        return None
    return f"{host.lower()}/{path.lower()}"


def read_git_context(cwd: str | None = None) -> dict[str, str]:
    """Return ``{repo, branch, dev, pr, commit_sha}`` derived from the cwd's git state.

    Keys are omitted when not available. Never raises.
    """
    target = cwd or os.getcwd()
    if not Path(target).is_dir():
        return {}

    toplevel = _run_git(target, "rev-parse", "--show-toplevel")
    if not toplevel:
        return {}

    ctx: dict[str, str] = {"repo": Path(toplevel).name}

    remote = _run_git(target, "config", "--get", "remote.origin.url")
    repo_id = _repo_identity(remote)
    if repo_id:
        ctx["repo_id"] = repo_id

    branch = _run_git(target, "rev-parse", "--abbrev-ref", "HEAD")
    if branch and branch != "HEAD":
        ctx["branch"] = branch
        pr = _parse_pr(branch)
        if pr:
            ctx["pr"] = pr

    dev = _run_git(target, "config", "user.email")
    if dev:
        ctx["dev"] = dev

    sha = _run_git(target, "rev-parse", "HEAD")
    if sha:
        ctx["commit_sha"] = sha

    return ctx
