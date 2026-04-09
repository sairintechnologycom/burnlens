#!/usr/bin/env python3
"""Seed the BurnLens database with realistic test data.

Usage:
    python scripts/seed_test_data.py          # 200 requests over last 7 days
    python scripts/seed_test_data.py --count 500 --days 30
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

# ── Config ──────────────────────────────────────────────────────────────

DB_PATH = str(Path.home() / ".burnlens" / "burnlens.db")

FEATURES = ["chat", "search", "summarize", "classify", "extract", "translate", "code-review"]
TEAMS = ["backend", "research", "infra", "frontend", "ml-ops"]
CUSTOMERS = ["acme-corp", "beta-user", "trial-user", "globex-inc", "initech", "hooli"]

SYSTEM_PROMPTS = [
    "You are a helpful assistant.",
    "You are a code reviewer. Be concise.",
    "Summarize the following document.",
    "Classify the user intent into one of: billing, support, sales, other.",
    "Extract structured data from the text below.",
    None,  # some requests have no system prompt
]

# Model configs: (provider, model, request_path, input_range, output_range, pricing)
MODEL_CONFIGS = [
    ("openai", "gpt-4o", "/v1/chat/completions", (200, 4000), (100, 2000), {"input": 2.50, "output": 10.00}),
    ("openai", "gpt-4o-mini", "/v1/chat/completions", (100, 2000), (50, 1000), {"input": 0.15, "output": 0.60}),
    ("openai", "o3-mini", "/v1/chat/completions", (500, 5000), (200, 3000), {"input": 1.10, "output": 4.40}),
    ("anthropic", "claude-sonnet-4-5", "/v1/messages", (300, 6000), (150, 3000), {"input": 3.00, "output": 15.00}),
    ("anthropic", "claude-haiku-4-5", "/v1/messages", (100, 2000), (50, 800), {"input": 0.80, "output": 4.00}),
    ("google", "gemini-2.0-flash", "/v1/models/gemini-2.0-flash:generateContent", (200, 3000), (100, 1500), {"input": 0.10, "output": 0.40}),
]

# Weights: gpt-4o-mini and haiku get more traffic (cheap models used more)
MODEL_WEIGHTS = [15, 30, 10, 15, 20, 10]

STATUS_CODES = [200] * 95 + [429] * 3 + [500] * 2  # 95% success, 3% rate limit, 2% error


def _cost(input_tokens: int, output_tokens: int, pricing: dict[str, float]) -> float:
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000


def _prompt_hash(prompt: str | None) -> str | None:
    if prompt is None:
        return None
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


async def seed(count: int, days: int) -> None:
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Init DB schema
    from burnlens.storage.database import init_db
    await init_db(DB_PATH)

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)

    rows = []
    for _ in range(count):
        cfg = random.choices(MODEL_CONFIGS, weights=MODEL_WEIGHTS, k=1)[0]
        provider, model, req_path, in_range, out_range, pricing = cfg

        status = random.choice(STATUS_CODES)
        input_tokens = random.randint(*in_range) if status == 200 else 0
        output_tokens = random.randint(*out_range) if status == 200 else 0
        cost = _cost(input_tokens, output_tokens, pricing) if status == 200 else 0.0

        # Spread timestamps across the time range with slight clustering during work hours
        ts = start + timedelta(seconds=random.uniform(0, days * 86400))
        # Bias toward work hours (9-18)
        if random.random() < 0.7:
            ts = ts.replace(hour=random.randint(9, 17), minute=random.randint(0, 59))

        prompt = random.choice(SYSTEM_PROMPTS)
        tags = {
            "feature": random.choice(FEATURES),
            "team": random.choice(TEAMS),
            "customer": random.choice(CUSTOMERS),
        }

        rows.append((
            ts.isoformat(),
            provider,
            model,
            req_path,
            input_tokens,
            output_tokens,
            0,  # reasoning_tokens
            0,  # cache_read_tokens
            0,  # cache_write_tokens
            round(cost, 6),
            random.randint(100, 3000) if status == 200 else random.randint(10, 100),
            status,
            json.dumps(tags),
            _prompt_hash(prompt),
        ))

    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            """
            INSERT INTO requests (
                timestamp, provider, model, request_path,
                input_tokens, output_tokens, reasoning_tokens,
                cache_read_tokens, cache_write_tokens,
                cost_usd, duration_ms, status_code,
                tags, system_prompt_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        await db.commit()

    # Summary
    total_cost = sum(r[9] for r in rows)
    print(f"Seeded {count} requests over {days} days into {DB_PATH}")
    print(f"  Total cost: ${total_cost:.2f}")
    providers = {}
    for r in rows:
        providers[r[1]] = providers.get(r[1], 0) + 1
    for p, c in sorted(providers.items()):
        print(f"  {p}: {c} requests")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed BurnLens with test data")
    parser.add_argument("--count", type=int, default=200, help="Number of requests to seed")
    parser.add_argument("--days", type=int, default=7, help="Spread requests over N days")
    args = parser.parse_args()
    asyncio.run(seed(args.count, args.days))
