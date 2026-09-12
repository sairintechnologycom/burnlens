"""BurnLens Simulation & Recommendations package (BL-AE-003)."""
from burnlens.recommendations.engine import RecommendationEngine
from burnlens.recommendations.models import Recommendation, SimulationResult
from burnlens.recommendations.simulator import (
    simulate_model_switch,
    simulate_prompt_caching,
    simulate_retry_reduction,
)

__all__ = [
    "Recommendation",
    "SimulationResult",
    "RecommendationEngine",
    "simulate_model_switch",
    "simulate_retry_reduction",
    "simulate_prompt_caching",
]
