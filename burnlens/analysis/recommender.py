"""Model recommendation engine — analyses usage patterns and suggests cheaper alternatives."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiosqlite

from burnlens.cost.calculator import TokenUsage, calculate_cost, is_model_priced
from burnlens.cost.pricing import get_model_pricing

logger = logging.getLogger(__name__)


@dataclass
class ModelRecommendation:
    """A single recommendation to switch models or enable caching."""

    current_model: str
    suggested_model: str
    feature_tag: str
    request_count: int
    avg_output_tokens: float
    current_cost: float
    projected_cost: float
    projected_saving: float
    saving_pct: float
    confidence: str   # "high" | "medium" | "low"
    reason: str


# ---------------------------------------------------------------------------
# Model downgrade mapping
# ---------------------------------------------------------------------------

# Keys are matched exactly first, then as a prefix (longest key wins), so a
# family key covers every member and dated snapshot of that family without an
# entry per model. That is the point: models ship continuously here — pricing
# is even date-scheduled — and a map keyed on individual model names goes stale
# silently. It did: with only the six entries this held before, `recommend`
# reported "your model usage looks efficient!" on a database where `analyze`
# found $3,528 of model overkill, because the two biggest wasters
# (claude-opus-4-6 at $568, claude-opus-4-7 at $504) matched nothing.
#
# Targets are the cheap tier of the same vendor, not the next rung down. This
# rule only fires on requests averaging under 200 output tokens — classification,
# extraction, routing — and for that shape the small model is the right answer.
#
# The codex line stays inside its own product line: a general-purpose small
# model is not a like-for-like substitute for coding-agent traffic, so
# gpt-5.2-codex is pointed at gpt-5.1-codex-mini rather than gpt-5-mini. The
# rest of that line is already at $1.25/$10, where the swap saves nothing and
# the positive-saving guard drops it.
_CHEAPER_EQUIVALENT: dict[str, str] = {
    # OpenAI
    "gpt-4o": "gpt-4o-mini",
    "gpt-4-turbo": "gpt-4o-mini",
    "gpt-5.2": "gpt-5-mini",
    # Longer key, so it wins over "gpt-5.2" for the codex variant.
    "gpt-5.2-codex": "gpt-5.1-codex-mini",
    "gpt-5.4": "gpt-5.4-mini",
    "gpt-5.5": "gpt-5.6-luna",
    # Cheapest member of the 5.6 family. Terra ($2.5/$15) was the old target
    # and is itself a downgrade candidate, so pointing at it left money behind.
    "gpt-5.6": "gpt-5.6-luna",
    # Anthropic — family prefixes, so opus-4-5 through opus-5 and every dated
    # sonnet snapshot are all covered.
    "claude-opus": "claude-haiku-4-5",
    "claude-sonnet": "claude-haiku-4-5",
    "claude-fable": "claude-haiku-4-5",
    "claude-mythos": "claude-haiku-4-5",
    # Google
    "gemini-1.5-pro": "gemini-1.5-flash",
    "gemini-3.1-pro-preview": "gemini-3.1-flash-lite",
}

# Longest first: "gpt-4-turbo" must win over "gpt-4o" would-be prefixes, and a
# model with its own entry must never be captured by a shorter family key.
_OVERKILL_MODELS = sorted(_CHEAPER_EQUIVALENT, key=len, reverse=True)
_REASONING_MODELS = {"o1", "o3", "o1-mini", "gpt-5.6"}

def _provider_of(model: str) -> str:
    return (
        "anthropic" if model.startswith("claude-")
        else "google" if model.startswith("gemini-")
        else "openai"
    )


def _get_pricing(model: str) -> dict[str, float] | None:
    """Look up projection pricing from the provider's bundled price table."""
    pricing = get_model_pricing(_provider_of(model), model)
    if pricing is None:
        return None
    return {"input": pricing["input_per_million"], "output": pricing["output_per_million"]}


def _project_cost(
    request_count: int,
    avg_input_tokens: float,
    avg_output_tokens: float,
    model: str,
    avg_cache_read_tokens: float = 0.0,
    avg_cache_write_tokens: float = 0.0,
) -> float | None:
    """Project total cost for ``model`` over the given request volume.

    Delegates to ``calculate_cost`` instead of multiplying rates here, because
    the two cached-prompt conventions cannot be hand-written safely: OpenAI and
    Google fold cache reads INTO input_tokens, Anthropic reports them disjoint.

    Ignoring cache tokens is not a small inaccuracy on agent traffic — it is the
    whole prompt. Claude Code's short-output requests record `input_tokens` of
    6 against 121,099 cache-read tokens, so the old rate multiplication
    projected the cheaper model at ~nothing and reported savings of 98.6% and
    99.7%. Carrying the cache tokens over assumes the target model caches the
    same way, which is the closest honest assumption available.
    """
    provider = _provider_of(model)
    if not is_model_priced(provider, model):
        return None
    return calculate_cost(
        provider,
        model,
        TokenUsage(
            input_tokens=round(avg_input_tokens * request_count),
            output_tokens=round(avg_output_tokens * request_count),
            cache_read_tokens=round(avg_cache_read_tokens * request_count),
            cache_write_tokens=round(avg_cache_write_tokens * request_count),
        ),
    )


# ---------------------------------------------------------------------------
# Core analysis
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

    # A recommendation that costs money is not a recommendation. Every rule
    # projects both sides from the same price table, so a non-positive saving
    # means the "cheaper equivalent" is not cheaper for this traffic — e.g.
    # gpt-5.6-luna ($1/$6 per M) prefix-matched the gpt-5.6 family and was told
    # to switch to gpt-5.6-terra ($2.5/$15), reported as "saving -$343.99
    # (-1840.7%)" and summed into the total. Filtered once here rather than in
    # each rule: all three route through this return, and a fourth rule would
    # otherwise have to remember the guard.
    recommendations = [r for r in recommendations if r.projected_saving > 0]

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
                AVG(input_tokens)       AS avg_input_tokens,
                AVG(output_tokens)      AS avg_output_tokens,
                AVG(cache_read_tokens)  AS avg_cache_read_tokens,
                AVG(cache_write_tokens) AS avg_cache_write_tokens,
                SUM(cost_usd)           AS total_cost
            FROM requests
            WHERE timestamp >= ?
              AND output_tokens < 200
            GROUP BY model, feature_tag
            """,
            (since,),
        )
        rows = await cursor.fetchall()

    for row in rows:
        model = row["model"]
        # Check if model matches any overkill key (exact or prefix)
        matched_key = _match_overkill_model(model)
        if matched_key is None:
            continue

        # The SQL already restricts to short-output requests, so this group IS
        # the overkill subset. It used to aggregate every request and require
        # the GROUP's average to be under 200, which meant a model used for a
        # mix of trivial and heavy work never qualified — claude-opus-4-7
        # averages 573 output tokens overall, so its 4,000-odd short-output
        # calls were invisible here while the waste detector flagged every one.
        avg_out = float(row["avg_output_tokens"] or 0)
        count = int(row["request_count"])
        if count <= 20:
            continue

        suggested = _CHEAPER_EQUIVALENT[matched_key]
        avg_in = float(row["avg_input_tokens"] or 0)
        current_cost = float(row["total_cost"] or 0)

        projected = _project_cost(
            count, avg_in, avg_out, suggested,
            float(row["avg_cache_read_tokens"] or 0),
            float(row["avg_cache_write_tokens"] or 0),
        )
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
                f"{count} request(s) produced under 200 output tokens "
                f"(avg {avg_out:.0f}) — {suggested} can handle short tasks at a "
                "fraction of the cost"
            ),
        ))

    return recs


def _match_overkill_model(model: str) -> str | None:
    """Return the overkill key that matches ``model``, or None.

    Keys are tried longest-first so the most specific one wins. A model that is
    already the family's downgrade target matches nothing: gpt-5.6-luna is a
    prefix match on "gpt-5.6", and without this it was told to switch to
    itself's dearer sibling (see the saving guard in analyse_model_fit).
    """
    for key in _OVERKILL_MODELS:
        if model == key or model.startswith(key):
            return None if _CHEAPER_EQUIVALENT[key] == model else key
    return None


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
                AVG(input_tokens)       AS avg_input_tokens,
                AVG(output_tokens)      AS avg_output_tokens,
                AVG(reasoning_tokens)   AS avg_reasoning_tokens,
                AVG(cache_read_tokens)  AS avg_cache_read_tokens,
                AVG(cache_write_tokens) AS avg_cache_write_tokens,
                SUM(cost_usd)           AS total_cost
            FROM requests
            WHERE timestamp >= ?
            GROUP BY model, feature_tag
            """,
            (since,),
        )
        rows = await cursor.fetchall()

    for row in rows:
        model = row["model"]
        matched = _match_reasoning_model(model)
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

        projected = _project_cost(
            count, avg_in, avg_out, suggested,
            float(row["avg_cache_read_tokens"] or 0),
            float(row["avg_cache_write_tokens"] or 0),
        )
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


def _match_reasoning_model(model: str) -> str | None:
    """Return the reasoning model key that matches, or None."""
    for key in _REASONING_MODELS:
        if model == key or model.startswith(key):
            return key
    return None


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
        # Prompt caching typically saves ~50% on input cost; estimate input
        # is ~60% of total cost for large-prompt workloads → ~30% total saving
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
