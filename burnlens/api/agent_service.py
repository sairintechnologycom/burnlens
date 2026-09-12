"""Deterministic service layer for BurnLens Agent API & MCP (BL-AE-004).

Implements the 7 core deterministic operations required by the master plan:
1. get_agent_economics
2. get_task_economics
3. find_waste
4. estimate_cost
5. simulate_change
6. check_budget
7. get_cost_per_outcome

All operations enforce workspace tenancy, capability scope authorization,
deterministic calculation, audit provenance, and zero raw database exposure.
"""
from __future__ import annotations

import logging
from typing import Any

import aiosqlite

from burnlens.analyst.tools import (
    get_agent_waste_ratio,
    get_top_spending_agents,
    get_worst_cost_per_outcome_workflows,
    investigate_task_costs,
)
from burnlens.api.agent_security import AgentScope, AgentSecurityContext
from burnlens.cost.calculator import TokenUsage, calculate_cost, is_model_priced
from burnlens.recommendations.engine import RecommendationEngine
from burnlens.recommendations.simulator import (
    simulate_model_switch,
    simulate_prompt_caching,
    simulate_retry_reduction,
)
from burnlens.storage.agent_economics import (
    get_agent_economics as storage_get_agent_economics,
    get_task_economics as storage_get_task_economics,
    get_workflow_economics as storage_get_workflow_economics,
)

logger = logging.getLogger(__name__)


class AgentApiPermissionError(PermissionError):
    """Raised when an external agent lacks required scopes or attempts cross-workspace access."""
    pass


class AgentApiValidationError(ValueError):
    """Raised when request arguments fail validation."""
    pass


class AgentEconomicsService:
    """Core deterministic service backing Agent HTTP APIs and MCP tools."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._rec_engine = RecommendationEngine(db_path)

    def _authorize(
        self,
        context: AgentSecurityContext,
        required_scope: AgentScope,
        target_workspace_id: str | None = None,
    ) -> None:
        """Verify token validity, required scope, and workspace containment."""
        if not context.is_valid():
            raise AgentApiPermissionError("Authentication token is expired or revoked.")

        if not context.has_scope(required_scope):
            raise AgentApiPermissionError(
                f"Agent '{context.agent_id}' missing required scope '{required_scope.value}'."
            )

        if target_workspace_id and target_workspace_id != context.workspace_id:
            # Multi-tenant boundary invariant
            raise AgentApiPermissionError(
                f"Agent registered for workspace '{context.workspace_id}' cannot access workspace '{target_workspace_id}'."
            )

    # 1. get_agent_economics
    async def get_agent_economics(
        self,
        context: AgentSecurityContext,
        agent_id: str,
        workspace_id: str | None = None,
        since: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve authoritative economics and spend breakdown for an agent."""
        eff_workspace = workspace_id or context.workspace_id
        self._authorize(context, AgentScope.ECONOMICS_READ, eff_workspace)

        raw = await storage_get_agent_economics(
            self.db_path, agent_id=agent_id, workspace_id=eff_workspace, since=since
        )
        return {
            "agent_id": agent_id,
            "workspace_id": eff_workspace,
            "provenance": "canonical_requests_and_actions",
            **raw,
        }

    # 2. get_task_economics
    async def get_task_economics(
        self,
        context: AgentSecurityContext,
        task_id: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve granular economics for a task and its actions."""
        eff_workspace = workspace_id or context.workspace_id
        self._authorize(context, AgentScope.ECONOMICS_READ, eff_workspace)

        raw = await storage_get_task_economics(
            self.db_path, task_id=task_id, workspace_id=eff_workspace
        )
        return {
            "task_id": task_id,
            "workspace_id": eff_workspace,
            "provenance": "canonical_task_and_actions",
            **raw,
        }

    # 3. find_waste
    async def find_waste(
        self,
        context: AgentSecurityContext,
        agent_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Detect and quantify retry waste, errors, and uncacheable queries."""
        eff_workspace = workspace_id or context.workspace_id
        self._authorize(context, AgentScope.ECONOMICS_READ, eff_workspace)

        if agent_id:
            waste_data = await get_agent_waste_ratio(
                self.db_path, agent_id=agent_id, workspace_id=eff_workspace
            )
            return waste_data

        # Workspace-wide waste summary
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT
                    COALESCE(SUM(cost_usd), 0.0),
                    COUNT(*)
                FROM requests
                WHERE (workspace_id = ? OR (workspace_id IS NULL AND ? = 'default'))
                  AND status_code >= 400
                """,
                (eff_workspace, eff_workspace),
            )
            retry_cost, retry_count = await cursor.fetchone()

        return {
            "workspace_id": eff_workspace,
            "metric": "workspace_retry_waste",
            "provenance": "requests_status_code_gte_400",
            "total_retry_waste_usd": round(retry_cost, 6),
            "failed_requests_count": retry_count,
        }

    # 4. estimate_cost
    def estimate_cost(
        self,
        context: AgentSecurityContext,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int = 1000,
        cache_read_tokens: int = 0,
    ) -> dict[str, Any]:
        """Estimate the USD cost of a planned model call before invocation."""
        self._authorize(context, AgentScope.ECONOMICS_READ)

        if not is_model_priced(provider, model):
            return {
                "provider": provider,
                "model": model,
                "is_priced": False,
                "estimated_cost_usd": 0.0,
                "warning": f"Model '{model}' from provider '{provider}' is unpriced in current registry.",
            }

        usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
        )
        cost = calculate_cost(provider, model, usage)
        return {
            "provider": provider,
            "model": model,
            "is_priced": True,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "estimated_cost_usd": round(cost, 6),
        }

    # 5. simulate_change
    def simulate_change(
        self,
        context: AgentSecurityContext,
        simulation_type: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Simulate counterfactual savings for a proposed architecture or routing change."""
        self._authorize(context, AgentScope.SIMULATION_EXECUTE)

        sim_type = simulation_type.lower()
        if sim_type in ("model_switch", "switch_model"):
            res = simulate_model_switch(
                current_provider=params.get("current_provider", "anthropic"),
                current_model=params["current_model"],
                target_provider=params.get("target_provider", "anthropic"),
                target_model=params["target_model"],
                input_tokens=params["input_tokens"],
                output_tokens=params.get("output_tokens", 1000),
                request_count=params.get("request_count", 1),
            )
            return res.to_dict()

        elif sim_type in ("retry_reduction", "reduce_retries"):
            res = simulate_retry_reduction(
                current_retry_spend_usd=float(params["current_retry_spend_usd"]),
                reduction_pct=float(params.get("reduction_pct", 0.5)),
            )
            return res.to_dict()

        elif sim_type in ("prompt_caching", "cache_prompt"):
            res = simulate_prompt_caching(
                provider=params.get("provider", "anthropic"),
                model=params["model"],
                total_input_tokens=int(params["total_input_tokens"]),
                cache_read_tokens=int(params["cache_read_tokens"]),
                output_tokens=int(params.get("output_tokens", 500)),
                request_count=int(params.get("request_count", 1)),
            )
            return res.to_dict()

        else:
            raise AgentApiValidationError(
                f"Unsupported simulation_type '{simulation_type}'. "
                f"Supported: 'model_switch', 'retry_reduction', 'prompt_caching'."
            )

    # 6. check_budget
    async def check_budget(
        self,
        context: AgentSecurityContext,
        task_id: str | None = None,
        agent_id: str | None = None,
        workspace_id: str | None = None,
        planned_spend_usd: float = 0.0,
        budget_limit_usd: float | None = None,
    ) -> dict[str, Any]:
        """Check whether a task or agent has sufficient budget remaining for another retry or step."""
        eff_workspace = workspace_id or context.workspace_id
        self._authorize(context, AgentScope.BUDGET_CHECK, eff_workspace)

        current_spend = 0.0
        if task_id:
            task_econ = await storage_get_task_economics(
                self.db_path, task_id=task_id, workspace_id=eff_workspace
            )
            current_spend = task_econ["total_spend_usd"]
        elif agent_id:
            ag_econ = await storage_get_agent_economics(
                self.db_path, agent_id=agent_id, workspace_id=eff_workspace
            )
            current_spend = ag_econ["total_spend_usd"]
        else:
            # Check workspace spend
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0.0) FROM requests WHERE workspace_id = ? OR (workspace_id IS NULL AND ? = 'default')",
                    (eff_workspace, eff_workspace),
                )
                current_spend = (await cursor.fetchone())[0]

        limit = budget_limit_usd if budget_limit_usd is not None else 100.0
        projected_spend = current_spend + planned_spend_usd
        allowed = projected_spend <= limit
        remaining_budget = max(0.0, limit - current_spend)

        return {
            "workspace_id": eff_workspace,
            "task_id": task_id,
            "agent_id": agent_id,
            "budget_limit_usd": round(limit, 6),
            "current_spend_usd": round(current_spend, 6),
            "planned_spend_usd": round(planned_spend_usd, 6),
            "projected_spend_usd": round(projected_spend, 6),
            "remaining_budget_usd": round(remaining_budget, 6),
            "allowed": allowed,
            "reason": "Within budget" if allowed else f"Projected spend ${projected_spend:.4f} exceeds limit ${limit:.4f}",
        }

    # 7. get_cost_per_outcome
    async def get_cost_per_outcome(
        self,
        context: AgentSecurityContext,
        workflow_id: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Compute true unit economics: cost per accepted outcome for a workflow."""
        eff_workspace = workspace_id or context.workspace_id
        self._authorize(context, AgentScope.ECONOMICS_READ, eff_workspace)

        econ = await storage_get_workflow_economics(
            self.db_path, workflow_id=workflow_id, workspace_id=eff_workspace
        )
        return {
            "workflow_id": workflow_id,
            "workspace_id": eff_workspace,
            "provenance": "workflow_and_outcomes_join",
            **econ,
        }
