"""Deterministic simulation engine for AI optimization candidates (BL-AE-003).

Pure functions that project costs, expected savings, confidence, and quality risks
by repricing real request history through canonical pricing tables.
"""
from __future__ import annotations

import logging
from typing import Any

from burnlens.cost.calculator import TokenUsage, calculate_cost
from burnlens.recommendations.models import SimulationResult

logger = logging.getLogger(__name__)


def simulate_model_switch(
    requests: list[dict[str, Any]],
    current_model: str,
    target_model: str,
    target_provider: str | None = None,
    quality_risk: float = 0.015,
) -> SimulationResult:
    """Simulate switching requests from an expensive model to a cheaper tier."""
    matching = [r for r in requests if r.get("model") == current_model]
    if not matching:
        return SimulationResult(
            category="model_overkill",
            current_cost_usd=0.0,
            projected_cost_usd=0.0,
            expected_saving_usd=0.0,
            confidence=0.0,
            quality_risk=quality_risk,
            affected_requests_count=0,
            details={"message": f"No requests found matching model {current_model}"},
        )

    current_total = 0.0
    projected_total = 0.0

    for r in matching:
        c_cost = float(r.get("cost_usd", 0.0))
        current_total += c_cost

        prov = target_provider or r.get("provider", "openai")
        usage = TokenUsage(
            input_tokens=int(r.get("input_tokens", 0)),
            output_tokens=int(r.get("output_tokens", 0)),
            cache_read_tokens=int(r.get("cache_read_tokens", 0)),
            cache_write_tokens=int(r.get("cache_write_tokens", 0)),
            reasoning_tokens=int(r.get("reasoning_tokens", 0)),
        )
        sim_cost = calculate_cost(prov, target_model, usage)
        if sim_cost is not None:
            projected_total += sim_cost
        else:
            # Fallback if unpriced
            projected_total += c_cost

    expected_saving = max(0.0, current_total - projected_total)
    confidence = 0.94 if len(matching) >= 5 else 0.80

    return SimulationResult(
        category="model_overkill",
        current_cost_usd=round(current_total, 6),
        projected_cost_usd=round(projected_total, 6),
        expected_saving_usd=round(expected_saving, 6),
        confidence=confidence,
        quality_risk=quality_risk,
        affected_requests_count=len(matching),
        details={
            "current_model": current_model,
            "target_model": target_model,
            "target_provider": target_provider or matching[0].get("provider"),
        },
    )


def simulate_retry_reduction(
    requests: list[dict[str, Any]],
    reduction_factor: float = 0.75,
) -> SimulationResult:
    """Simulate savings achieved by capping retry loops and backoff storms."""
    total_cost = sum(float(r.get("cost_usd", 0.0)) for r in requests)
    error_requests = [r for r in requests if int(r.get("status_code", 200)) >= 400]
    error_cost = sum(float(r.get("cost_usd", 0.0)) for r in error_requests)

    expected_saving = error_cost * reduction_factor
    projected_cost = max(0.0, total_cost - expected_saving)
    confidence = 0.92 if error_requests else 0.50

    return SimulationResult(
        category="retry_reduction",
        current_cost_usd=round(total_cost, 6),
        projected_cost_usd=round(projected_cost, 6),
        expected_saving_usd=round(expected_saving, 6),
        confidence=confidence,
        quality_risk=0.002,  # Very low quality risk when stopping duplicate failing attempts
        affected_requests_count=len(error_requests),
        details={
            "total_error_requests": len(error_requests),
            "raw_retry_waste_usd": round(error_cost, 6),
            "reduction_factor": reduction_factor,
        },
    )


def simulate_prompt_caching(
    requests: list[dict[str, Any]],
    cache_eligible_ratio: float = 0.50,
) -> SimulationResult:
    """Simulate savings from enabling prompt caching on repetitive contexts."""
    total_cost = sum(float(r.get("cost_usd", 0.0)) for r in requests)
    # Estimate ~50% discount on cache-eligible input tokens
    potential_saving = total_cost * 0.35 * cache_eligible_ratio
    projected_cost = max(0.0, total_cost - potential_saving)

    return SimulationResult(
        category="caching_opportunity",
        current_cost_usd=round(total_cost, 6),
        projected_cost_usd=round(projected_cost, 6),
        expected_saving_usd=round(potential_saving, 6),
        confidence=0.88,
        quality_risk=0.0,  # Zero quality risk with prompt caching
        affected_requests_count=len(requests),
        details={"cache_eligible_ratio": cache_eligible_ratio},
    )
