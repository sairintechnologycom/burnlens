"""Every `burnlens <command>` printed on the site must be a real CLI command.

The marketing and docs pages are the first thing a visitor runs, and they are
edited far more often than the CLI. A page that names a command typer does not
register sends a new user straight into "No such command" on step two of the
funnel — the same failure class as `burnlens sync --now` being dead for every
user, which only a clean-machine run caught.

Not a style check: it only asserts the command exists, never how it is described.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PAGES = [
    ROOT / "frontend" / "src" / "app" / "scan" / "page.tsx",
    ROOT / "frontend" / "src" / "app" / "docs" / "scan" / "page.tsx",
    ROOT / "frontend" / "src" / "app" / "docs" / "page.tsx",
    ROOT / "frontend" / "src" / "app" / "docs" / "cli" / "page.tsx",
    ROOT / "README.md",
]

# `burnlens scan`, `burnlens report --days 30`, `burnlens check-otel`. Horizontal
# whitespace only: `pip install burnlens` at the end of a line must not swallow
# whatever word starts the next one.
INVOCATION = re.compile(r"\bburnlens[ \t]+([a-z][a-z-]*)")

# English, not typer: "every burnlens command", "the burnlens commands are".
PROSE = {"command", "commands"}


def _known_commands() -> set[str]:
    from burnlens.cli import app

    names = {
        (cmd.name or cmd.callback.__name__).replace("_", "-")
        for cmd in app.registered_commands
    }
    names |= {group.name for group in app.registered_groups if group.name}
    return names


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_documented_commands_exist(page: Path):
    if not page.exists():  # a page may be renamed; the other entries still guard
        pytest.skip(f"{page} not present")
    known = _known_commands()
    text = page.read_text()
    # "burnlens.db", "burnlens.app", "burnlens/cost/..." are not invocations.
    used = {
        m.group(1)
        for m in INVOCATION.finditer(text)
        if not text[m.start() : m.end()].startswith("burnlens.")
    }
    unknown = sorted(w for w in used if w not in known and w not in PROSE)
    assert not unknown, (
        f"{page.relative_to(ROOT)} tells the reader to run commands that do not "
        f"exist: {unknown}. Known: {sorted(known)}"
    )
