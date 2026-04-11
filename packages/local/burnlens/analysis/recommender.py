"""Model recommendation engine — analyses usage patterns and suggests cheaper alternatives.

Pure business logic (ModelRecommendation, projection functions) is in
burnlens_core.analysis.recommender. This module re-exports those and adds the
DB-dependent analysis functions.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import aiosqlite

from burnlens_core.analysis.recommender import (  # noqa: F401
    ModelRecommendation,
    cheaper_equivalent,
    get_projection_pricing,
    match_overkill_model,
    match_reasoning_model,
    project_cost,
)

# Backward-compatible aliases for old private names used by tests
_project_cost = project_cost
_match_overkill_model = match_overkill_model
_match_reasoning_model = match_reasoning_model
_get_pricing = get_projection_pricing

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB-dependent analysis (local only)
# ---------------------------------------------------------------------------


async def analyse_model_fit(
    db_path: str,
    days: int = 30,
) -> list[ModelRecommendation]:
    """Analyse usage patterns and return model switch recommendations."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    recommendations: list[ModelRecommendation] = []

    # Rule 1 — model overkill: aggregate by (model, feature_tag)
    overkill_recs = await _check_model_overkill(db_path, since)
    recommendations.extend(overkill_recs)

    # Rule 2 — reasoning models for simple tasks
    reasoning_recs = await _check_reasoning_overkill(db_path, since)
    recommendations.extend(reasoning_recs)

    # Rule 3 — cache opportunity
    cache_recs = await _check_cache_opportunity(db_path)
    recommendations.extend(cache_recs)

    # Sort by projected saving descending
    recommendations.sort(key=lambda r: r.projected_saving, reverse=True)
    return recommendations


async def _check_model_overkill(
    db_path: str,
    since: str,
) -> list[ModelRecommendation]:
    """Rule 1: expensive models used for short-output tasks."""
    recs: list[ModelRecommendation] = []

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                model,
                COALESCE(json_extract(tags, '$.feature'), '(untagged)') AS feature_tag,
                COUNT(*) AS request_count,
                AVG(input_tokens)  AS avg_input_tokens,
                AVG(output_tokens) AS avg_output_tokens,
                SUM(cost_usd)      AS total_cost
            FROM requests
            WHERE timestamp >= ?
            GROUP BY model, feature_tag
            """,
            (since,),
        )
        rows = await cursor.fetchall()

    for row in rows:
        model = row["model"]
        matched_key = match_overkill_model(model)
        if matched_key is None:
            continue

        avg_out = float(row["avg_output_tokens"] or 0)
        count = int(row["request_count"])
        if avg_out >= 200 or count <= 20:
            continue

        suggested = cheaper_equivalent(matched_key)
        if suggested is None:
            continue
        avg_in = float(row["avg_input_tokens"] or 0)
        current_cost = float(row["total_cost"] or 0)

        projected = project_cost(count, avg_in, avg_out, suggested)
        if projected is None:
            continue

        saving = current_cost - projected
        pct = (saving / current_cost * 100) if current_cost > 0 else 0.0
        confidence = "high" if avg_out < 50 else "medium"

        recs.append(ModelRecommendation(
            current_model=model,
            suggested_model=suggested,
            feature_tag=row["feature_tag"],
            request_count=count,
            avg_output_tokens=round(avg_out, 1),
            current_cost=round(current_cost, 6),
            projected_cost=round(projected, 6),
            projected_saving=round(saving, 6),
            saving_pct=round(pct, 1),
            confidence=confidence,
            reason=(
                f"Average output is only {avg_out:.0f} tokens across {count} requests "
                f"— {suggested} can handle short tasks at a fraction of the cost"
            ),
        ))

    return recs


async def _check_reasoning_overkill(
    db_path: str,
    since: str,
) -> list[ModelRecommendation]:
    """Rule 2: reasoning models used for tasks with low output tokens."""
    recs: list[ModelRecommendation] = []

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                model,
                COALESCE(json_extract(tags, '$.feature'), '(untagged)') AS feature_tag,
                COUNT(*) AS request_count,
                AVG(input_tokens)     AS avg_input_tokens,
                AVG(output_tokens)    AS avg_output_tokens,
                AVG(reasoning_tokens) AS avg_reasoning_tokens,
                SUM(cost_usd)         AS total_cost
            FROM requests
            WHERE timestamp >= ?
            GROUP BY model, feature_tag
            """,
            (since,),
        )
        rows = await cursor.fetchall()

    for row in rows:
        model = row["model"]
        matched = match_reasoning_model(model)
        if matched is None:
            continue

        avg_out = float(row["avg_output_tokens"] or 0)
        avg_reasoning = float(row["avg_reasoning_tokens"] or 0)
        count = int(row["request_count"])

        if avg_out >= 100 or avg_out == 0:
            continue
        if avg_reasoning <= avg_out * 5:
            continue

        suggested = "gpt-4o-mini"
        avg_in = float(row["avg_input_tokens"] or 0)
        current_cost = float(row["total_cost"] or 0)

        projected = project_cost(count, avg_in, avg_out, suggested)
        if projected is None:
            continue

        saving = current_cost - projected
        pct = (saving / current_cost * 100) if current_cost > 0 else 0.0
        ratio = avg_reasoning / avg_out if avg_out > 0 else 0

        recs.append(ModelRecommendation(
            current_model=model,
            suggested_model=suggested,
            feature_tag=row["feature_tag"],
            request_count=count,
            avg_output_tokens=round(avg_out, 1),
            current_cost=round(current_cost, 6),
            projected_cost=round(projected, 6),
            projected_saving=round(saving, 6),
            saving_pct=round(pct, 1),
            confidence="medium",
            reason=(
                f"Reasoning tokens are {ratio:.0f}x output tokens "
                f"— this task may not need deep reasoning"
            ),
        ))

    return recs


async def _check_cache_opportunity(db_path: str) -> list[ModelRecommendation]:
    """Rule 3: high-volume features with large prompts that could use caching."""
    recs: list[ModelRecommendation] = []
    since_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                model,
                COALESCE(json_extract(tags, '$.feature'), '(untagged)') AS feature_tag,
                COUNT(*) AS request_count,
                AVG(input_tokens)  AS avg_input_tokens,
                AVG(output_tokens) AS avg_output_tokens,
                SUM(cost_usd)      AS total_cost
            FROM requests
            WHERE timestamp >= ?
              AND json_extract(tags, '$.feature') IS NOT NULL
            GROUP BY model, feature_tag
            """,
            (since_24h,),
        )
        rows = await cursor.fetchall()

    for row in rows:
        count = int(row["request_count"])
        avg_in = float(row["avg_input_tokens"] or 0)
        if count <= 50 or avg_in <= 2000:
            continue

        current_cost = float(row["total_cost"] or 0)
        saving_pct = 30.0
        saving = current_cost * saving_pct / 100

        recs.append(ModelRecommendation(
            current_model=row["model"],
            suggested_model="prompt-caching",
            feature_tag=row["feature_tag"],
            request_count=count,
            avg_output_tokens=round(float(row["avg_output_tokens"] or 0), 1),
            current_cost=round(current_cost, 6),
            projected_cost=round(current_cost - saving, 6),
            projected_saving=round(saving, 6),
            saving_pct=round(saving_pct, 1),
            confidence="low",
            reason=(
                f"High-volume feature with large prompts ({avg_in:.0f} avg input tokens, "
                f"{count} requests/24h) — prompt caching could save ~{saving_pct:.0f}%"
            ),
        ))

    return recs
