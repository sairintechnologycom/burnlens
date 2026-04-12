"""Integration tests for hard customer budget enforcement and team budget alerts.

Tests validate that the proxy rejects over-budget customers before forwarding,
allows under-budget customers through, honours the default budget for unknown
customers, and correctly caches spend lookups.  Team budget alert thresholds
(WARNING at 80 %, CRITICAL at 100 %) are verified via the engine function.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
import respx

from burnlens.config import (
    AlertsConfig,
    BurnLensConfig,
    CustomerBudgetsConfig,
    TeamBudgetsConfig,
)
from burnlens.cost.calculator import TokenUsage, calculate_cost
from burnlens.proxy.interceptor import (
    _customer_spend_cache,
    check_customer_budget,
    handle_request,
)
from burnlens.proxy.providers import ProviderConfig
from burnlens.storage.database import init_db, insert_request
from burnlens.storage.models import RequestRecord

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_OPENAI_PROVIDER = ProviderConfig(
    name="openai",
    proxy_prefix="/proxy/openai",
    upstream_base="https://api.openai.com",
    env_var="OPENAI_BASE_URL",
)

_OPENAI_RESPONSE = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "model": "gpt-4o-mini",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hi"}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}

_REQUEST_BODY = json.dumps({"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]}).encode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture()
async def test_db(tmp_path):
    """Create a temp DB, seed spend for test-customer, yield path."""
    db_path = str(tmp_path / "budget_test.db")
    await init_db(db_path)

    # Insert enough spend so test-customer exceeds $0.001
    now = datetime.now(timezone.utc)
    for i in range(5):
        record = RequestRecord(
            provider="openai",
            model="gpt-4o-mini",
            request_path="/v1/chat/completions",
            timestamp=now - timedelta(hours=i),
            input_tokens=2000,
            output_tokens=500,
            cost_usd=0.001,  # $0.001 each → $0.005 total
            duration_ms=300,
            status_code=200,
            tags={"customer": "test-customer", "team": "backend"},
            system_prompt_hash=hashlib.sha256(b"sys").hexdigest(),
        )
        await insert_request(db_path, record)

    # Insert spend for mystery-customer too (for default budget test)
    record = RequestRecord(
        provider="openai",
        model="gpt-4o-mini",
        request_path="/v1/chat/completions",
        timestamp=now,
        input_tokens=1000,
        output_tokens=200,
        cost_usd=0.005,
        duration_ms=200,
        status_code=200,
        tags={"customer": "mystery-customer", "team": "research"},
    )
    await insert_request(db_path, record)

    yield db_path


@pytest.fixture(autouse=True)
def _clear_spend_cache():
    """Clear the customer spend cache before each test."""
    _customer_spend_cache.clear()
    yield
    _customer_spend_cache.clear()


def _customer_budgets(**overrides) -> CustomerBudgetsConfig:
    defaults = {
        "default": None,
        "customers": {
            "test-customer": 0.001,
            "rich-customer": 999.00,
        },
    }
    defaults.update(overrides)
    return CustomerBudgetsConfig(**defaults)


def _make_headers(customer: str | None = None) -> dict[str, str]:
    h: dict[str, str] = {
        "content-type": "application/json",
        "authorization": "Bearer sk-test-key",
    }
    if customer:
        h["x-burnlens-tag-customer"] = customer
    return h


# ---------------------------------------------------------------------------
# 1. Over-budget customer is rejected with 429
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_request_rejected_when_customer_over_budget(test_db: str):
    budgets = _customer_budgets()

    with respx.mock:
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
        )
        async with httpx.AsyncClient() as client:
            status, headers, body, stream = await handle_request(
                client=client,
                provider=_OPENAI_PROVIDER,
                path="/proxy/openai/v1/chat/completions",
                method="POST",
                headers=_make_headers("test-customer"),
                body_bytes=_REQUEST_BODY,
                query_string="",
                db_path=test_db,
                customer_budgets=budgets,
            )

    assert status == 429
    assert stream is None
    resp = json.loads(body)
    assert resp["error"] == "budget_exceeded"
    assert resp["customer"] == "test-customer"
    assert "spent" in resp
    assert "limit" in resp


# ---------------------------------------------------------------------------
# 2. Upstream is NOT called when budget exceeded
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upstream_not_called_when_budget_exceeded(test_db: str):
    budgets = _customer_budgets()

    with respx.mock:
        route = respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
        )
        async with httpx.AsyncClient() as client:
            status, _, _, _ = await handle_request(
                client=client,
                provider=_OPENAI_PROVIDER,
                path="/proxy/openai/v1/chat/completions",
                method="POST",
                headers=_make_headers("test-customer"),
                body_bytes=_REQUEST_BODY,
                query_string="",
                db_path=test_db,
                customer_budgets=budgets,
            )

    assert status == 429
    assert route.call_count == 0, "Upstream should NOT be called for over-budget customer"


# ---------------------------------------------------------------------------
# 3. Under-budget customer is allowed through
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_request_allowed_when_under_budget(test_db: str):
    budgets = _customer_budgets()

    with respx.mock:
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
        )
        async with httpx.AsyncClient() as client:
            status, _, body, _ = await handle_request(
                client=client,
                provider=_OPENAI_PROVIDER,
                path="/proxy/openai/v1/chat/completions",
                method="POST",
                headers=_make_headers("rich-customer"),
                body_bytes=_REQUEST_BODY,
                query_string="",
                db_path=test_db,
                customer_budgets=budgets,
            )

    assert status == 200, f"Expected 200 for under-budget customer, got {status}"
    resp = json.loads(body)
    assert resp.get("error") != "budget_exceeded"


# ---------------------------------------------------------------------------
# 4. Default budget applied to unknown customer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_default_budget_applied_to_unknown_customer(test_db: str):
    budgets = _customer_budgets(default=0.001)

    with respx.mock:
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
        )
        async with httpx.AsyncClient() as client:
            status, _, body, _ = await handle_request(
                client=client,
                provider=_OPENAI_PROVIDER,
                path="/proxy/openai/v1/chat/completions",
                method="POST",
                headers=_make_headers("mystery-customer"),
                body_bytes=_REQUEST_BODY,
                query_string="",
                db_path=test_db,
                customer_budgets=budgets,
            )

    assert status == 429
    resp = json.loads(body)
    assert resp["error"] == "budget_exceeded"
    assert resp["customer"] == "mystery-customer"


# ---------------------------------------------------------------------------
# 5. Untagged request is never blocked
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_untagged_request_never_blocked(test_db: str):
    budgets = _customer_budgets(default=0.001)

    with respx.mock:
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
        )
        async with httpx.AsyncClient() as client:
            status, _, _, _ = await handle_request(
                client=client,
                provider=_OPENAI_PROVIDER,
                path="/proxy/openai/v1/chat/completions",
                method="POST",
                headers=_make_headers(customer=None),
                body_bytes=_REQUEST_BODY,
                query_string="",
                db_path=test_db,
                customer_budgets=budgets,
            )

    assert status != 429, "Untagged request should never be rejected by budget enforcement"


# ---------------------------------------------------------------------------
# 6. 429 response body has correct schema
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_429_response_body_has_correct_schema(test_db: str):
    budgets = _customer_budgets()

    with respx.mock:
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
        )
        async with httpx.AsyncClient() as client:
            status, resp_headers, body, stream = await handle_request(
                client=client,
                provider=_OPENAI_PROVIDER,
                path="/proxy/openai/v1/chat/completions",
                method="POST",
                headers=_make_headers("test-customer"),
                body_bytes=_REQUEST_BODY,
                query_string="",
                db_path=test_db,
                customer_budgets=budgets,
            )

    assert status == 429
    assert stream is None
    assert resp_headers.get("content-type") == "application/json"

    resp = json.loads(body)
    assert set(resp.keys()) == {"error", "customer", "spent", "limit"}
    assert isinstance(resp["spent"], (int, float))
    assert isinstance(resp["limit"], (int, float))
    assert resp["spent"] >= resp["limit"], (
        f"spent ({resp['spent']}) should be >= limit ({resp['limit']})"
    )


# ---------------------------------------------------------------------------
# 7. Spend cache reduces DB queries
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_spend_cache_hit_reduces_db_queries(test_db: str):
    budgets = _customer_budgets()

    with patch(
        "burnlens.storage.database.get_spend_by_customer_this_month",
        new_callable=AsyncMock,
        return_value={"test-customer": 0.005},
    ) as mock_db:
        # Fire 5 rapid requests for the same over-budget customer
        for _ in range(5):
            allowed, spent, limit = await check_customer_budget(
                "test-customer", test_db, budgets,
            )
            assert not allowed

        # DB should be queried only once — subsequent calls hit the cache
        assert mock_db.call_count == 1, (
            f"Expected 1 DB call (cache hit for 4 more), got {mock_db.call_count}"
        )


# ---------------------------------------------------------------------------
# 8. Team budget WARNING at 80 %
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_team_budget_warning_alert_at_80_percent(test_db: str):
    """Seeded backend spend is $0.005.  Set limit to $0.006 → 83 % → WARNING."""
    from burnlens.alerts.engine import check_team_budgets

    config = BurnLensConfig(
        db_path=test_db,
        alerts=AlertsConfig(
            budgets=TeamBudgetsConfig(
                teams={"backend": 0.006},
            ),
        ),
    )

    alerts = await check_team_budgets(config, test_db)
    backend_alerts = [a for a in alerts if a.team == "backend"]

    assert len(backend_alerts) == 1, f"Expected 1 backend alert, got {len(backend_alerts)}"
    assert backend_alerts[0].severity == "WARNING"


# ---------------------------------------------------------------------------
# 9. Team budget CRITICAL at 100 %
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_team_budget_critical_alert_at_100_percent(test_db: str):
    """Seeded backend spend is $0.005.  Set limit to $0.004 → 125 % → CRITICAL."""
    from burnlens.alerts.engine import check_team_budgets

    config = BurnLensConfig(
        db_path=test_db,
        alerts=AlertsConfig(
            budgets=TeamBudgetsConfig(
                teams={"backend": 0.004},
            ),
        ),
    )

    alerts = await check_team_budgets(config, test_db)
    backend_alerts = [a for a in alerts if a.team == "backend"]

    assert len(backend_alerts) == 1, f"Expected 1 backend alert, got {len(backend_alerts)}"
    assert backend_alerts[0].severity == "CRITICAL"
