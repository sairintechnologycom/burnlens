#!/usr/bin/env python3
"""Flatten burnlens/cost/pricing_data/*.json into one snapshot the frontend can import.

The Next.js app is deployed from `frontend/` as its own Vercel root, so it cannot
read the Python package's pricing files at build time. Same deal as the OpenAPI
snapshot: generate, commit, and let a test fail when it goes stale.

Regenerate after any pricing_data edit:  python scripts/build_pricing_snapshot.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "burnlens" / "cost" / "pricing_data"
OUT = ROOT / "frontend" / "src" / "data" / "llm-pricing.json"


def build() -> dict:
    providers = []
    for path in sorted(SRC.glob("*.json")):
        data = json.loads(path.read_text())
        models = [
            {"name": name, **rates}
            for name, rates in sorted(data.get("models", {}).items())
        ]
        providers.append({
            "provider": data["provider"],
            "updated": data.get("updated"),
            "models": models,
        })
    return {
        "source": "burnlens/cost/pricing_data",
        "model_count": sum(len(p["models"]) for p in providers),
        "providers": providers,
    }


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), indent=2, sort_keys=False) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
