"""Tests for the model recommendation engine."""
from __future__ import annotations

import pytest
import pytest_asyncio

from burnlens.storage.database import init_db, insert_request
from burnlens.storage.models import RequestRecord
from burnlens.analysis.recommender import (
    ModelRecommendation,
    analyse_model_fit,
    _project_cost,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed(db: str, records: list[dict]) -> None:
    """Insert multiple request records into the test database."""
    for r in records:
        rec = RequestRecord(
            provider=r.get("provider", "openai"),
            model=r["model"],
            request_path="/v1/chat/completions",
            input_tokens=r.get("input_tokens", 500),
            output_tokens=r.get("output_tokens", 100),
            reasoning_tokens=r.get("reasoning_tokens", 0),
            cost_usd=r.get("cost_usd", 0.01),
            tags=r.get("tags", {}),
        )
        await insert_request(db, rec)


# ---------------------------------------------------------------------------
# Rule 1 — Model overkill
# ---------------------------------------------------------------------------


class TestModelOverkillHighConfidence:
    """avg_output_tokens < 50 → high confidence."""

    @pytest.mark.asyncio
    async def test_model_overkill_high_confidence_below_50_tokens(self, initialized_db: str):
        # 25 requests with gpt-4o, avg 30 output tokens
        await _seed(initialized_db, [
            {"model": "gpt-4o", "input_tokens": 500, "output_tokens": 30,
             "cost_usd": 0.005, "tags": {"feature": "classify"}}
            for _ in range(25)
        ])

        recs = await analyse_model_fit(initialized_db, days=30)
        overkill = [r for r in recs if r.current_model == "gpt-4o" and r.suggested_model == "gpt-4o-mini"]
        assert len(overkill) == 1
        assert overkill[0].confidence == "high"
        assert overkill[0].feature_tag == "classify"
        assert overkill[0].request_count == 25

    @pytest.mark.asyncio
    async def test_model_overkill_medium_confidence_50_to_200_tokens(self, initialized_db: str):
        # 25 requests with gpt-4o, avg 150 output tokens
        await _seed(initialized_db, [
            {"model": "gpt-4o", "input_tokens": 800, "output_tokens": 150,
             "cost_usd": 0.01, "tags": {"feature": "summarize"}}
            for _ in range(25)
        ])

        recs = await analyse_model_fit(initialized_db, days=30)
        overkill = [r for r in recs if r.current_model == "gpt-4o"]
        assert len(overkill) == 1
        assert overkill[0].confidence == "medium"


class TestNoRecommendationForHighOutput:
    """Models with avg_output_tokens >= 200 should not be flagged."""

    @pytest.mark.asyncio
    async def test_no_recommendation_for_high_output_models(self, initialized_db: str):
        await _seed(initialized_db, [
            {"model": "gpt-4o", "input_tokens": 1000, "output_tokens": 500,
             "cost_usd": 0.02, "tags": {"feature": "generate"}}
            for _ in range(30)
        ])

        recs = await analyse_model_fit(initialized_db, days=30)
        overkill = [r for r in recs if r.current_model == "gpt-4o" and r.suggested_model == "gpt-4o-mini"]
        assert len(overkill) == 0


# ---------------------------------------------------------------------------
# Rule 2 — Reasoning models for simple tasks
# ---------------------------------------------------------------------------


class TestReasoningModelOverkill:
    @pytest.mark.asyncio
    async def test_reasoning_model_flagged_for_simple_tasks(self, initialized_db: str):
        # o1 with avg 50 output tokens but 500 reasoning tokens (10x)
        await _seed(initialized_db, [
            {"model": "o1", "input_tokens": 1000, "output_tokens": 50,
             "reasoning_tokens": 500, "cost_usd": 0.10,
             "tags": {"feature": "route"}}
            for _ in range(25)
        ])

        recs = await analyse_model_fit(initialized_db, days=30)
        reasoning = [r for r in recs if r.current_model == "o1" and r.suggested_model == "gpt-4o-mini"]
        assert len(reasoning) == 1
        assert "reasoning tokens" in reasoning[0].reason.lower()
        assert reasoning[0].confidence == "medium"

    @pytest.mark.asyncio
    async def test_reasoning_model_not_flagged_when_output_high(self, initialized_db: str):
        # o1 with avg 200 output tokens — should not be flagged (>= 100)
        await _seed(initialized_db, [
            {"model": "o1", "input_tokens": 1000, "output_tokens": 200,
             "reasoning_tokens": 2000, "cost_usd": 0.15,
             "tags": {"feature": "analyze"}}
            for _ in range(25)
        ])

        recs = await analyse_model_fit(initialized_db, days=30)
        reasoning = [r for r in recs if r.current_model == "o1" and r.suggested_model == "gpt-4o-mini"]
        assert len(reasoning) == 0


# ---------------------------------------------------------------------------
# Cost projection math
# ---------------------------------------------------------------------------


class TestCostProjection:
    def test_cost_projection_math_correct(self):
        # 100 requests, 500 avg input, 50 avg output, gpt-4o-mini pricing
        # input: 100 * 500 / 1_000_000 * 0.15 = 0.0075
        # output: 100 * 50 / 1_000_000 * 0.60 = 0.003
        # total: 0.0105
        result = _project_cost(100, 500, 50, "gpt-4o-mini")
        assert result is not None
        assert abs(result - 0.0105) < 1e-9

    @pytest.mark.asyncio
    async def test_saving_pct_correct(self, initialized_db: str):
        # Seed data where we know the exact cost
        await _seed(initialized_db, [
            {"model": "gpt-4o", "input_tokens": 500, "output_tokens": 30,
             "cost_usd": 0.01, "tags": {"feature": "tag"}}
            for _ in range(25)
        ])

        recs = await analyse_model_fit(initialized_db, days=30)
        overkill = [r for r in recs if r.current_model == "gpt-4o"]
        assert len(overkill) == 1

        rec = overkill[0]
        # Verify saving_pct = (projected_saving / current_cost) * 100
        expected_pct = (rec.projected_saving / rec.current_cost) * 100
        assert abs(rec.saving_pct - round(expected_pct, 1)) < 0.1

        # Verify projected_saving = current_cost - projected_cost
        assert abs(rec.projected_saving - (rec.current_cost - rec.projected_cost)) < 1e-4

    def test_unknown_model_returns_none(self):
        result = _project_cost(100, 500, 50, "some-unknown-model")
        assert result is None


# ---------------------------------------------------------------------------
# Empty database
# ---------------------------------------------------------------------------


class TestEmptyDatabase:
    @pytest.mark.asyncio
    async def test_empty_db_returns_no_recommendations(self, initialized_db: str):
        recs = await analyse_model_fit(initialized_db, days=30)
        assert recs == []
