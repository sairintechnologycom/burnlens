"""The committed frontend pricing snapshot must match what the generator produces.

`frontend/tests/llm-pricing.test.ts` already compares the rate tables, but the
snapshot also carries `inclusive_prompt_tokens`, derived from the Python provider
registry — which TypeScript cannot read. Registering a provider without
regenerating would ship a calculator that applies the wrong cache convention, so
guard the whole file from this side.

Regenerate with: python scripts/build_pricing_snapshot.py
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "frontend" / "src" / "data" / "llm-pricing.json"


def _build() -> dict:
    spec = importlib.util.spec_from_file_location(
        "build_pricing_snapshot", ROOT / "scripts" / "build_pricing_snapshot.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build()


def test_snapshot_is_current():
    assert json.loads(SNAPSHOT.read_text()) == _build(), (
        "frontend/src/data/llm-pricing.json is stale — "
        "run: python scripts/build_pricing_snapshot.py"
    )


def test_cache_convention_comes_from_the_registry():
    from burnlens.providers.registry import inclusive_prompt_token_providers

    snapshot = json.loads(SNAPSHOT.read_text())
    assert snapshot["inclusive_prompt_tokens"] == list(inclusive_prompt_token_providers())
