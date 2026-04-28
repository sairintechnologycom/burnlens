"""Tests for env-var tag fallback in burnlens.proxy.interceptor (CODE-1)."""
from __future__ import annotations

from burnlens.proxy.interceptor import _extract_tags


def test_proxy_reads_tag_repo_from_env_when_header_missing(monkeypatch) -> None:
    monkeypatch.setenv("BURNLENS_TAG_REPO", "my-app")
    monkeypatch.setenv("BURNLENS_TAG_DEV", "alice@co.com")
    monkeypatch.setenv("BURNLENS_TAG_PR", "1247")
    monkeypatch.setenv("BURNLENS_TAG_BRANCH", "pr/1247")

    tags = _extract_tags({})

    assert tags["repo"] == "my-app"
    assert tags["dev"] == "alice@co.com"
    assert tags["pr"] == "1247"
    assert tags["branch"] == "pr/1247"


def test_proxy_header_takes_precedence_over_env(monkeypatch) -> None:
    monkeypatch.setenv("BURNLENS_TAG_REPO", "fallback-repo")
    monkeypatch.setenv("BURNLENS_TAG_PR", "9999")

    tags = _extract_tags(
        {"x-burnlens-tag-repo": "header-repo", "x-burnlens-tag-pr": "1247"}
    )

    assert tags["repo"] == "header-repo"
    assert tags["pr"] == "1247"


def test_proxy_env_only_applies_to_known_tag_keys(monkeypatch) -> None:
    """A random BURNLENS_TAG_FOO env var must not produce a `foo` tag."""
    monkeypatch.setenv("BURNLENS_TAG_FOO", "should-not-appear")
    monkeypatch.setenv("BURNLENS_TAG_REPO", "my-app")

    tags = _extract_tags({})

    assert "foo" not in tags
    assert tags.get("repo") == "my-app"


def test_proxy_no_env_no_header_yields_empty_dict(monkeypatch) -> None:
    for key in (
        "BURNLENS_TAG_FEATURE",
        "BURNLENS_TAG_TEAM",
        "BURNLENS_TAG_CUSTOMER",
        "BURNLENS_TAG_REPO",
        "BURNLENS_TAG_DEV",
        "BURNLENS_TAG_PR",
        "BURNLENS_TAG_BRANCH",
    ):
        monkeypatch.delenv(key, raising=False)

    assert _extract_tags({}) == {}


def test_proxy_env_fallback_picks_up_at_call_time(monkeypatch) -> None:
    """Env vars are read per-request, not cached at module import time."""
    monkeypatch.delenv("BURNLENS_TAG_REPO", raising=False)
    assert "repo" not in _extract_tags({})

    monkeypatch.setenv("BURNLENS_TAG_REPO", "late-binding-app")
    assert _extract_tags({})["repo"] == "late-binding-app"
