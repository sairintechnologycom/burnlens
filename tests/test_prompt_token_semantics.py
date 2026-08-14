"""Guard the two incompatible ways providers report cached prompt tokens.

OpenAI and Google report the whole prompt as one number with the cached share
as a SUBSET of it. Anthropic reports uncached input and cache reads as DISJOINT
numbers. Assuming either shape is silently wrong for the other, in both
directions and in two different places:

* summing the columns double-counts the cache for OpenAI-style providers
  (measured live 2026-08-14: a 12k prompt with 11k cached rendered as 23k)
* subtracting the cache under-bills the uncached input for Anthropic-style ones

Neither failure raises anything — the wrong number is always plausible.
"""
from __future__ import annotations

import sqlite3

import pytest

from burnlens.cost.calculator import TokenUsage, calculate_cost
from burnlens.providers.registry import inclusive_prompt_token_providers


def test_registry_flags_openai_family_and_not_anthropic():
    inclusive = inclusive_prompt_token_providers()
    for p in ("openai", "azure", "google", "groq", "together", "mistral", "xai", "deepseek"):
        assert p in inclusive, f"{p} speaks the OpenAI/Google wire format"
    for p in ("anthropic", "bedrock"):
        assert p not in inclusive, f"{p} reports cache tokens disjointly"


def test_cloud_copy_has_not_drifted():
    """The backend cannot import the proxy's registry, so it duplicates the list."""
    pytest.importorskip("burnlens_cloud.models", reason="cloud deps not installed")
    from burnlens_cloud.models import INCLUSIVE_PROMPT_TOKEN_PROVIDERS

    assert tuple(INCLUSIVE_PROMPT_TOKEN_PROVIDERS) == inclusive_prompt_token_providers(), (
        "burnlens_cloud.models.INCLUSIVE_PROMPT_TOKEN_PROVIDERS drifted from the "
        "registry — the hosted run view would report a different prompt size "
        "than `burnlens runs` for the same data"
    )


# ---------------------------------------------------------------------------
# Cost: the disjoint case must not have its uncached input subtracted away
# ---------------------------------------------------------------------------


def test_anthropic_partial_cache_bills_all_uncached_input():
    """input and cache_read are disjoint, so nothing may be subtracted.

    Before the fix this billed 2000 input tokens instead of 5000 — invisible,
    because the total was still a plausible number.
    """
    usage = TokenUsage(input_tokens=5000, output_tokens=0, cache_read_tokens=3000)
    cost = calculate_cost("anthropic", "claude-sonnet-4-5-20250929", usage)

    input_only = calculate_cost(
        "anthropic", "claude-sonnet-4-5-20250929", TokenUsage(input_tokens=5000)
    )
    cache_only = calculate_cost(
        "anthropic", "claude-sonnet-4-5-20250929", TokenUsage(cache_read_tokens=3000)
    )
    assert cost == pytest.approx(input_only + cache_only)


def test_openai_cached_share_is_not_billed_twice():
    """prompt_tokens includes the cache, so the cached share bills at its own rate."""
    usage = TokenUsage(input_tokens=12000, output_tokens=0, cache_read_tokens=11000)
    cost = calculate_cost("openai", "gpt-4o-mini", usage)

    uncached = calculate_cost("openai", "gpt-4o-mini", TokenUsage(input_tokens=1000))
    cached = calculate_cost("openai", "gpt-4o-mini", TokenUsage(cache_read_tokens=11000))
    assert cost == pytest.approx(uncached + cached)


# ---------------------------------------------------------------------------
# Display: the run view's prompt total, against real SQL
# ---------------------------------------------------------------------------


def _db_with_two_rows(path: str) -> None:
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE requests (provider TEXT, input_tokens INT, "
        "cache_read_tokens INT, cache_write_tokens INT)"
    )
    db.executemany(
        "INSERT INTO requests VALUES (?, ?, ?, ?)",
        [
            # OpenAI: 12k prompt of which 11k cached. Whole prompt = 12000.
            ("openai", 12000, 11000, 0),
            # Anthropic: 6 uncached + 120k cache read. Whole prompt = 120006.
            ("anthropic", 6, 120000, 0),
        ],
    )
    db.commit()
    db.close()


def test_prompt_tokens_sql_is_correct_for_both_conventions(tmp_path):
    from burnlens.analysis.runs import _prompt_tokens_sql

    path = str(tmp_path / "t.db")
    _db_with_two_rows(path)
    db = sqlite3.connect(path)
    rows = dict(
        db.execute(f"SELECT provider, {_prompt_tokens_sql()} FROM requests").fetchall()
    )

    assert rows["openai"] == 12000, "cached share double-counted"
    assert rows["anthropic"] == 120006, "disjoint cache dropped"


def test_prompt_tokens_sql_survives_an_empty_registry(monkeypatch):
    """A bare import that registered nothing must not silently emit `IN ()`."""
    import burnlens.providers.registry as reg

    monkeypatch.setattr(reg, "inclusive_prompt_token_providers", lambda: ())
    from burnlens.analysis.runs import _prompt_tokens_sql

    sql = _prompt_tokens_sql()
    assert "IN ()" not in sql
    assert sql == "input_tokens + cache_read_tokens + cache_write_tokens"
