#!/usr/bin/env python3
"""Dump the FastAPI OpenAPI component schemas to a committed snapshot.

The frontend contract test (frontend/tests/contract/api-contract.test.ts) reads
this file as the backend's source of truth. Regenerate after changing any
Pydantic response_model.

IMPORTANT: regenerate against the PINNED deps in requirements.txt, not a system
interpreter that may have newer pydantic/fastapi. The JSON-schema output is
version-sensitive (e.g. pydantic 2.7 -> 2.13 adds `additionalProperties`/`ctx`/
`input` fields), so a snapshot built with unpinned deps fails CI's
snapshot-freshness gate, which runs `pip install -r requirements.txt` first.

    # Canonical (matches CI): build a venv from the pinned requirements
    python3.11 -m venv /tmp/bl-venv && /tmp/bl-venv/bin/pip install -r requirements.txt
    /tmp/bl-venv/bin/python scripts/dump_openapi.py

app.openapi() does NOT open a DB connection (the pool is created in the FastAPI
lifespan, which this does not trigger), so this runs offline.
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Ensure the repo root is importable when run as `python scripts/dump_openapi.py`
# (which otherwise puts only scripts/ on sys.path) and in CI where the package
# is not pip-installed.
sys.path.insert(0, str(REPO_ROOT))

from burnlens_cloud.main import app  # noqa: E402  (import after sys.path setup)

SNAPSHOT = REPO_ROOT / "frontend" / "tests" / "contract" / "openapi-schemas.snapshot.json"


def main() -> None:
    schemas = app.openapi()["components"]["schemas"]
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    # Sort keys for a stable, diff-friendly snapshot.
    SNAPSHOT.write_text(json.dumps(schemas, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {len(schemas)} schemas to {SNAPSHOT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
