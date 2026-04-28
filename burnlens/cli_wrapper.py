"""``burnlens run`` command — auto-tag a child process via env vars + execvpe.

Reads :func:`burnlens.git_context.read_git_context` from the cwd, sets
``BURNLENS_TAG_*`` env vars and ``OPENAI_BASE_URL`` / ``ANTHROPIC_BASE_URL``,
then ``execvpe``-s the child command. The proxy reads the BURNLENS_TAG_*
env vars per-request via the env-fallback path in
:mod:`burnlens.proxy.interceptor`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import typer

from burnlens.config import load_config
from burnlens.git_context import read_git_context
from burnlens.proxy.providers import build_env_exports


def _build_env(
    git_ctx: dict[str, str],
    base_urls: dict[str, str],
    feature: Optional[str],
    team: Optional[str],
    customer: Optional[str],
    base_env: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Build the env mapping the child process should see.

    Explicit flags override the corresponding git-context values. The
    returned dict is a *new* dict; the input ``base_env`` is not mutated.
    """
    env = dict(base_env if base_env is not None else os.environ)

    for key, env_name in (
        ("repo", "BURNLENS_TAG_REPO"),
        ("dev", "BURNLENS_TAG_DEV"),
        ("branch", "BURNLENS_TAG_BRANCH"),
        ("pr", "BURNLENS_TAG_PR"),
    ):
        if key in git_ctx:
            env[env_name] = git_ctx[key]

    if feature:
        env["BURNLENS_TAG_FEATURE"] = feature
    if team:
        env["BURNLENS_TAG_TEAM"] = team
    if customer:
        env["BURNLENS_TAG_CUSTOMER"] = customer

    env.update(base_urls)
    return env


def _summary_line(git_ctx: dict[str, str]) -> str:
    parts = []
    for key in ("repo", "dev", "pr", "branch"):
        if key in git_ctx:
            parts.append(f"{key}={git_ctx[key]}")
    if not parts:
        return "BurnLens: tagging (no git context detected)"
    return "BurnLens: tagging as " + " ".join(parts)


def run_command(
    command: list[str],
    config: Optional[Path] = None,
    feature: Optional[str] = None,
    team: Optional[str] = None,
    customer: Optional[str] = None,
) -> None:
    """Wire up env vars + base URLs and ``execvpe`` the child command.

    On success this never returns (the child replaces the process).
    """
    if not command:
        typer.echo("Usage: burnlens run -- <command> [args...]", err=True)
        raise typer.Exit(code=2)

    cfg = load_config(config)
    git_ctx = read_git_context()
    base_urls = build_env_exports(cfg.host, cfg.port)

    env = _build_env(git_ctx, base_urls, feature, team, customer)

    print(_summary_line(git_ctx), file=sys.stderr, flush=True)

    os.execvpe(command[0], command, env)
