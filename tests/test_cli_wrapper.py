"""Tests for burnlens.cli_wrapper — `burnlens run` env wiring (CODE-1)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from burnlens.cli_wrapper import _build_env, run_command


def test_run_sets_env_vars_from_git_context() -> None:
    git_ctx = {
        "repo": "my-app",
        "dev": "alice@co.com",
        "branch": "pr/1247-fix-timeout",
        "pr": "1247",
    }
    env = _build_env(
        git_ctx,
        base_urls={},
        feature=None,
        team=None,
        customer=None,
        base_env={},
    )
    assert env["BURNLENS_TAG_REPO"] == "my-app"
    assert env["BURNLENS_TAG_DEV"] == "alice@co.com"
    assert env["BURNLENS_TAG_BRANCH"] == "pr/1247-fix-timeout"
    assert env["BURNLENS_TAG_PR"] == "1247"


def test_run_sets_base_url_env_vars() -> None:
    base_urls = {
        "OPENAI_BASE_URL": "http://localhost:8420/proxy/openai",
        "ANTHROPIC_BASE_URL": "http://localhost:8420/proxy/anthropic",
    }
    env = _build_env({}, base_urls, None, None, None, base_env={})
    assert env["OPENAI_BASE_URL"] == "http://localhost:8420/proxy/openai"
    assert env["ANTHROPIC_BASE_URL"] == "http://localhost:8420/proxy/anthropic"


def test_run_flags_override_git_context() -> None:
    """Explicit --feature/--team/--customer add their own BURNLENS_TAG_* vars."""
    env = _build_env(
        git_ctx={"repo": "my-app"},
        base_urls={},
        feature="chat",
        team="backend",
        customer="acme",
        base_env={},
    )
    assert env["BURNLENS_TAG_REPO"] == "my-app"
    assert env["BURNLENS_TAG_FEATURE"] == "chat"
    assert env["BURNLENS_TAG_TEAM"] == "backend"
    assert env["BURNLENS_TAG_CUSTOMER"] == "acme"


def test_run_pr_omitted_when_not_in_git_context() -> None:
    env = _build_env(
        git_ctx={"repo": "my-app", "branch": "main"},
        base_urls={},
        feature=None,
        team=None,
        customer=None,
        base_env={},
    )
    assert "BURNLENS_TAG_PR" not in env


def test_run_execs_child_command(tmp_path) -> None:
    """run_command invokes os.execvpe with the command + assembled env."""
    captured = {}

    def fake_execvpe(file, args, env):
        captured["file"] = file
        captured["args"] = args
        captured["env"] = env

    with patch("burnlens.cli_wrapper.os.execvpe", side_effect=fake_execvpe), patch(
        "burnlens.cli_wrapper.read_git_context",
        return_value={"repo": "my-app", "dev": "alice@co.com"},
    ), patch(
        "burnlens.cli_wrapper.build_env_exports",
        return_value={"OPENAI_BASE_URL": "http://localhost:8420/proxy/openai"},
    ):
        run_command(command=["claude", "--help"])

    assert captured["file"] == "claude"
    assert captured["args"] == ["claude", "--help"]
    assert captured["env"]["BURNLENS_TAG_REPO"] == "my-app"
    assert captured["env"]["OPENAI_BASE_URL"] == "http://localhost:8420/proxy/openai"


def test_run_empty_command_exits_with_usage(capsys) -> None:
    import typer

    with pytest.raises(typer.Exit):
        run_command(command=[])
    stderr = capsys.readouterr().err
    assert "Usage" in stderr
