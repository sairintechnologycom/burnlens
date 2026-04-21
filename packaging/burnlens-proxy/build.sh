#!/usr/bin/env bash
# Build the `burnlens` proxy package (PyPI) from a staged copy.
# This keeps the repo root pyproject.toml untouched (Railway safe).
#
# Usage:  ./packaging/burnlens-proxy/build.sh
# Output: ./dist/burnlens-<version>.tar.gz + burnlens-<version>-py3-none-any.whl

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE_DIR="$(mktemp -d)"
trap 'rm -rf "$STAGE_DIR"' EXIT

echo "▶ Staging build at $STAGE_DIR"
cp -R "$REPO_ROOT/burnlens"            "$STAGE_DIR/burnlens"
cp    "$REPO_ROOT/README.md"           "$STAGE_DIR/README.md"
cp    "$REPO_ROOT/LICENSE"             "$STAGE_DIR/LICENSE"
cp    "$REPO_ROOT/packaging/burnlens-proxy/pyproject.toml" "$STAGE_DIR/pyproject.toml"

# Drop bytecode and test artifacts from the staged source.
find "$STAGE_DIR/burnlens" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find "$STAGE_DIR/burnlens" -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
find "$STAGE_DIR/burnlens" -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true

echo "▶ Building sdist + wheel"
cd "$STAGE_DIR"
PYTHON_BIN="${PYTHON:-python3}"
"$PYTHON_BIN" -m build --sdist --wheel

echo "▶ Copying artifacts to $REPO_ROOT/dist"
mkdir -p "$REPO_ROOT/dist"
cp "$STAGE_DIR"/dist/burnlens-*.tar.gz "$REPO_ROOT/dist/"
cp "$STAGE_DIR"/dist/burnlens-*.whl    "$REPO_ROOT/dist/"

echo "✅ Build complete:"
ls -la "$REPO_ROOT/dist"/burnlens-*.{tar.gz,whl} 2>/dev/null
