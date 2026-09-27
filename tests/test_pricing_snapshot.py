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


def test_provider_price_provenance_is_queryable_and_in_snapshot():
    from burnlens.cost.pricing import get_model_pricing_provenance

    sonnet = get_model_pricing_provenance("anthropic", "claude-sonnet-5")
    assert sonnet == {
        "source_url": "https://www.anthropic.com/news/claude-sonnet-5",
        "effective_from": "2026-08-10",
        "verified_at": "2026-09-27",
        "pricing_confidence": "VERIFIED_PROVIDER",
    }
    assert get_model_pricing_provenance("anthropic", "unknown-model") is None

    snapshot = json.loads(SNAPSHOT.read_text())
    provider = next(p for p in snapshot["providers"] if p["provider"] == "anthropic")
    assert provider["pricing_provenance"]["claude-sonnet-5"] == sonnet

    openai = get_model_pricing_provenance("openai", "gpt-5.6-sol-2026-09-01")
    assert openai["effective_from"] == "2026-08-21"
    assert openai["minimum_valid_through"] == "2026-11-21"
    provider = next(p for p in snapshot["providers"] if p["provider"] == "openai")
    assert provider["pricing_provenance"]["gpt-5.6-sol"] == openai
