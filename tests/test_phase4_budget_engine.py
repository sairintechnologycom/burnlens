from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
import pytest
import aiosqlite
import httpx

from burnlens.config import BurnLensConfig, BudgetPolicy, load_config
from burnlens.budget_engine import BudgetEngine, estimate_request_tokens
from burnlens.proxy.interceptor import handle_request
from burnlens.proxy.providers import get_provider_for_path
from burnlens.storage.database import init_db, insert_request
from burnlens.storage.models import RequestRecord

class _MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.captured: httpx.Request | None = None
        self._payload = payload
        self._status = status

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.captured = request
        return httpx.Response(
            status_code=self._status,
            content=json.dumps(self._payload).encode(),
            headers={"content-type": "application/json"},
        )


def _openai_payload(input_tokens: int = 10, output_tokens: int = 5) -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "gpt-4o",
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens},
    }


async def _flush() -> None:
    for _ in range(10):
        await asyncio.sleep(0.02)


def test_budget_policy_config_parsing(tmp_path):
    config_file = tmp_path / "burnlens.yaml"
    config_content = """
port: 8420
host: 127.0.0.1
budget_policies:
  - name: "DevOps Team Budget"
    scope: "team"
    target: "devops"
    limit_usd: 100.00
    period: "monthly"
  - name: "Expensive Model Cap"
    scope: "model"
    target: "gpt-4o"
    limit_usd: 50.00
    period: "daily"
"""
    config_file.write_text(config_content)
    config = load_config(config_file)
    
    assert len(config.budget_policies) == 2
    
    policy1 = config.budget_policies[0]
    assert policy1.name == "DevOps Team Budget"
    assert policy1.scope == "team"
    assert policy1.target == "devops"
    assert policy1.limit_usd == 100.00
    assert policy1.period == "monthly"
    
    policy2 = config.budget_policies[1]
    assert policy2.name == "Expensive Model Cap"
    assert policy2.scope == "model"
    assert policy2.target == "gpt-4o"
    assert policy2.limit_usd == 50.00
    assert policy2.period == "daily"


def test_estimate_request_tokens():
    # Test OpenAI/Anthropic messages format
    body = {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello world!"}
        ],
        "max_tokens": 150
    }
    in_tok, out_tok = estimate_request_tokens(json.dumps(body).encode())
    # "You are a helpful assistant.Hello world!" is 41 characters. 41 / 4 = 10 input tokens.
    assert in_tok == pytest.approx(10, abs=2)
    assert out_tok == 150

    # Test Google Gemini format
    body_gemini = {
        "contents": [
            {"role": "user", "parts": [{"text": "Hello Gemini!"}]}
        ],
        "max_completion_tokens": 200
    }
    in_tok, out_tok = estimate_request_tokens(json.dumps(body_gemini).encode())
    # "Hello Gemini!" is 13 characters. 13 / 4 = 3 -> max(10, 3) = 10 input tokens.
    assert in_tok == 10
    assert out_tok == 200


@pytest.mark.asyncio
async def test_budget_engine_matching_logic(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    
    policy = BudgetPolicy(
        name="Team Budget",
        scope="team",
        target="devops",
        limit_usd=10.0
    )
    config = BurnLensConfig(budget_policies=[policy])
    engine = BudgetEngine(config, db_path)
    
    # Matches team
    assert engine._matches_policy(policy, "gpt-4o", {"team": "devops"}) is True
    # Does not match different team
    assert engine._matches_policy(policy, "gpt-4o", {"team": "finance"}) is False
    # Does not match if tag missing
    assert engine._matches_policy(policy, "gpt-4o", {}) is False

    # Wildcard policy
    wildcard_policy = BudgetPolicy(
        name="All Teams Budget",
        scope="team",
        target="*",
        limit_usd=100.0
    )
    assert engine._matches_policy(wildcard_policy, "gpt-4o", {"team": "finance"}) is True
    assert engine._matches_policy(wildcard_policy, "gpt-4o", {"team": "devops"}) is True
    assert engine._matches_policy(wildcard_policy, "gpt-4o", {}) is False


@pytest.mark.asyncio
async def test_budget_engine_atomic_reservation_and_reconciliation(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)

    policy = BudgetPolicy(
        name="Team Budget",
        scope="team",
        target="devops",
        limit_usd=0.01,  # very tight budget
        period="daily"
    )
    config = BurnLensConfig(budget_policies=[policy])
    engine = BudgetEngine(config, db_path)

    body = json.dumps({"messages": [{"role": "user", "content": "hello"}], "max_tokens": 100}).encode()
    request_context = {"team": "devops"}

    # First reservation should be allowed
    allowed, reservation = await engine.check_and_reserve("openai", "gpt-4o", body, request_context)
    assert allowed is True
    assert reservation["estimated_cost"] > 0.0
    assert len(reservation["policies"]) == 1

    # Dynamically set limit between 1x and 2x of estimated cost
    policy.limit_usd = 1.5 * reservation["estimated_cost"]

    # Check counter value in DB
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT current_spend FROM budget_counters WHERE policy_name = ?", (policy.name,)) as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert float(row[0]) == pytest.approx(reservation["estimated_cost"])

    # Second reservation should exceed limit and be blocked
    allowed2, reservation2 = await engine.check_and_reserve("openai", "gpt-4o", body, request_context)
    assert allowed2 is False
    assert reservation2["violated_policy"].name == "Team Budget"

    # Reconcile first call (with lower actual cost)
    actual_cost = 0.0001
    await engine.reconcile(actual_cost, reservation)

    # Counter should be updated to actual cost
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT current_spend FROM budget_counters WHERE policy_name = ?", (policy.name,)) as cursor:
            row = await cursor.fetchone()
            assert float(row[0]) == pytest.approx(actual_cost)


@pytest.mark.asyncio
async def test_budget_engine_initialization_from_requests_history(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)

    # Insert a past request in the current month/day
    now = datetime.now(timezone.utc)
    await insert_request(
        db_path,
        RequestRecord(
            provider="openai",
            model="gpt-4o",
            request_path="/v1/chat",
            timestamp=now,
            input_tokens=1000,
            output_tokens=1000,
            cost_usd=50.0,
            status_code=200,
            tags={"team": "devops"}
        )
    )

    policy = BudgetPolicy(
        name="Team Budget",
        scope="team",
        target="devops",
        limit_usd=100.0,
        period="monthly"
    )
    config = BurnLensConfig(budget_policies=[policy])
    engine = BudgetEngine(config, db_path)

    body = json.dumps({"messages": [], "max_tokens": 10}).encode()
    request_context = {"team": "devops"}

    # Counter does not exist yet. Check and reserve should initialize it from requests history (50.0 spent)
    allowed, reservation = await engine.check_and_reserve("openai", "gpt-4o", body, request_context)
    assert allowed is True
    
    # Counter should equal 50.0 + estimated cost
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT current_spend FROM budget_counters WHERE policy_name = ?", (policy.name,)) as cursor:
            row = await cursor.fetchone()
            assert float(row[0]) == pytest.approx(50.0 + reservation["estimated_cost"])


@pytest.mark.asyncio
async def test_interceptor_hierarchical_budget_block(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)

    policy = BudgetPolicy(
        name="Devops Model Block",
        scope="model",
        target="gpt-4o",
        limit_usd=0.0001, # extremely small limit
        period="daily"
    )
    config = BurnLensConfig(
        db_path=db_path,
        budget_policies=[policy]
    )

    transport = _MockTransport(_openai_payload())
    client = httpx.AsyncClient(transport=transport)
    provider = get_provider_for_path("/proxy/openai/v1/chat/completions")
    body = json.dumps({"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}).encode()

    status, headers, body_out, stream = await handle_request(
        client=client,
        provider=provider,
        path="/proxy/openai/v1/chat/completions",
        method="POST",
        headers={
            "content-type": "application/json",
            "x-burnlens-tag-team": "devops",
        },
        body_bytes=body,
        query_string="",
        db_path=db_path,
        config=config,
    )

    assert status == 429
    assert stream is None
    payload = json.loads(body_out)
    assert payload["error"] == "budget_policy_exceeded"
    assert payload["policy_name"] == "Devops Model Block"
    assert payload["scope"] == "model"
    assert payload["target"] == "gpt-4o"
