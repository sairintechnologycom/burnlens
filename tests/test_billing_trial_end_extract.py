"""`_extract_trial_end` against the payload shape Paddle actually sends.

Paddle puts trial dates on the LINE ITEM, not the subscription. The original
implementation read only `data["trial_dates"]["ends_at"]`, a key that never
exists, so it returned None for every trialing subscription. Production showed
`trial_ends_at = NULL` on a subscription that was genuinely mid-trial, and
because `settings/page.tsx` gates the "Trial ends: …" line on that field being
truthy, a trialing customer got no in-app warning of when they'd be charged.

The payload below is the real shape, taken from
`client.subscriptions.get("sub_01m0238dam04x47aqc7bcwq5qr")` on 2026-08-15:
`sub.trial_dates` absent, `sub.items[0].trial_dates` populated.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/burnlens_test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests")
os.environ.setdefault("ENVIRONMENT", "test")

from burnlens_cloud.billing import _extract_trial_end  # noqa: E402


def test_reads_trial_dates_from_the_line_item():
    """The regression: this is the shape Paddle sends, and it used to return None."""
    payload = {
        "id": "sub_01m0238dam04x47aqc7bcwq5qr",
        "status": "trialing",
        # NOTE: no top-level "trial_dates" — Paddle does not send one.
        "items": [
            {
                "status": "trialing",
                "trial_dates": {
                    "starts_at": "2026-08-15T06:55:25.519Z",
                    "ends_at": "2026-08-22T06:55:25.519Z",
                },
            }
        ],
    }
    assert _extract_trial_end(payload) == datetime(
        2026, 8, 22, 6, 55, 25, 519000, tzinfo=timezone.utc
    )


def test_falls_back_to_a_top_level_trial_dates():
    """Kept so a payload carrying it top-level still works."""
    payload = {"trial_dates": {"ends_at": "2026-08-22T06:55:25.519Z"}}
    assert _extract_trial_end(payload) == datetime(
        2026, 8, 22, 6, 55, 25, 519000, tzinfo=timezone.utc
    )


def test_prefers_the_item_when_both_are_present():
    payload = {
        "trial_dates": {"ends_at": "2020-01-01T00:00:00Z"},
        "items": [{"trial_dates": {"ends_at": "2026-08-22T06:55:25.519Z"}}],
    }
    assert _extract_trial_end(payload).year == 2026


def test_returns_none_when_there_is_no_trial():
    # A non-trial subscription: items exist but carry trial_dates: null. Must be
    # None, not an exception and not a bogus date — `trial_ends_at` NULL is the
    # correct representation of "not on a trial".
    assert _extract_trial_end({"items": [{"trial_dates": None}], "status": "active"}) is None
    assert _extract_trial_end({"items": []}) is None
    assert _extract_trial_end({}) is None


def test_skips_items_without_trial_dates_and_finds_a_later_one():
    payload = {
        "items": [
            {"trial_dates": None},
            {"trial_dates": {"ends_at": "2026-08-22T06:55:25.519Z"}},
        ]
    }
    assert _extract_trial_end(payload).day == 22


def test_malformed_input_returns_none_rather_than_raising():
    # This runs inside a webhook handler; raising would fail the delivery.
    assert _extract_trial_end({"items": "not-a-list"}) is None
    assert _extract_trial_end({"items": [{"trial_dates": {"ends_at": "garbage"}}]}) is None
