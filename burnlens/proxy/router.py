"""Budget-aware model downgrade routing for BurnLens proxy.

decide_route() is called on every proxied request. It checks the caller's
remaining budget against configured thresholds and returns a RouteDecision
that may rewrite the model to a cheaper tier. This function MUST NEVER RAISE
— any exception returns a no-op decision so the proxy is never broken.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from burnlens.config import BurnLensConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Team spend cache — 60-second TTL (per D-10).
# Customer spend is looked up via get_spend_by_customer_this_month() directly;
# each call in the router path is low-frequency enough that a single DB read
# per cache-miss is acceptable without a local cache.
# ---------------------------------------------------------------------------

_team_spend_cache: dict[str, tuple[float, float]] = {}  # team -> (spend_usd, cached_at)
_TEAM_CACHE_TTL = 60.0  # seconds


# ---------------------------------------------------------------------------
# RouteDecision
# ---------------------------------------------------------------------------


@dataclass
class RouteDecision:
    """Result of a routing decision for a single proxied request.

    Fields
    ------
    original_model:
        The model name as received from the caller.
    routed_model:
        The model name that will actually be forwarded upstream.
        Equals ``original_model`` when ``downgraded`` is False.
    downgraded:
        True iff the model was replaced with a cheaper alternative.
    reason:
        Machine-readable code explaining the decision:
        ``"budget_pct"``      — remaining budget % < downgrade_threshold_pct
        ``"budget_usd"``      — remaining budget USD < downgrade_threshold_usd
        ``"no_downgrade_needed"`` — budget above both thresholds
        ``"no_alternative"``  — threshold triggered but no cheaper model mapped
        ``"no_budget"``       — no budget configured for this caller
        ``"disabled"``        — budget_downgrade=False in config
        ``"error"``           — unexpected exception; fail-open
    budget_remaining_usd:
        Remaining budget in USD, or 0.0 if unknown.
    budget_remaining_pct:
        Remaining budget as a percentage (0–100), or 100.0 if unknown / disabled.
    """

    original_model: str
    routed_model: str
    downgraded: bool
    reason: str
    budget_remaining_usd: float
    budget_remaining_pct: float


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def decide_route(
    model: str,
    tag_team: str | None,
    tag_customer: str | None,
    config: "BurnLensConfig",
    db_path: str,
) -> RouteDecision:
    """Return a routing decision for the given request — never raises.

    On any exception, returns a pass-through decision (fail-open proxy design).
    The caller should act on ``RouteDecision.routed_model``; when ``downgraded``
    is True it should also log the downgrade event if ``config.routing.log_downgrades``
    is set.
    """
    try:
        return await _decide_route_inner(model, tag_team, tag_customer, config, db_path)
    except Exception as exc:
        logger.debug("Router error (fail-open): %s", exc)
        return RouteDecision(
            original_model=model,
            routed_model=model,
            downgraded=False,
            reason="error",
            budget_remaining_usd=0.0,
            budget_remaining_pct=100.0,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _decide_route_inner(
    model: str,
    tag_team: str | None,
    tag_customer: str | None,
    config: "BurnLensConfig",
    db_path: str,
) -> RouteDecision:
    """Core routing logic — may raise; caller wraps in try/except."""
    if not config.routing.budget_downgrade:
        return RouteDecision(
            original_model=model,
            routed_model=model,
            downgraded=False,
            reason="disabled",
            budget_remaining_usd=0.0,
            budget_remaining_pct=100.0,
        )

    limit, spent = await _resolve_budget(tag_team, tag_customer, config, db_path)

    if limit is None or limit <= 0:
        return RouteDecision(
            original_model=model,
            routed_model=model,
            downgraded=False,
            reason="no_budget",
            budget_remaining_usd=0.0,
            budget_remaining_pct=100.0,
        )

    remaining_usd = max(0.0, limit - spent)
    remaining_pct = (remaining_usd / limit) * 100.0

    # Percentage check runs first; when both trigger, reason = "budget_pct" (per D-03).
    if remaining_pct < config.routing.downgrade_threshold_pct:
        trigger_reason = "budget_pct"
    elif remaining_usd < config.routing.downgrade_threshold_usd:
        trigger_reason = "budget_usd"
    else:
        return RouteDecision(
            original_model=model,
            routed_model=model,
            downgraded=False,
            reason="no_downgrade_needed",
            budget_remaining_usd=remaining_usd,
            budget_remaining_pct=remaining_pct,
        )

    # Deferred import avoids circular dependency at module-load time.
    from burnlens.providers.downgrade import get_downgrade_model

    cheaper = get_downgrade_model(model)
    if cheaper is None:
        return RouteDecision(
            original_model=model,
            routed_model=model,
            downgraded=False,
            reason="no_alternative",
            budget_remaining_usd=remaining_usd,
            budget_remaining_pct=remaining_pct,
        )

    return RouteDecision(
        original_model=model,
        routed_model=cheaper,
        downgraded=True,
        reason=trigger_reason,
        budget_remaining_usd=remaining_usd,
        budget_remaining_pct=remaining_pct,
    )


async def _resolve_budget(
    tag_team: str | None,
    tag_customer: str | None,
    config: "BurnLensConfig",
    db_path: str,
) -> tuple[float | None, float]:
    """Return (limit_usd, spent_usd).

    Budget priority order (per D-03): customer > team > global_usd > budget_limit_usd.
    Returns (None, 0.0) when no budget is configured for the caller.
    """
    from burnlens.storage.database import (
        get_spend_by_customer_this_month,
        get_spend_by_team_this_month,
    )

    # 1. Customer budget (highest priority)
    if tag_customer:
        cust_cfg = config.alerts.customer_budgets
        limit: float | None = cust_cfg.customers.get(tag_customer) or cust_cfg.default
        if limit is not None:
            all_spend = await get_spend_by_customer_this_month(db_path)
            return limit, all_spend.get(tag_customer, 0.0)

    # 2. Team budget
    if tag_team:
        team_limits = config.alerts.budgets.teams
        team_limit = team_limits.get(tag_team)
        if team_limit is not None:
            spent = await _get_team_spend(tag_team, db_path)
            return team_limit, spent

    # 3. Global budget — prefer global_usd, fall back to legacy budget_limit_usd
    global_limit = config.alerts.budgets.global_usd or config.alerts.budget_limit_usd
    if global_limit is not None:
        all_team = await get_spend_by_team_this_month(db_path)
        total_spent = sum(all_team.values())
        return global_limit, total_spent

    return None, 0.0


async def _get_team_spend(team: str, db_path: str) -> float:
    """Return a team's spend for the current month, cached for 60 seconds (per D-10)."""
    entry = _team_spend_cache.get(team)
    if entry is not None:
        spend, cached_at = entry
        if time.monotonic() - cached_at <= _TEAM_CACHE_TTL:
            return spend

    from burnlens.storage.database import get_spend_by_team_this_month

    all_spend = await get_spend_by_team_this_month(db_path)
    spend = all_spend.get(team, 0.0)
    _team_spend_cache[team] = (spend, time.monotonic())
    return spend
