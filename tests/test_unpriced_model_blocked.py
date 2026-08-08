"""Unpriced models must not be forwarded under a budget that cannot enforce.

A model absent from the pricing data costs $0 as far as BurnLens is concerned,
so its spend never advances any counter and a cap over it silently enforces
nothing. These tests pin the fail-closed behaviour and, just as importantly,
pin that traffic with *no* budget attached is still allowed through.
"""
from __future__ import annotations

import json

import httpx
import pytest

from burnlens.budget_engine import BudgetEngine
from burnlens.config import (
    ApiKeyBudgetsConfig,
    BudgetPolicy,
    BurnLensConfig,
    CustomerBudgetsConfig,
    KeyBudgetEntry,
)
from burnlens.cost.calculator import is_model_priced
from burnlens.keys import register_key
from burnlens.proxy.interceptor import handle_request
from burnlens.proxy.providers import get_provider_for_path
from burnlens.key_budget import spend_cache as global_spend_cache

# Not in openai.json. Deliberately shares no prefix with any real entry:
# get_model_pricing falls back to longest-prefix matching, so "gpt-4o-anything"
# would resolve to gpt-4o and this file would silently test nothing.
UNPRICED_MODEL = "zzz-not-a-real-model-v0"
PRICED_MODEL = "gpt-4o"

PATH = "/proxy/openai/v1/chat/completions"


class _MockTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.captured: httpx.Request | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.captured = request
        return httpx.Response(
            status_code=200,
            content=json.dumps({
                "id": "chatcmpl-test",
                "model": UNPRICED_MODEL,
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }).encode(),
            headers={"content-type": "application/json"},
        )


@pytest.fixture(autouse=True)
def _reset_cache():
    global_spend_cache.clear()
    yield
    global_spend_cache.clear()


def _body(model: str) -> bytes:
    return json.dumps({"model": model, "messages": [{"role": "user", "content": "hi"}]}).encode()


async def _call(
    db_path: str,
    model: str,
    *,
    headers: dict[str, str] | None = None,
    api_key_budgets: ApiKeyBudgetsConfig | None = None,
    customer_budgets: CustomerBudgetsConfig | None = None,
    config: BurnLensConfig | None = None,
):
    transport = _MockTransport()
    client = httpx.AsyncClient(transport=transport)
    provider = get_provider_for_path(PATH)
    base = {"content-type": "application/json"}
    base.update(headers or {})
    status, _, body_out, _ = await handle_request(
        client=client,
        provider=provider,
        path=PATH,
        method="POST",
        headers=base,
        body_bytes=_body(model),
        query_string="",
        db_path=db_path,
        api_key_budgets=api_key_budgets,
        customer_budgets=customer_budgets,
        config=config,
    )
    await client.aclose()
    return status, body_out, transport


def test_pricing_fixture_assumptions_hold() -> None:
    """Guards the whole file: if these flip, every test below is vacuous."""
    assert is_model_priced("openai", PRICED_MODEL)
    assert not is_model_priced("openai", UNPRICED_MODEL)


def test_is_model_priced_handles_bedrock_geo_prefix() -> None:
    """resolve_pricing strips the geo prefix, so the two must agree."""
    from burnlens.cost.calculator import TokenUsage, calculate_cost

    model = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    if calculate_cost("bedrock", model, TokenUsage(input_tokens=1000)) > 0:
        assert is_model_priced("bedrock", model)


# ---------------------------------------------------------------------------
# Per-API-key daily cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unpriced_model_blocked_under_daily_cap(initialized_db: str) -> None:
    raw_key = "sk-test-capped-key"
    await register_key(initialized_db, "capped-key", "openai", raw_key)
    status, body_out, transport = await _call(
        initialized_db,
        UNPRICED_MODEL,
        headers={"authorization": f"Bearer {raw_key}"},
        api_key_budgets=ApiKeyBudgetsConfig(
            keys={"capped-key": KeyBudgetEntry(daily_usd=5.00)}
        ),
    )

    assert status == 403
    assert transport.captured is None, "must NOT forward upstream"
    payload = json.loads(body_out)
    assert payload["error"] == "unpriced_model_blocked"
    assert payload["model"] == UNPRICED_MODEL


@pytest.mark.asyncio
async def test_unpriced_model_allowed_when_key_has_no_cap(initialized_db: str) -> None:
    """No cap, nothing to defeat — availability wins."""
    raw_key = "sk-test-uncapped-key"
    await register_key(initialized_db, "uncapped-key", "openai", raw_key)
    status, _, transport = await _call(
        initialized_db,
        UNPRICED_MODEL,
        headers={"authorization": f"Bearer {raw_key}"},
        api_key_budgets=ApiKeyBudgetsConfig(keys={}),
    )

    assert status == 200
    assert transport.captured is not None


@pytest.mark.asyncio
async def test_priced_model_passes_under_daily_cap(initialized_db: str) -> None:
    raw_key = "sk-test-capped-key"
    await register_key(initialized_db, "capped-key", "openai", raw_key)
    status, _, transport = await _call(
        initialized_db,
        PRICED_MODEL,
        headers={"authorization": f"Bearer {raw_key}"},
        api_key_budgets=ApiKeyBudgetsConfig(
            keys={"capped-key": KeyBudgetEntry(daily_usd=5.00)}
        ),
    )

    assert status == 200
    assert transport.captured is not None


@pytest.mark.asyncio
async def test_default_cap_also_blocks(initialized_db: str) -> None:
    """A cap inherited from `default` is just as unenforceable."""
    raw_key = "sk-test-inherits-default"
    await register_key(initialized_db, "inherits-default", "openai", raw_key)
    status, body_out, transport = await _call(
        initialized_db,
        UNPRICED_MODEL,
        headers={"authorization": f"Bearer {raw_key}"},
        api_key_budgets=ApiKeyBudgetsConfig(default=KeyBudgetEntry(daily_usd=2.00)),
    )

    assert status == 403
    assert transport.captured is None
    assert json.loads(body_out)["error"] == "unpriced_model_blocked"


# ---------------------------------------------------------------------------
# Customer budgets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unpriced_model_blocked_under_customer_budget(initialized_db: str) -> None:
    status, body_out, transport = await _call(
        initialized_db,
        UNPRICED_MODEL,
        headers={"x-burnlens-tag-customer": "acme"},
        customer_budgets=CustomerBudgetsConfig(customers={"acme": 100.0}),
    )

    assert status == 403
    assert transport.captured is None
    assert json.loads(body_out)["error"] == "unpriced_model_blocked"


@pytest.mark.asyncio
async def test_unpriced_model_allowed_when_customer_uncapped(initialized_db: str) -> None:
    status, _, transport = await _call(
        initialized_db,
        UNPRICED_MODEL,
        headers={"x-burnlens-tag-customer": "acme"},
        customer_budgets=CustomerBudgetsConfig(customers={"other": 100.0}),
    )

    assert status == 200
    assert transport.captured is not None


# ---------------------------------------------------------------------------
# Budget policies — the path that used to return "allowed" on a $0 estimate
# ---------------------------------------------------------------------------


def _policy_config(db_path: str, **kw) -> BurnLensConfig:
    return BurnLensConfig(
        db_path=db_path,
        budget_policies=[
            BudgetPolicy(name="team-cap", scope="team", target="platform", limit_usd=50.0)
        ],
        **kw,
    )


@pytest.mark.asyncio
async def test_unpriced_model_blocked_by_budget_policy(initialized_db: str) -> None:
    status, body_out, transport = await _call(
        initialized_db,
        UNPRICED_MODEL,
        headers={"x-burnlens-tag-team": "platform"},
        config=_policy_config(initialized_db),
    )

    assert status == 403
    assert transport.captured is None
    assert json.loads(body_out)["error"] == "unpriced_model_blocked"


@pytest.mark.asyncio
async def test_unpriced_model_allowed_when_no_policy_matches(initialized_db: str) -> None:
    status, _, transport = await _call(
        initialized_db,
        UNPRICED_MODEL,
        headers={"x-burnlens-tag-team": "unrelated"},
        config=_policy_config(initialized_db),
    )

    assert status == 200
    assert transport.captured is not None


@pytest.mark.asyncio
async def test_check_and_reserve_reports_unpriced(initialized_db: str) -> None:
    """The engine, not the interceptor, is where the $0 bypass lived."""
    engine = BudgetEngine(_policy_config(initialized_db), initialized_db)
    allowed, reservation = await engine.check_and_reserve(
        "openai", UNPRICED_MODEL, _body(UNPRICED_MODEL), {"team": "platform"}
    )

    assert allowed is False
    assert reservation["unpriced"] is True


# ---------------------------------------------------------------------------
# Escape hatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_block_unpriced_models_false_allows_through(initialized_db: str) -> None:
    """Opt out when a provider ships a model before BurnLens ships its price."""
    raw_key = "sk-test-capped-key"
    await register_key(initialized_db, "capped-key", "openai", raw_key)
    status, _, transport = await _call(
        initialized_db,
        UNPRICED_MODEL,
        headers={"authorization": f"Bearer {raw_key}"},
        api_key_budgets=ApiKeyBudgetsConfig(
            keys={"capped-key": KeyBudgetEntry(daily_usd=5.00)}
        ),
        config=BurnLensConfig(db_path=initialized_db, block_unpriced_models=False),
    )

    assert status == 200
    assert transport.captured is not None


@pytest.mark.asyncio
async def test_opt_out_also_disables_the_policy_guard(initialized_db: str) -> None:
    status, _, transport = await _call(
        initialized_db,
        UNPRICED_MODEL,
        headers={"x-burnlens-tag-team": "platform"},
        config=_policy_config(initialized_db, block_unpriced_models=False),
    )

    assert status == 200
    assert transport.captured is not None
