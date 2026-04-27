"""Tests for per-customer cost tracking and budget enforcement."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from burnlens.alerts.engine import CustomerBudgetAlert, check_customer_budgets
from burnlens.config import (
    AlertsConfig,
    BurnLensConfig,
    CustomerBudgetsConfig,
)
from burnlens.proxy.interceptor import (
    _customer_spend_cache,
    _get_cached_customer_spend,
    _set_cached_customer_spend,
    check_customer_budget,
)
from burnlens.storage.database import (
    get_spend_by_customer_this_month,
    get_customer_request_count,
    get_top_customers_by_cost,
    insert_request,
)
from burnlens.storage.models import RequestRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    db_path: str,
    customers: dict[str, float] | None = None,
    default: float | None = None,
) -> BurnLensConfig:
    cust = CustomerBudgetsConfig(
        default=default,
        customers=customers or {},
    )
    alerts = AlertsConfig(customer_budgets=cust)
    return BurnLensConfig(db_path=db_path, alerts=alerts)


async def _insert_customer_request(
    db_path: str,
    customer: str,
    cost_usd: float,
) -> None:
    record = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        cost_usd=cost_usd,
        input_tokens=100,
        output_tokens=50,
        tags={"customer": customer},
    )
    await insert_request(db_path, record)


# ---------------------------------------------------------------------------
# test_customer_spend_tracked_correctly
# ---------------------------------------------------------------------------


class TestCustomerSpendTrackedCorrectly:
    async def test_aggregates_multiple_requests(self, initialized_db: str) -> None:
        """Spend is summed correctly across multiple requests for the same customer."""
        await _insert_customer_request(initialized_db, "acme-corp", 10.0)
        await _insert_customer_request(initialized_db, "acme-corp", 20.0)
        await _insert_customer_request(initialized_db, "acme-corp", 5.50)

        spend = await get_spend_by_customer_this_month(initialized_db)
        assert abs(spend["acme-corp"] - 35.50) < 1e-6

    async def test_separate_customers(self, initialized_db: str) -> None:
        """Different customers are tracked independently."""
        await _insert_customer_request(initialized_db, "acme-corp", 10.0)
        await _insert_customer_request(initialized_db, "beta-user", 25.0)

        spend = await get_spend_by_customer_this_month(initialized_db)
        assert abs(spend["acme-corp"] - 10.0) < 1e-6
        assert abs(spend["beta-user"] - 25.0) < 1e-6

    async def test_request_count(self, initialized_db: str) -> None:
        """Request count is tracked per customer."""
        await _insert_customer_request(initialized_db, "acme-corp", 1.0)
        await _insert_customer_request(initialized_db, "acme-corp", 2.0)
        await _insert_customer_request(initialized_db, "acme-corp", 3.0)

        count = await get_customer_request_count(initialized_db, "acme-corp")
        assert count == 3

    async def test_top_customers(self, initialized_db: str) -> None:
        """Top customers are returned sorted by cost descending."""
        await _insert_customer_request(initialized_db, "low-spender", 5.0)
        await _insert_customer_request(initialized_db, "big-spender", 100.0)
        await _insert_customer_request(initialized_db, "mid-spender", 25.0)

        top = await get_top_customers_by_cost(initialized_db, limit=2)
        assert len(top) == 2
        assert top[0]["customer"] == "big-spender"
        assert top[1]["customer"] == "mid-spender"

    async def test_untagged_requests_excluded(self, initialized_db: str) -> None:
        """Requests without a customer tag don't appear."""
        record = RequestRecord(
            provider="openai",
            model="gpt-4o",
            request_path="/v1/chat/completions",
            cost_usd=100.0,
        )
        await insert_request(initialized_db, record)

        spend = await get_spend_by_customer_this_month(initialized_db)
        assert spend == {}


# ---------------------------------------------------------------------------
# test_budget_cap_returns_429_when_exceeded
# ---------------------------------------------------------------------------


class TestBudgetCapReturns429WhenExceeded:
    async def test_rejects_when_over_budget(self, initialized_db: str) -> None:
        """Customer who exceeded budget gets 429 rejection."""
        await _insert_customer_request(initialized_db, "acme-corp", 50.12)

        cust_cfg = CustomerBudgetsConfig(customers={"acme-corp": 50.0})

        # Clear cache to force DB lookup
        _customer_spend_cache.clear()

        allowed, spent, limit = await check_customer_budget(
            "acme-corp", initialized_db, cust_cfg,
        )
        assert not allowed
        assert spent >= 50.0
        assert limit == 50.0

    async def test_rejects_when_exactly_at_budget(self, initialized_db: str) -> None:
        """Customer at exactly their budget gets rejected (>= check)."""
        await _insert_customer_request(initialized_db, "acme-corp", 50.0)

        cust_cfg = CustomerBudgetsConfig(customers={"acme-corp": 50.0})
        _customer_spend_cache.clear()

        allowed, spent, limit = await check_customer_budget(
            "acme-corp", initialized_db, cust_cfg,
        )
        assert not allowed


# ---------------------------------------------------------------------------
# test_budget_cap_allows_request_when_under_limit
# ---------------------------------------------------------------------------


class TestBudgetCapAllowsRequestWhenUnderLimit:
    async def test_allows_under_budget(self, initialized_db: str) -> None:
        """Customer under budget is allowed through."""
        await _insert_customer_request(initialized_db, "acme-corp", 30.0)

        cust_cfg = CustomerBudgetsConfig(customers={"acme-corp": 50.0})
        _customer_spend_cache.clear()

        allowed, spent, limit = await check_customer_budget(
            "acme-corp", initialized_db, cust_cfg,
        )
        assert allowed
        assert spent == 30.0
        assert limit == 50.0

    async def test_allows_when_no_budget_configured(self, initialized_db: str) -> None:
        """Customer with no budget configured is always allowed."""
        await _insert_customer_request(initialized_db, "unknown-user", 9999.0)

        cust_cfg = CustomerBudgetsConfig(customers={})
        _customer_spend_cache.clear()

        allowed, spent, limit = await check_customer_budget(
            "unknown-user", initialized_db, cust_cfg,
        )
        assert allowed


# ---------------------------------------------------------------------------
# test_default_budget_applied_to_unknown_customer
# ---------------------------------------------------------------------------


class TestDefaultBudgetAppliedToUnknownCustomer:
    async def test_default_budget_enforced(self, initialized_db: str) -> None:
        """Unrecognised customer gets the default budget."""
        await _insert_customer_request(initialized_db, "new-user", 6.0)

        cust_cfg = CustomerBudgetsConfig(
            default=5.0,
            customers={"acme-corp": 50.0},
        )
        _customer_spend_cache.clear()

        allowed, spent, limit = await check_customer_budget(
            "new-user", initialized_db, cust_cfg,
        )
        assert not allowed
        assert limit == 5.0

    async def test_default_budget_allows_under(self, initialized_db: str) -> None:
        """Unrecognised customer under default budget is allowed."""
        await _insert_customer_request(initialized_db, "new-user", 3.0)

        cust_cfg = CustomerBudgetsConfig(default=5.0, customers={})
        _customer_spend_cache.clear()

        allowed, spent, limit = await check_customer_budget(
            "new-user", initialized_db, cust_cfg,
        )
        assert allowed
        assert limit == 5.0


# ---------------------------------------------------------------------------
# test_spend_cache_reduces_db_calls
# ---------------------------------------------------------------------------


class TestSpendCacheReducesDbCalls:
    async def test_cache_hit_avoids_db(self, initialized_db: str) -> None:
        """Second call within TTL uses cache, not DB."""
        _customer_spend_cache.clear()

        cust_cfg = CustomerBudgetsConfig(customers={"acme-corp": 100.0})

        # First call — hits DB
        await _insert_customer_request(initialized_db, "acme-corp", 10.0)
        allowed1, spent1, _ = await check_customer_budget(
            "acme-corp", initialized_db, cust_cfg,
        )
        assert allowed1
        assert spent1 == 10.0

        # Insert more spend — but cache should still return old value
        await _insert_customer_request(initialized_db, "acme-corp", 95.0)

        allowed2, spent2, _ = await check_customer_budget(
            "acme-corp", initialized_db, cust_cfg,
        )
        # Cache still has 10.0, so still allowed
        assert allowed2
        assert spent2 == 10.0

    def test_cache_expires(self) -> None:
        """Cache entries expire after TTL."""
        _customer_spend_cache.clear()
        _set_cached_customer_spend("test", 42.0)

        # Artificially expire the entry
        _customer_spend_cache["test"] = (42.0, time.monotonic() - 120.0)

        result = _get_cached_customer_spend("test")
        assert result is None


# ---------------------------------------------------------------------------
# test_customer_alert_fires_at_80_percent
# ---------------------------------------------------------------------------


class TestCustomerAlertFiresAt80Percent:
    async def test_warning_at_80_pct(self, initialized_db: str) -> None:
        """Customer at 80%+ of budget triggers WARNING alert."""
        cfg = _make_config(
            initialized_db, customers={"acme-corp": 50.0},
        )
        await _insert_customer_request(initialized_db, "acme-corp", 40.10)

        alerts = await check_customer_budgets(cfg, initialized_db)
        assert len(alerts) == 1
        assert alerts[0].customer == "acme-corp"
        assert alerts[0].severity == "WARNING"
        assert alerts[0].pct >= 80.0

    async def test_critical_at_100_pct(self, initialized_db: str) -> None:
        """Customer at 100%+ of budget triggers CRITICAL alert."""
        cfg = _make_config(
            initialized_db, customers={"acme-corp": 50.0},
        )
        await _insert_customer_request(initialized_db, "acme-corp", 55.0)

        alerts = await check_customer_budgets(cfg, initialized_db)
        assert len(alerts) == 1
        assert alerts[0].severity == "CRITICAL"

    async def test_no_alert_below_80_pct(self, initialized_db: str) -> None:
        """Customer below 80% gets no alert."""
        cfg = _make_config(
            initialized_db, customers={"acme-corp": 100.0},
        )
        await _insert_customer_request(initialized_db, "acme-corp", 50.0)

        alerts = await check_customer_budgets(cfg, initialized_db)
        assert alerts == []

    async def test_default_budget_alert(self, initialized_db: str) -> None:
        """Unknown customer using default budget triggers alert."""
        cfg = _make_config(initialized_db, default=10.0)
        await _insert_customer_request(initialized_db, "random-user", 8.50)

        alerts = await check_customer_budgets(cfg, initialized_db)
        assert len(alerts) == 1
        assert alerts[0].customer == "random-user"
        assert alerts[0].severity == "WARNING"
