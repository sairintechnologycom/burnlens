"""End-to-end test fixtures: proxy lifecycle, test DB, and synthetic seed data."""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from burnlens.cost.calculator import TokenUsage, calculate_cost
from burnlens.storage.database import init_db, insert_request
from burnlens.storage.models import RequestRecord

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
E2E_PORT = 8421
E2E_HOST = "127.0.0.1"
E2E_DB_PATH = str(Path.home() / ".burnlens" / "burnlens_test.db")

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _port_is_open(host: str, port: int, timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def _make_system_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _calc_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    usage = TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens)
    return calculate_cost(provider, model, usage)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def db_path() -> str:
    """Return the path to the e2e test database."""
    return E2E_DB_PATH


@pytest_asyncio.fixture(scope="session")
async def seed_requests(db_path: str) -> int:
    """Insert 30 synthetic RequestRecord rows into the test DB.

    Covers 3 providers, 4 models, 3 features, 3 teams, 3 customers,
    a mix of streaming/non-streaming, various token counts, and
    timestamps spread across the last 14 days.

    Returns the number of rows inserted.
    """
    # Initialise schema (idempotent)
    await init_db(db_path)

    now = datetime.now(timezone.utc)
    rng = random.Random(42)  # deterministic seed for reproducibility
    inserted = 0

    for i in range(30):
        # Round-robin across providers/models
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

        # Spread timestamps across last 14 days
        days_ago = rng.uniform(0, 14)
        timestamp = now - timedelta(days=days_ago)

        cost_usd = _calc_cost(provider, model, input_tokens, output_tokens)

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
            system_prompt_hash=_make_system_hash(f"system-prompt-{i}"),
        )

        await insert_request(db_path, record)
        inserted += 1

    return inserted


@pytest.fixture(scope="session")
def start_burnlens_proxy(db_path: str) -> subprocess.Popen:
    """Launch ``burnlens start`` as a subprocess on the test port.

    Waits up to 15 seconds for the proxy to become ready, then yields the
    process.  Kills it on teardown.
    """
    env = {
        **dict(__import__("os").environ),
        "BURNLENS_DB_PATH": db_path,
    }

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "burnlens",
            "start",
            "--port", str(E2E_PORT),
            "--host", E2E_HOST,
            "--no-env",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for the proxy to start accepting connections
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if _port_is_open(E2E_HOST, E2E_PORT):
            break
        time.sleep(0.3)
    else:
        proc.kill()
        stdout, stderr = proc.communicate(timeout=5)
        raise RuntimeError(
            f"BurnLens proxy did not start within 15s.\n"
            f"stdout: {stdout.decode()}\nstderr: {stderr.decode()}"
        )

    yield proc  # type: ignore[misc]

    # Teardown: graceful shutdown then force kill
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
