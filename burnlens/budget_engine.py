from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from burnlens.config import BurnLensConfig, BudgetPolicy
from burnlens.cost.calculator import TokenUsage, calculate_cost
from burnlens.key_budget import resolve_timezone, today_window_utc

logger = logging.getLogger(__name__)


def estimate_request_tokens(body_bytes: bytes) -> tuple[int, int]:
    """Estimate (input_tokens, output_tokens) from request body bytes."""
    try:
        data = json.loads(body_bytes)
    except Exception:
        return 100, 1000  # Default fallback

    # 1. Estimate input tokens
    input_chars = 0

    # Chat completions / messages format
    messages = data.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str):
                    input_chars += len(content)
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and "text" in part:
                            input_chars += len(part["text"])

    # Anthropic system prompt
    system = data.get("system")
    if isinstance(system, str):
        input_chars += len(system)
    elif isinstance(system, list):
        for part in system:
            if isinstance(part, dict) and "text" in part:
                input_chars += len(part["text"])

    # Google Gemini format
    contents = data.get("contents")
    if isinstance(contents, list):
        for item in contents:
            if isinstance(item, dict):
                parts = item.get("parts")
                if isinstance(parts, list):
                    for part in parts:
                        if isinstance(part, dict) and "text" in part:
                            input_chars += len(part["text"])

    # Generic fallback text/prompt fields
    prompt = data.get("prompt")
    if isinstance(prompt, str):
        input_chars += len(prompt)
    elif isinstance(prompt, list):
        input_chars += sum(len(str(x)) for x in prompt)

    input_tokens = max(10, int(input_chars / 4)) if input_chars > 0 else 100

    # 2. Parse output tokens
    output_tokens = data.get("max_tokens") or data.get("max_completion_tokens")
    if not output_tokens or not isinstance(output_tokens, int):
        output_tokens = 1000  # Default fallback

    return input_tokens, output_tokens


class BudgetEngine:
    """Manages real-time budget policies, pre-call estimations, and post-call reconciliations."""

    def __init__(self, config: BurnLensConfig, db_path: str) -> None:
        self.config = config
        self.db_path = db_path
        self._lock = asyncio.Lock()

    def estimate_cost(self, provider: str, model: str, body_bytes: bytes) -> float:
        """Estimate the request cost in USD."""
        in_tok, out_tok = estimate_request_tokens(body_bytes)
        usage = TokenUsage(input_tokens=in_tok, output_tokens=out_tok)
        return calculate_cost(provider, model, usage)

    def _get_period_start(self, period: str, now: datetime) -> datetime:
        """Get the start datetime of the period in UTC."""
        if period == "daily":
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "weekly":
            # Monday start
            start = now - timedelta(days=now.weekday())
            return start.replace(hour=0, minute=0, second=0, microsecond=0)
        else:  # monthly
            return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    async def _calculate_initial_spend(
        self,
        db: aiosqlite.Connection,
        policy: BudgetPolicy,
        since: datetime,
    ) -> float:
        """Query requests table to calculate spent_usd since period start for policy scope/target."""
        since_iso = since.isoformat()
        scope = policy.scope
        target = policy.target

        # Construct query based on scope and target
        if scope == "org":
            if target == "*":
                query = "SELECT COALESCE(SUM(cost_usd), 0.0) FROM requests WHERE timestamp >= ?"
                params: tuple[Any, ...] = (since_iso,)
            else:
                query = "SELECT COALESCE(SUM(cost_usd), 0.0) FROM requests WHERE timestamp >= ? AND (org_id = ? OR json_extract(tags, '$.org_id') = ?)"
                params = (since_iso, target, target)
        elif scope == "team":
            if target == "*":
                query = "SELECT COALESCE(SUM(cost_usd), 0.0) FROM requests WHERE timestamp >= ? AND (team IS NOT NULL OR json_extract(tags, '$.team') IS NOT NULL)"
                params = (since_iso,)
            else:
                query = "SELECT COALESCE(SUM(cost_usd), 0.0) FROM requests WHERE timestamp >= ? AND (team = ? OR json_extract(tags, '$.team') = ?)"
                params = (since_iso, target, target)
        elif scope == "app":
            if target == "*":
                query = "SELECT COALESCE(SUM(cost_usd), 0.0) FROM requests WHERE timestamp >= ? AND (app_id IS NOT NULL OR json_extract(tags, '$.app_id') IS NOT NULL)"
                params = (since_iso,)
            else:
                query = "SELECT COALESCE(SUM(cost_usd), 0.0) FROM requests WHERE timestamp >= ? AND (app_id = ? OR json_extract(tags, '$.app_id') = ?)"
                params = (since_iso, target, target)
        elif scope == "customer":
            if target == "*":
                query = "SELECT COALESCE(SUM(cost_usd), 0.0) FROM requests WHERE timestamp >= ? AND (customer_hash IS NOT NULL OR json_extract(tags, '$.customer') IS NOT NULL)"
                params = (since_iso,)
            else:
                cust_hash = hashlib.sha256(target.encode()).hexdigest()
                query = "SELECT COALESCE(SUM(cost_usd), 0.0) FROM requests WHERE timestamp >= ? AND (customer_hash = ? OR json_extract(tags, '$.customer') = ?)"
                params = (since_iso, cust_hash, target)
        elif scope == "model":
            if target == "*":
                query = "SELECT COALESCE(SUM(cost_usd), 0.0) FROM requests WHERE timestamp >= ? AND model IS NOT NULL"
                params = (since_iso,)
            else:
                query = "SELECT COALESCE(SUM(cost_usd), 0.0) FROM requests WHERE timestamp >= ? AND model = ?"
                params = (since_iso, target)
        else:
            return 0.0

        try:
            async with db.execute(query, params) as cursor:
                row = await cursor.fetchone()
                return float(row[0]) if row and row[0] is not None else 0.0
        except Exception as exc:
            logger.warning("Failed to query initial spend for policy %r: %s", policy.name, exc)
            return 0.0

    def _matches_policy(self, policy: BudgetPolicy, model: str, request_context: dict[str, Any]) -> bool:
        """Check if request_context matches a policy."""
        scope = policy.scope
        target = policy.target

        if scope == "org":
            val = request_context.get("org_id")
        elif scope == "team":
            val = request_context.get("team")
        elif scope == "app":
            val = request_context.get("app_id")
        elif scope == "customer":
            val = request_context.get("customer")
        elif scope == "model":
            val = model
        else:
            return False

        if not val:
            return False

        return target == "*" or target == val

    async def check_and_reserve(
        self,
        provider: str,
        model: str,
        body_bytes: bytes,
        request_context: dict[str, Any],
    ) -> tuple[bool, dict[str, Any]]:
        """Atomically check budget policies and reserve estimated cost if allowed.

        Returns:
            (allowed, reservation_dict)
            If allowed is True, reservation_dict contains:
              - "estimated_cost": float
              - "policies": list[tuple[BudgetPolicy, str]] -- matched policies and their period_start strings
            If allowed is False, reservation_dict contains:
              - "violated_policy": BudgetPolicy
              - "estimated_cost": float
        """
        estimated_cost = self.estimate_cost(provider, model, body_bytes)
        if estimated_cost <= 0.0:
            return True, {"estimated_cost": 0.0, "policies": []}

        # Filter applicable policies
        matching_policies: list[tuple[BudgetPolicy, str]] = []
        now = datetime.now(timezone.utc)

        for policy in self.config.budget_policies:
            if self._matches_policy(policy, model, request_context):
                period_start = self._get_period_start(policy.period, now).isoformat()
                matching_policies.append((policy, period_start))

        if not matching_policies:
            return True, {"estimated_cost": estimated_cost, "policies": []}

        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                # 1. Check current spend for all matched policies
                for policy, period_start in matching_policies:
                    cursor = await db.execute(
                        "SELECT current_spend FROM budget_counters WHERE policy_name = ? AND period_start = ?",
                        (policy.name, period_start),
                    )
                    row = await cursor.fetchone()
                    if row is None:
                        # Initialize counter
                        initial_spend = await self._calculate_initial_spend(db, policy, datetime.fromisoformat(period_start))
                        await db.execute(
                            "INSERT OR IGNORE INTO budget_counters (policy_name, period_start, current_spend) VALUES (?, ?, ?)",
                            (policy.name, period_start, initial_spend),
                        )
                        current_spend = initial_spend
                    else:
                        current_spend = float(row[0])

                    if current_spend + estimated_cost > policy.limit_usd:
                        return False, {
                            "violated_policy": policy,
                            "estimated_cost": estimated_cost,
                        }

                # 2. Reserve estimated cost
                for policy, period_start in matching_policies:
                    await db.execute(
                        "UPDATE budget_counters SET current_spend = current_spend + ? WHERE policy_name = ? AND period_start = ?",
                        (estimated_cost, policy.name, period_start),
                    )
                await db.commit()

        return True, {
            "estimated_cost": estimated_cost,
            "policies": matching_policies,
        }

    async def reconcile(self, actual_cost: float, reservation: dict[str, Any]) -> None:
        """Atomically reconcile the budget counters with actual cost after request finishes."""
        policies = reservation.get("policies")
        estimated_cost = reservation.get("estimated_cost", 0.0)
        if not policies or estimated_cost <= 0.0:
            return

        diff = actual_cost - estimated_cost

        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                for policy, period_start in policies:
                    await db.execute(
                        "UPDATE budget_counters SET current_spend = current_spend + ? WHERE policy_name = ? AND period_start = ?",
                        (diff, policy.name, period_start),
                    )
                await db.commit()
