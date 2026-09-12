"""Economics Analyst Engine (BL-AE-002).

Routes conversational questions to deterministic tools and formats natural language
explanations anchored strictly to verified evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from burnlens.analyst.tools import (
    get_agent_waste_ratio,
    get_top_spending_agents,
    get_workflow_waste_explanation,
    get_worst_cost_per_outcome_workflows,
    investigate_task_costs,
)


@dataclass
class AnalystResponse:
    """Structured response from the Economics Analyst with provenance and evidence."""

    answer: str
    intent: str
    tool_called: str
    evidence: dict[str, Any]
    provenance: str
    workspace_id: str
    denied: bool = False
    error: str | None = None


class EconomicsAnalyst:
    """Conversational investigator over deterministic BurnLens APIs."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def ask(self, question: str, workspace_id: str = "default") -> AnalystResponse:
        """Process a user question, route to deterministic tool, and explain the result."""
        q_clean = question.strip()
        q_lower = q_clean.lower()

        # Security check: detect prompt injection or cross-workspace exfiltration attempts
        if any(
            pattern in q_lower
            for pattern in [
                "other workspace",
                "another workspace",
                "reveal workspace",
                "bypass workspace",
                "ignore workspace",
                "select * from",
                "union select",
                "drop table",
                "--",
            ]
        ):
            return AnalystResponse(
                answer="DENIED: Cross-tenant data access and unauthorized query manipulation are strictly prohibited.",
                intent="security_violation",
                tool_called="none",
                evidence={},
                provenance="security_boundary_enforcement",
                workspace_id=workspace_id,
                denied=True,
                error="Access denied: unauthorized workspace scope or SQL injection pattern detected",
            )

        # 1. Intent: Top spending agents
        # Matches: "which agent cost most", "who spent the most", "top agents"
        if ("agent" in q_lower and ("cost most" in q_lower or "spent most" in q_lower or "top" in q_lower)) or "highest spend" in q_lower:
            evidence = await get_top_spending_agents(self.db_path, workspace_id=workspace_id)
            top_agents = evidence["results"]
            if not top_agents:
                ans = f"No agent activity found in workspace '{workspace_id}'."
            else:
                top = top_agents[0]
                ans = (
                    f"Agent '{top['agent_id']}' had the highest spend in workspace '{workspace_id}' "
                    f"with a total of ${top['total_spend_usd']:.2f} across {top['requests_count']} requests."
                )
            return AnalystResponse(
                answer=ans,
                intent="top_spending_agents",
                tool_called="get_top_spending_agents",
                evidence=evidence,
                provenance=evidence["provenance"],
                workspace_id=workspace_id,
            )

        # 2. Intent: Workflow waste or increase investigation
        # Matches: "why did workflow X increase", "what caused workflow X", "workflow X waste"
        wf_match = re.search(r"workflow\s+([\w\-]+)", q_clean, re.IGNORECASE)
        if wf_match and ("waste" in q_lower or "increase" in q_lower or "cause" in q_lower or "why" in q_lower):
            wf_id = wf_match.group(1)
            evidence = await get_workflow_waste_explanation(self.db_path, wf_id, workspace_id=workspace_id)
            total = evidence["total_spend_usd"]
            waste = evidence["retry_waste_usd"]
            ratio = evidence["waste_ratio"] * 100
            ans = (
                f"Workflow '{wf_id}' spent a total of ${total:.2f}. "
                f"Of that amount, ${waste:.2f} ({ratio:.1f}%) was retry waste from failed or retried requests."
            )
            return AnalystResponse(
                answer=ans,
                intent="workflow_waste_explanation",
                tool_called="get_workflow_waste_explanation",
                evidence=evidence,
                provenance=evidence["provenance"],
                workspace_id=workspace_id,
            )

        # 3. Intent: Agent retry waste ratio
        # Matches: "proportion was retry waste", "waste ratio for agent X"
        ag_match = re.search(r"agent\s+([\w\.\-]+)", q_clean, re.IGNORECASE)
        if "retry waste" in q_lower or "waste ratio" in q_lower or "proportion was retry" in q_lower:
            ag_id = ag_match.group(1) if ag_match else "unknown"
            evidence = await get_agent_waste_ratio(self.db_path, ag_id, workspace_id=workspace_id)
            waste_pct = evidence["retry_waste_percentage"]
            waste_usd = evidence["retry_waste_usd"]
            ans = (
                f"For agent '{ag_id}', retry waste accounted for {waste_pct:.1f}% of total spend "
                f"(${waste_usd:.2f} of ${evidence['total_spend_usd']:.2f})."
            )
            return AnalystResponse(
                answer=ans,
                intent="agent_waste_ratio",
                tool_called="get_agent_waste_ratio",
                evidence=evidence,
                provenance=evidence["provenance"],
                workspace_id=workspace_id,
            )

        # 4. Intent: Worst cost per outcome
        # Matches: "worst cost/outcome", "worst cost per outcome", "poor cost/outcome"
        if "cost/outcome" in q_lower or "cost per outcome" in q_lower or "cost per successful outcome" in q_lower:
            evidence = await get_worst_cost_per_outcome_workflows(self.db_path, workspace_id=workspace_id)
            results = evidence["results"]
            if not results:
                ans = f"No workflows with accepted outcomes recorded in workspace '{workspace_id}'."
            else:
                worst = results[0]
                ans = (
                    f"Workflow '{worst['workflow_id']}' has the highest unit cost at "
                    f"${worst['cost_per_accepted_outcome_usd']:.2f} per accepted outcome "
                    f"(${worst['total_spend_usd']:.2f} total spend across {worst['accepted_outcomes']} accepted outcomes)."
                )
            return AnalystResponse(
                answer=ans,
                intent="worst_cost_per_outcome",
                tool_called="get_worst_cost_per_outcome_workflows",
                evidence=evidence,
                provenance=evidence["provenance"],
                workspace_id=workspace_id,
            )

        # 5. Intent: Task cost investigation
        task_match = re.search(r"task\s+([\w\-]+)", q_clean, re.IGNORECASE)
        if task_match:
            t_id = task_match.group(1)
            evidence = await investigate_task_costs(self.db_path, t_id, workspace_id=workspace_id)
            total = evidence["total_spend_usd"]
            model = evidence["model_spend_usd"]
            tool_spend = evidence["tool_action_spend_usd"]
            ans = (
                f"Task '{t_id}' total cost was ${total:.2f}, comprising ${model:.2f} in model calls "
                f"and ${tool_spend:.2f} in tool actions."
            )
            return AnalystResponse(
                answer=ans,
                intent="task_cost_investigation",
                tool_called="investigate_task_costs",
                evidence=evidence,
                provenance=evidence["provenance"],
                workspace_id=workspace_id,
            )

        # Fallback default query: top spending overview
        evidence = await get_top_spending_agents(self.db_path, workspace_id=workspace_id)
        return AnalystResponse(
            answer=f"Identified top spend across active agents in workspace '{workspace_id}'.",
            intent="general_economics_query",
            tool_called="get_top_spending_agents",
            evidence=evidence,
            provenance=evidence["provenance"],
            workspace_id=workspace_id,
        )
