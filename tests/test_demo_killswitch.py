"""CODE-2 STEP 10: docs/demo_killswitch.sh structural sanity checks.

We don't run the script in tests (it needs real API keys + outbound network),
but we do guarantee the on-disk artifact stays runnable: shebang, executable
bit, syntactic bash, and the contract pieces the README points users to.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parent.parent / "docs" / "demo_killswitch.sh"


def test_script_exists() -> None:
    assert SCRIPT.is_file(), f"expected demo at {SCRIPT}"


def test_script_is_executable() -> None:
    mode = SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, "owner execute bit must be set"


def test_script_has_bash_shebang() -> None:
    first_line = SCRIPT.read_text().splitlines()[0]
    assert first_line.startswith("#!"), "first line must be a shebang"
    assert "bash" in first_line, f"expected bash shebang, got: {first_line}"


def test_script_uses_strict_mode() -> None:
    body = SCRIPT.read_text()
    assert re.search(r"^set -euo pipefail\b", body, re.MULTILINE), (
        "demo must `set -euo pipefail` so cleanup trap fires on partial failure"
    )


def test_script_parses_with_bash_n() -> None:
    bash = shutil.which("bash")
    if bash is None:  # pragma: no cover — bash always present on dev machines
        pytest.skip("bash not on PATH")
    result = subprocess.run([bash, "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_script_pins_default_cap_to_five_cents() -> None:
    """Spec calls for $0.05 cap; the README screenshot promise depends on it."""
    body = SCRIPT.read_text()
    assert re.search(r'CAP="\$\{CAP:-0\.05\}"', body), (
        "default daily cap must be 0.05 USD"
    )


def test_script_invokes_burnlens_keys_for_rollup() -> None:
    """The demo must show the same panel the user will screenshot."""
    body = SCRIPT.read_text()
    assert "burnlens keys" in body
    assert "/api/keys-today" in body, "comment should cite the matching endpoint"


def test_script_handles_missing_api_key(tmp_path: Path) -> None:
    """Empty env must abort with a clear error before any side effect."""
    bash = shutil.which("bash")
    if bash is None:  # pragma: no cover
        pytest.skip("bash not on PATH")

    env = {"PATH": os.environ.get("PATH", ""), "PROVIDER": "openai"}
    result = subprocess.run(
        [bash, str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode != 0
    assert "OPENAI_API_KEY" in (result.stderr + result.stdout)


def test_script_rejects_unknown_provider(tmp_path: Path) -> None:
    bash = shutil.which("bash")
    if bash is None:  # pragma: no cover
        pytest.skip("bash not on PATH")

    env = {
        "PATH": os.environ.get("PATH", ""),
        "PROVIDER": "deepseek",
    }
    result = subprocess.run(
        [bash, str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode != 0
    assert "Unsupported PROVIDER" in (result.stderr + result.stdout)
