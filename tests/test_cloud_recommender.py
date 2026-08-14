"""BL-F4: cloud recommendations use the canonical Python engine."""
from __future__ import annotations

from datetime import datetime, timezone

from burnlens_cloud.findings import recommendations_from_records
from burnlens_cloud.models import RecommendationItem


def _row(**over):
    row = {
        "model": "gpt-4o",
        "input_tokens": 500,
        "output_tokens": 40,
        "reasoning_tokens": 0,
        "cost_usd": 0.50,
        "tags": {"feature": "chat"},
        "ts": datetime.now(timezone.utc),
    }
    row.update(over)
    return row


def test_seeded_overkill_yields_recommendation_item():
    recs = recommendations_from_records([_row() for _ in range(21)])
    assert recs
    rec = recs[0]
    assert isinstance(rec, RecommendationItem)
    assert rec.current_model == "gpt-4o"
    assert rec.suggested_model == "gpt-4o-mini"
    assert rec.feature_tag == "chat"
    assert rec.projected_saving > 0
    RecommendationItem.model_validate(rec.model_dump())


def test_short_volume_does_not_recommend():
    assert recommendations_from_records([_row() for _ in range(5)]) == []
