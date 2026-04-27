#!/usr/bin/env python3
"""Standalone seed script for BurnLens.

Fires real API calls through the running proxy if API keys are present,
otherwise falls back to inserting synthetic data directly into SQLite.

Usage:
    python -m tests.e2e.seed_live          # from project root
    python tests/e2e/seed_live.py          # direct invocation
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure project root is on sys.path when invoked directly
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from burnlens.cost.calculator import TokenUsage, calculate_cost
from burnlens.storage.database import init_db, insert_request
from burnlens.storage.models import RequestRecord

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROXY_HOST = "http://127.0.0.1:8420"
DB_PATH = str(Path.home() / ".burnlens" / "burnlens.db")

OPENAI_PROXY = f"{PROXY_HOST}/proxy/openai"
ANTHROPIC_PROXY = f"{PROXY_HOST}/proxy/anthropic"

# Tag combinations for the 5 live calls
_LIVE_CALLS = [
    {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "tags": {"feature": "chat", "team": "backend", "customer": "acme-corp"},
        "prompt": "Say hello in one sentence.",
    },
    {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "tags": {"feature": "search", "team": "research", "customer": "beta-user"},
        "prompt": "What is the capital of France? One word.",
    },
    {
        "provider": "openai",
        "model": "gpt-4o",
        "tags": {"feature": "summarise", "team": "infra", "customer": "unknown-co"},
        "prompt": "Summarise what an LLM proxy does in one sentence.",
    },
    {
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
        "tags": {"feature": "chat", "team": "research", "customer": "acme-corp"},
        "prompt": "What is 2+2? Answer with just the number.",
    },
    {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "tags": {"feature": "chat", "team": "backend", "customer": "beta-user"},
        "prompt": "Name one colour. One word only.",
    },
]


# ---------------------------------------------------------------------------
# Live API calls through proxy
# ---------------------------------------------------------------------------

def _tag_headers(tags: dict[str, str]) -> dict[str, str]:
    return {f"X-BurnLens-Tag-{k}": v for k, v in tags.items()}


def _fire_openai(model: str, prompt: str, tags: dict[str, str]) -> dict:
    """Send a chat completion through the OpenAI proxy."""
    import httpx

    headers = {
        "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
        "Content-Type": "application/json",
        **_tag_headers(tags),
    }
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 50,
    }
    resp = httpx.post(
        f"{OPENAI_PROXY}/v1/chat/completions",
        headers=headers,
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    usage = data.get("usage", {})
    return {
        "model": data.get("model", model),
        "tokens_in": usage.get("prompt_tokens", 0),
        "tokens_out": usage.get("completion_tokens", 0),
        "cost_usd": calculate_cost(
            "openai",
            data.get("model", model),
            TokenUsage(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
            ),
        ),
    }


def _fire_anthropic(model: str, prompt: str, tags: dict[str, str]) -> dict:
    """Send a message through the Anthropic proxy."""
    import httpx

    headers = {
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
        **_tag_headers(tags),
    }
    body = {
        "model": model,
        "max_tokens": 50,
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = httpx.post(
        f"{ANTHROPIC_PROXY}/v1/messages",
        headers=headers,
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    usage = data.get("usage", {})
    return {
        "model": data.get("model", model),
        "tokens_in": usage.get("input_tokens", 0),
        "tokens_out": usage.get("output_tokens", 0),
        "cost_usd": calculate_cost(
            "anthropic",
            data.get("model", model),
            TokenUsage(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            ),
        ),
    }


def run_live_calls() -> int:
    """Fire 5 real API calls through the proxy. Returns number of successful calls."""
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))

    if not has_openai and not has_anthropic:
        return 0

    # Set SDK base URLs to point at the proxy
    os.environ["OPENAI_BASE_URL"] = OPENAI_PROXY
    os.environ["ANTHROPIC_BASE_URL"] = ANTHROPIC_PROXY

    count = 0
    for call in _LIVE_CALLS:
        provider = call["provider"]

        # Skip if we lack the key for this provider
        if provider == "openai" and not has_openai:
            continue
        if provider == "anthropic" and not has_anthropic:
            continue

        try:
            if provider == "openai":
                result = _fire_openai(call["model"], call["prompt"], call["tags"])
            else:
                result = _fire_anthropic(call["model"], call["prompt"], call["tags"])

            count += 1
            print(
                f"  [{count}] model={result['model']}  "
                f"tokens_in={result['tokens_in']}  "
                f"tokens_out={result['tokens_out']}  "
                f"cost_usd=${result['cost_usd']:.6f}"
            )
        except Exception as e:
            print(f"  [!] {provider}/{call['model']} failed: {e}")

    return count


# ---------------------------------------------------------------------------
# Synthetic fallback
# ---------------------------------------------------------------------------

_MODELS = {
    "openai": ["gpt-4o-mini", "gpt-4o"],
    "anthropic": ["claude-haiku-4-5-20251001"],
    "google": ["gemini-1.5-flash"],
}

_REQUEST_PATHS = {
    "openai": "/v1/chat/completions",
    "anthropic": "/v1/messages",
    "google": "/v1beta/models/gemini-1.5-flash:generateContent",
}

_FEATURES = ["chat", "search", "summarise"]
_TEAMS = ["backend", "research", "infra"]
_CUSTOMERS = ["acme-corp", "beta-user", "unknown-co"]


async def insert_synthetic(db_path: str, count: int = 30) -> int:
    """Insert synthetic RequestRecord rows directly into SQLite."""
    await init_db(db_path)

    now = datetime.now(timezone.utc)
    rng = random.Random(42)
    inserted = 0

    for i in range(count):
        provider = ["openai", "openai", "anthropic", "google"][i % 4]
        model_pool = _MODELS[provider]
        model = model_pool[i % len(model_pool)]

        feature = _FEATURES[i % len(_FEATURES)]
        team = _TEAMS[i % len(_TEAMS)]
        customer = _CUSTOMERS[i % len(_CUSTOMERS)]

        input_tokens = rng.randint(50, 8000)
        output_tokens = rng.randint(10, 500)
        streaming = rng.choice([True, False])
        duration_ms = rng.randint(200, 5000)

        days_ago = rng.uniform(0, 14)
        timestamp = now - timedelta(days=days_ago)

        usage = TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens)
        cost_usd = calculate_cost(provider, model, usage)

        record = RequestRecord(
            provider=provider,
            model=model,
            request_path=_REQUEST_PATHS[provider],
            timestamp=timestamp,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            status_code=200,
            tags={
                "feature": feature,
                "team": team,
                "customer": customer,
                "streaming": str(streaming).lower(),
            },
            system_prompt_hash=hashlib.sha256(f"system-prompt-{i}".encode()).hexdigest(),
        )

        await insert_request(db_path, record)
        inserted += 1

    return inserted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def _count_rows(db_path: str) -> int:
    import aiosqlite
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM requests")
        row = await cursor.fetchone()
        return row[0] if row else 0


def main() -> None:
    db_path = os.environ.get("BURNLENS_DB_PATH", DB_PATH)

    print(f"BurnLens seed script")
    print(f"  DB: {db_path}")
    print()

    # Try live calls first
    print("Attempting live API calls through proxy...")
    live_count = run_live_calls()

    if live_count > 0:
        print(f"\n  {live_count} live call(s) recorded via proxy.")
    else:
        print("  No API keys found — falling back to synthetic data.")

    # Always top up with synthetic data if live calls didn't cover everything
    if live_count < 30:
        synthetic_count = 30 - live_count
        print(f"\nInserting {synthetic_count} synthetic rows...")
        asyncio.run(insert_synthetic(db_path, synthetic_count))

    total = asyncio.run(_count_rows(db_path))
    print(f"\nSeed complete: {total} rows in DB")


if __name__ == "__main__":
    main()
