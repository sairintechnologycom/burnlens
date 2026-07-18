"""Unit tests for the monthly-spend burn-rate forecast (_budget_forecast).

Pure-function tests — no DB, no app, no mocking. Covers the run-rate projection,
the over-budget flag, the ≥1-day pace-alarm guard, and the no-budget path.
"""
from burnlens_cloud.dashboard_api import _budget_forecast


def test_on_pace_to_exceed_midmonth():
    # 15 days into a 30-day month, spent $50 of an $80 cap → forecast ~$100.
    r = _budget_forecast(spent_usd=50.0, elapsed_days_frac=15.0, period_days=30, budget_usd=80.0)
    assert r["forecast_usd"] == 100.0
    assert r["is_on_pace_to_exceed"] is True
    assert r["is_over_budget"] is False
    assert r["pct_used"] == 62.5
    assert r["remaining_usd"] == 30.0


def test_over_budget_suppresses_pace_alarm():
    r = _budget_forecast(spent_usd=90.0, elapsed_days_frac=20.0, period_days=30, budget_usd=80.0)
    assert r["is_over_budget"] is True
    assert r["is_on_pace_to_exceed"] is False   # already over → not "on pace to"
    assert r["remaining_usd"] == 0.0            # floored, never negative


def test_hour_one_spike_does_not_cry_wolf():
    # 0.2 days in, $5 spent → forecast is a huge $750, but < 1 day of data
    # so the pace alarm stays quiet.
    r = _budget_forecast(spent_usd=5.0, elapsed_days_frac=0.2, period_days=30, budget_usd=80.0)
    assert r["forecast_usd"] == 750.0
    assert r["is_on_pace_to_exceed"] is False


def test_under_pace_stays_calm():
    r = _budget_forecast(spent_usd=20.0, elapsed_days_frac=15.0, period_days=30, budget_usd=80.0)
    assert r["forecast_usd"] == 40.0
    assert r["is_on_pace_to_exceed"] is False


def test_no_budget_still_forecasts():
    r = _budget_forecast(spent_usd=50.0, elapsed_days_frac=10.0, period_days=30, budget_usd=None)
    assert r["forecast_usd"] == 150.0           # still projects spend
    assert r["budget_usd"] is None
    assert r["remaining_usd"] is None
    assert r["pct_used"] is None
    assert r["is_over_budget"] is False
    assert r["is_on_pace_to_exceed"] is False


def test_zero_elapsed_no_divide_by_zero():
    r = _budget_forecast(spent_usd=0.0, elapsed_days_frac=0.0, period_days=31, budget_usd=100.0)
    assert r["forecast_usd"] == 0.0
    assert r["elapsed_days"] == 0
    assert r["period_days"] == 31
