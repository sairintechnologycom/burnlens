"""Cost confidence: how much of a spend figure BurnLens can stand behind.

The two things worth guarding are the ones that make the number lie:

* **Unpriced spend is invisible to dollars.** A row with tokens and no price
  contributes $0, so a dollar-weighted score would report 100% confidence on a
  workspace whose most expensive model has no price at all. The ratio is counted
  by requests for exactly that reason, and this file pins it.
* **It stays a ratio.** `confidence_pct` is the share of requests in any class
  except `unpriced` — no per-class weights. A weighted index is not auditable,
  and this file fails if one is reintroduced.
* **Reconciled does not mean priced.** A provider can agree with its bill on the
  models we price and still be serving one we do not. `unpriced` has to outrank
  `reconciled`, or the badge hides the hole.
"""
import pytest

from burnlens_cloud.reconciliation import build_confidence, classify_row


def row(provider, model, state, is_scan, requests, cost):
    return {
        "provider": provider,
        "model": model,
        "pricing_state": state,
        "is_scan": is_scan,
        "requests": requests,
        "cost": cost,
    }


# ----------------------------------------------------------------- classification


def cls(*args):
    verdict = classify_row(*args)
    return verdict[0] if verdict else None


def test_unpriced_outranks_a_reconciled_provider():
    assert cls("unpriced", False, "reconciled") == "unpriced"


def test_reconciled_provider_outranks_scan_origin():
    # The provider's bill covers agent traffic too, so a reconciled comparison
    # is stronger evidence than "the agent's own log said so".
    assert cls("priced", True, "reconciled") == "reconciled"
    assert cls("priced", True, "drifted") == "estimated"
    assert cls("priced", True, None) == "estimated"


def test_priced_without_reconciliation_is_calculated():
    assert cls("priced", False, None) == "calculated"
    assert cls("priced", False, "unreconciled") == "calculated"


def test_rows_with_no_usage_are_not_a_confidence_question():
    assert classify_row("no_usage", False, "reconciled") is None


def test_every_class_carries_a_machine_readable_reason():
    # The "why" has to survive to next year without anyone reverse-engineering it.
    assert classify_row("priced", True, None)[1] == "agent_self_reported_tokens"
    assert classify_row("priced", False, None)[1] == "priced_from_pricing_table"
    assert classify_row("priced", False, "reconciled")[1] == "provider_bill_agreed"
    assert classify_row("unpriced", False, None)[1] == "model_has_no_price"


def test_stored_unpriced_outranks_a_positive_cost():
    # Local class is is_model_priced, not cost_usd. A sentinel 0 is not the
    # only unpriced shape — and a priced model can land at $0 after rounding.
    assert cls("priced", False, None, "unpriced") == "unpriced"


def test_stored_calculated_is_not_unpriced_at_zero_cost():
    assert cls("unpriced", False, None, "calculated") == "calculated"


def test_stored_estimated_still_reconciles_when_the_bill_agrees():
    assert cls("priced", True, "reconciled", "estimated") == "reconciled"


def test_missing_class_still_infers_from_source_and_cost():
    assert cls("priced", True, None, None) == "estimated"
    assert cls("priced", False, None, None) == "calculated"


# ----------------------------------------------------------------------- scoring


def test_unpriced_spend_drags_the_score_even_though_it_adds_no_dollars():
    rows = [
        row("openai", "gpt-5", "priced", False, 50, 10.0),
        row("openai", "mystery-model", "unpriced", False, 50, 0.0),
    ]
    c = build_confidence(rows, {}, 30)

    # Dollars cannot see the gap: every dollar we have is calculated.
    assert c.total_cost_usd == pytest.approx(10.0)
    assert c.calculated.share_pct == pytest.approx(100.0)
    # Requests can. Half the traffic is unpriced, so half the ratio is gone.
    assert c.unpriced.requests == 50
    assert c.confidence_pct == pytest.approx(50.0)


def test_confidence_is_an_unweighted_ratio_not_a_score():
    # Every request is classified; none is unpriced. A weighted index would
    # discount the estimated and calculated halves and land below 100.
    rows = [
        row("openai", "gpt-5", "priced", False, 25, 5.0),
        row("anthropic", "claude", "priced", True, 25, 5.0),
        row("google", "gemini", "priced", False, 50, 10.0),
    ]
    c = build_confidence(rows, {"google": "reconciled"}, 30)
    assert c.confidence_pct == pytest.approx(100.0)


def test_reconciled_spend_pct_is_dollar_weighted_unlike_confidence():
    # The blind spot the request ratio has: one huge unreconciled call next to a
    # pile of tiny reconciled ones. Requests say "fine", dollars say otherwise.
    rows = [
        row("openai", "gpt-5", "priced", False, 99, 1.0),
        row("anthropic", "claude", "priced", False, 1, 99.0),
    ]
    c = build_confidence(rows, {"openai": "reconciled"}, 30)
    assert c.confidence_pct == pytest.approx(100.0)
    assert c.reconciled_spend_pct == pytest.approx(1.0)


def test_reasons_count_requests_per_basis():
    rows = [
        row("openai", "gpt-5", "priced", False, 4, 1.0),
        row("anthropic", "claude", "priced", True, 6, 2.0),
    ]
    assert build_confidence(rows, {}, 30).reasons == {
        "priced_from_pricing_table": 4,
        "agent_self_reported_tokens": 6,
    }


def test_full_reconciled_coverage_scores_100():
    rows = [row("openai", "gpt-5", "priced", False, 10, 5.0)]
    c = build_confidence(rows, {"openai": "reconciled"}, 30)
    assert c.confidence_pct == pytest.approx(100.0)
    assert c.reconciled.cost_usd == pytest.approx(5.0)
    assert c.gaps == []


def test_no_usage_rows_neither_help_nor_hurt():
    priced = [row("openai", "gpt-5", "priced", False, 10, 5.0)]
    with_errors = priced + [row("openai", "gpt-5", "no_usage", False, 999, 0.0)]
    assert (
        build_confidence(with_errors, {"openai": "reconciled"}, 30).confidence_pct
        == build_confidence(priced, {"openai": "reconciled"}, 30).confidence_pct
    )


def test_empty_workspace_does_not_divide_by_zero():
    c = build_confidence([], {}, 30)
    assert c.confidence_pct == 0.0
    assert c.total_requests == 0
    assert c.calculated.share_pct == 0.0


# -------------------------------------------------------------------------- gaps


def test_every_unpriced_model_is_named_as_a_gap():
    rows = [
        row("openai", "mystery-a", "unpriced", False, 3, 0.0),
        row("google", "mystery-b", "unpriced", False, 7, 0.0),
    ]
    gaps = {g.model: g for g in build_confidence(rows, {}, 30).gaps if g.reason == "unpriced"}
    assert set(gaps) == {"mystery-a", "mystery-b"}
    # Largest gap first — the one worth fixing leads.
    assert build_confidence(rows, {}, 30).gaps[0].model == "mystery-b"
    assert gaps["mystery-b"].requests == 7


def test_a_provider_with_spend_and_no_billing_key_is_a_gap():
    rows = [row("anthropic", "claude", "priced", False, 5, 2.0)]
    gaps = [g for g in build_confidence(rows, {}, 30).gaps if g.provider == "anthropic"]
    assert [g.reason for g in gaps] == ["no_billing_key"]


def test_drifted_and_unreconciled_providers_are_distinguished():
    rows = [
        row("openai", "gpt-5", "priced", False, 1, 1.0),
        row("anthropic", "claude", "priced", False, 1, 1.0),
    ]
    by_provider = {
        g.provider: g.reason
        for g in build_confidence(rows, {"openai": "drifted", "anthropic": "unreconciled"}, 30).gaps
    }
    assert by_provider == {"openai": "drifted", "anthropic": "unreconciled"}
