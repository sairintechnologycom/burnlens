"""Recommendation Engine (BL-AE-003).

Generates evidence-backed optimization recommendations with explicit confidence,
quality risk estimates, and rollback plans. Operates in advisory read-only mode.
"""
from __future__ import annotations

import logging
from typing import Any

import aiosqlite

from burnlens.recommendations.models import Recommendation
from burnlens.recommendations.simulator import (
    simulate_model_switch,
    simulate_prompt_caching,
    simulate_retry_reduction,
)

logger = logging.getLogger(__name__)


class RecommendationEngine:
    """Evaluates telemetry to generate actionable recommendations without mutating production systems."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def _fetch_requests(
        self, workspace_id: str, limit: int = 1000
    ) -> list[dict[str, Any]]:
        """Fetch request records for a workspace in read-only mode."""
        query = """
            SELECT
                id, provider, model, input_tokens, output_tokens,
                cache_read_tokens, cache_write_tokens, reasoning_tokens,
                cost_usd, status_code, agent_id, workflow_id, tags
            FROM requests
            WHERE workspace_id = ? OR (workspace_id IS NULL AND ? = 'default')
            ORDER BY id DESC
            LIMIT ?
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(query, (workspace_id, workspace_id, limit))
            rows = await cursor.fetchall()

        return [
            {
                "id": r[0],
                "provider": r[1],
                "model": r[2],
                "input_tokens": r[3],
                "output_tokens": r[4],
                "cache_read_tokens": r[5],
                "cache_write_tokens": r[6],
                "reasoning_tokens": r[7],
                "cost_usd": r[8],
                "status_code": r[9],
                "agent_id": r[10],
                "workflow_id": r[11],
            }
            for r in rows
        ]

    async def generate_recommendations(
        self, workspace_id: str
    ) -> list[Recommendation]:
        """Analyze recent telemetry and produce actionable, advisory recommendations."""
        requests = await self._fetch_requests(workspace_id)
        if not requests:
            return []

        recommendations: list[Recommendation] = []

        # 1. Model Overkill check (e.g. gpt-4o -> gpt-4o-mini)
        gpt4o_reqs = [r for r in requests if r["model"] == "gpt-4o"]
        if gpt4o_reqs and sum(r["cost_usd"] for r in gpt4o_reqs) > 0.005:
            sim = simulate_model_switch(
                requests,
                current_model="gpt-4o",
                target_model="gpt-4o-mini",
                target_provider="openai",
                quality_risk=0.006,
            )
            if sim.expected_saving_usd > 0.0:
                rec_id = Recommendation.generate_id(workspace_id, "model_overkill", "gpt-4o")
                recommendations.append(
                    Recommendation(
                        recommendation_id=rec_id,
                        category="model_overkill",
                        scope="model:gpt-4o",
                        workspace_id=workspace_id,
                        evidence={
                            "current_model": "gpt-4o",
                            "target_model": "gpt-4o-mini",
                            "affected_requests": sim.affected_requests_count,
                            "simulated_details": sim.details,
                        },
                        current_cost=sim.current_cost_usd,
                        projected_cost=sim.projected_cost_usd,
                        expected_saving=sim.expected_saving_usd,
                        confidence=sim.confidence,
                        quality_risk=sim.quality_risk,
                        implementation_plan="Update routing configuration or model header from 'gpt-4o' to 'gpt-4o-mini' on lightweight classification / parsing tasks.",
                        rollback_plan="Revert client model configuration back to 'gpt-4o' immediately; zero migration side effects.",
                    )
                )

        # 2. Retry storm reduction check
        error_reqs = [r for r in requests if r["status_code"] >= 400]
        if error_reqs and sum(r["cost_usd"] for r in error_reqs) > 0.10:
            sim = simulate_retry_reduction(requests, reduction_factor=0.75)
            rec_id = Recommendation.generate_id(workspace_id, "retry_reduction", "global")
            recommendations.append(
                Recommendation(
                    recommendation_id=rec_id,
                    category="retry_reduction",
                    scope="workspace:retry_limits",
                    workspace_id=workspace_id,
                    evidence={
                        "failed_requests": sim.affected_requests_count,
                        "raw_retry_waste_usd": sim.details.get("raw_retry_waste_usd"),
                    },
                    current_cost=sim.current_cost_usd,
                    projected_cost=sim.projected_cost_usd,
                    expected_saving=sim.expected_saving_usd,
                    confidence=sim.confidence,
                    quality_risk=sim.quality_risk,
                    implementation_plan="Configure proxy retry policy with max_retries=1 and exponential backoff to prevent cascading failure loops.",
                    rollback_plan="Disable proxy retry capping by setting max_retries to default vendor behavior.",
                )
            )

        # 3. Prompt Caching Opportunity
        large_context_reqs = [r for r in requests if r["input_tokens"] >= 2000]
        if len(large_context_reqs) >= 2:
            sim = simulate_prompt_caching(requests, cache_eligible_ratio=0.60)
            rec_id = Recommendation.generate_id(workspace_id, "caching_opportunity", "prompts")
            recommendations.append(
                Recommendation(
                    recommendation_id=rec_id,
                    category="caching_opportunity",
                    scope="workspace:prompt_caching",
                    workspace_id=workspace_id,
                    evidence={
                        "large_context_requests": len(large_context_reqs),
                        "cache_eligible_ratio": 0.60,
                    },
                    current_cost=sim.current_cost_usd,
                    projected_cost=sim.projected_cost_usd,
                    expected_saving=sim.expected_saving_usd,
                    confidence=sim.confidence,
                    quality_risk=sim.quality_risk,
                    implementation_plan="Enable prompt caching headers or structured cache breakpoints on static system prompts and system schemas.",
                    rollback_plan="Remove prompt caching markers; upstream providers fall back to standard uncached input billing seamlessly.",
                )
            )

        return recommendations

    def backtest_recommendation(
        self, recommendation: Recommendation, historical_requests: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Replay historical requests through the recommendation simulator to measure variance."""
        if recommendation.category == "model_overkill":
            target_model = recommendation.evidence.get("target_model", "gpt-4o-mini")
            current_model = recommendation.evidence.get("current_model", "gpt-4o")
            sim = simulate_model_switch(
                historical_requests,
                current_model=current_model,
                target_model=target_model,
            )
            backtested_saving = sim.expected_saving_usd
        elif recommendation.category == "retry_reduction":
            sim = simulate_retry_reduction(historical_requests)
            backtested_saving = sim.expected_saving_usd
        else:
            sim = simulate_prompt_caching(historical_requests)
            backtested_saving = sim.expected_saving_usd

        predicted_saving = recommendation.expected_saving
        variance_usd = abs(predicted_saving - backtested_saving)
        variance_pct = (
            round((variance_usd / predicted_saving) * 100, 2)
            if predicted_saving > 0
            else 0.0
        )

        return {
            "recommendation_id": recommendation.recommendation_id,
            "category": recommendation.category,
            "predicted_saving_usd": predicted_saving,
            "backtested_saving_usd": backtested_saving,
            "variance_usd": round(variance_usd, 6),
            "variance_percentage": variance_pct,
            "historical_requests_evaluated": len(historical_requests),
            "backtest_status": "PASS" if variance_pct < 20.0 else "REVIEW_REQUIRED",
        }
