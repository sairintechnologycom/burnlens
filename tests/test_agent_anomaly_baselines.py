"""Per-agent anomaly baselines (economics graph, Phase D).

The headline guarantee: a replayed synthetic burst on a tagged agent fires
exactly ONE deduplicated alert, naming the multiplier and the deploy that
preceded it -- not one alert per signal that the burst happens to trip.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from burnlens.config import AlertsConfig, BurnLensConfig
from burnlens.detection.anomaly import (
    AnomalyDetector,
    check_active_agents,
    max_requests_in_span,
    parse_timestamp,
)
from burnlens.storage.database import insert_request
from burnlens.storage.models import RequestRecord
from burnlens.storage.queries import get_recent_anomaly_events

AGENT = "refactor-bot"
OLD_SHA = "a" * 40
NEW_SHA = "b" * 40


def _config(db_path: str, **alert_overrides) -> BurnLensConfig:
    return BurnLensConfig(
        db_path=db_path,
        alerts=AlertsConfig(terminal=False, slack_webhook=None, **alert_overrides),
    )


async def _insert(
    db_path: str,
    *,
    when: datetime,
    cost: float,
    trace_id: str,
    agent_id: str = AGENT,
    commit_sha: str = OLD_SHA,
    status_code: int = 200,
) -> None:
    await insert_request(
        db_path,
        RequestRecord(
            provider="openai",
            model="gpt-4o",
            request_path="/v1/chat/completions",
            cost_usd=cost,
            timestamp=when,
            status_code=status_code,
            trace_id=trace_id,
            commit_sha=commit_sha,
            tags={"agent_id": agent_id, "commit_sha": commit_sha},
        ),
    )


async def _seed_baseline(db_path: str, now: datetime, hourly_cost: float = 0.05) -> None:
    """One request per hour across the whole 7-day baseline.

    Every hourly bucket must be non-empty, otherwise the median lands on zero
    and the detector reports "no prior baseline" instead of a multiplier.
    """
    for hours_ago in range(2, 169):
        await _insert(
            db_path,
            when=now - timedelta(hours=hours_ago),
            cost=hourly_cost,
            trace_id=f"baseline-{hours_ago}",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_max_requests_in_span():
    base = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    times = [base + timedelta(minutes=m) for m in (0, 1, 2, 30, 31, 32, 33)]
    assert max_requests_in_span(times, timedelta(minutes=10)) == 4
    assert max_requests_in_span(times, timedelta(minutes=60)) == 7
    assert max_requests_in_span([base], timedelta(minutes=10)) == 1


def test_parse_timestamp_assumes_utc_for_naive_rows():
    assert parse_timestamp("2026-08-10T12:00:00").tzinfo is not None
    assert parse_timestamp("2026-08-10T12:00:00Z") == parse_timestamp(
        "2026-08-10T12:00:00+00:00"
    )


# ---------------------------------------------------------------------------
# Exit criterion
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_replayed_burst_fires_exactly_one_alert(initialized_db: str):
    """A spend burst after a deploy fires one alert naming multiplier and commit."""
    now = datetime.now(timezone.utc)
    await _seed_baseline(initialized_db, now)

    for i in range(20):
        await _insert(
            initialized_db,
            when=now - timedelta(minutes=30),
            cost=0.06,
            trace_id=f"burst-{i}",
            commit_sha=NEW_SHA,
        )

    detector = AnomalyDetector(_config(initialized_db), initialized_db)
    await detector.check_agent(AGENT)
    # Replay: the scheduler runs hourly and the burst is still inside the window.
    await detector.check_agent(AGENT)

    events = await get_recent_anomaly_events(initialized_db)
    assert len(events) == 1

    event = events[0]
    assert event.event_type == "cost_spike"
    assert event.scope == "agent"
    assert event.target == AGENT
    assert event.severity == "critical"  # 24x, well past 2x the 3x multiplier
    assert event.details["signal"] == "spend"
    assert event.details["commit_sha"] == NEW_SHA
    assert abs(event.details["multiplier"] - 24.0) < 0.01
    assert "24.0x its usual" in event.details["description"]
    assert f"deploy {NEW_SHA[:12]}" in event.details["description"]


@pytest.mark.asyncio
async def test_no_deploy_note_when_commit_unchanged(initialized_db: str):
    """Without a commit change in the window, the alert makes no deploy claim."""
    now = datetime.now(timezone.utc)
    await _seed_baseline(initialized_db, now)
    for i in range(20):
        await _insert(
            initialized_db,
            when=now - timedelta(minutes=30),
            cost=0.06,
            trace_id=f"burst-{i}",
        )

    detector = AnomalyDetector(_config(initialized_db), initialized_db)
    await detector.check_agent(AGENT)

    events = await get_recent_anomaly_events(initialized_db)
    assert len(events) == 1
    assert events[0].details["commit_sha"] is None
    assert "deploy" not in events[0].details["description"]


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_loop_outranks_spend(initialized_db: str):
    """Requests hammering one trace report as a loop, not as a spend spike."""
    now = datetime.now(timezone.utc)
    await _seed_baseline(initialized_db, now)

    # Same spend as the burst above, but all on one trace inside 10 minutes.
    for i in range(25):
        await _insert(
            initialized_db,
            when=now - timedelta(minutes=30) + timedelta(seconds=i * 10),
            cost=0.06,
            trace_id="stuck-trace",
        )

    detector = AnomalyDetector(_config(initialized_db), initialized_db)
    await detector.check_agent(AGENT)

    events = await get_recent_anomaly_events(initialized_db)
    assert len(events) == 1
    assert events[0].event_type == "runaway_loop"
    assert events[0].details["signal"] == "loop"
    assert events[0].details["current_value"] == 25
    assert events[0].details["trace_id"] == "stuck-trace"


@pytest.mark.asyncio
async def test_loop_needs_requests_bunched_within_the_window(initialized_db: str):
    """The same trace spread over the hour is not a loop."""
    now = datetime.now(timezone.utc)
    await _seed_baseline(initialized_db, now)

    # 25 requests on one trace, but 2 minutes apart -- at most 6 per 10 minutes.
    for i in range(25):
        await _insert(
            initialized_db,
            when=now - timedelta(minutes=55) + timedelta(minutes=2 * i),
            cost=0.06,
            trace_id="slow-trace",
        )

    detector = AnomalyDetector(_config(initialized_db), initialized_db)
    await detector.check_agent(AGENT)

    events = await get_recent_anomaly_events(initialized_db)
    assert len(events) == 1
    assert events[0].event_type == "cost_spike"


@pytest.mark.asyncio
async def test_retry_storm_alerts_without_a_spend_spike(initialized_db: str):
    """Retries that do not move total spend still surface."""
    now = datetime.now(timezone.utc)
    await _seed_baseline(initialized_db, now)

    # 5 failures each followed by a retry: half the window's calls are retries,
    # for $0.10 total -- under the min-spend floor, so spend cannot fire.
    for i in range(5):
        start = now - timedelta(minutes=30) + timedelta(seconds=i * 30)
        await _insert(
            initialized_db,
            when=start,
            cost=0.01,
            trace_id=f"retry-{i}",
            status_code=500,
        )
        await _insert(
            initialized_db,
            when=start + timedelta(seconds=5),
            cost=0.01,
            trace_id=f"retry-{i}",
        )

    detector = AnomalyDetector(_config(initialized_db), initialized_db)
    await detector.check_agent(AGENT)

    events = await get_recent_anomaly_events(initialized_db)
    assert len(events) == 1
    assert events[0].details["signal"] == "retry_rate"
    assert abs(events[0].details["retry_rate"] - 0.5) < 1e-9
    assert events[0].details["baseline_retry_rate"] == 0.0


@pytest.mark.asyncio
async def test_min_spend_floor_silences_tiny_agents(initialized_db: str):
    """A 6x jump on an agent burning cents is noise, not an alert."""
    now = datetime.now(timezone.utc)
    await _seed_baseline(initialized_db, now, hourly_cost=0.01)
    for i in range(6):
        await _insert(
            initialized_db,
            when=now - timedelta(minutes=30),
            cost=0.01,
            trace_id=f"tiny-{i}",
        )

    detector = AnomalyDetector(_config(initialized_db), initialized_db)
    await detector.check_agent(AGENT)

    assert await get_recent_anomaly_events(initialized_db) == []


@pytest.mark.asyncio
async def test_steady_agent_is_quiet(initialized_db: str):
    """An agent running at its baseline fires nothing."""
    now = datetime.now(timezone.utc)
    await _seed_baseline(initialized_db, now, hourly_cost=2.00)
    await _insert(
        initialized_db,
        when=now - timedelta(minutes=30),
        cost=2.00,
        trace_id="steady",
    )

    detector = AnomalyDetector(_config(initialized_db), initialized_db)
    await detector.check_agent(AGENT)

    assert await get_recent_anomaly_events(initialized_db) == []


@pytest.mark.asyncio
async def test_multiplier_is_configurable(initialized_db: str):
    """Raising the multiplier above the observed jump silences the alert."""
    now = datetime.now(timezone.utc)
    await _seed_baseline(initialized_db, now)
    for i in range(20):
        await _insert(
            initialized_db,
            when=now - timedelta(minutes=30),
            cost=0.06,
            trace_id=f"burst-{i}",
        )

    config = _config(initialized_db, agent_deviation_multiplier=50.0)
    await AnomalyDetector(config, initialized_db).check_agent(AGENT)

    assert await get_recent_anomaly_events(initialized_db) == []


# ---------------------------------------------------------------------------
# Scheduler entry point
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_active_agents_scans_only_recent_agents(initialized_db: str):
    """Agents idle for the last hour are skipped; active ones get checked."""
    now = datetime.now(timezone.utc)
    await _seed_baseline(initialized_db, now)
    for i in range(20):
        await _insert(
            initialized_db,
            when=now - timedelta(minutes=30),
            cost=0.06,
            trace_id=f"burst-{i}",
            commit_sha=NEW_SHA,
        )
    # Idle agent: last seen two days ago.
    await _insert(
        initialized_db,
        when=now - timedelta(days=2),
        cost=5.00,
        trace_id="idle",
        agent_id="idle-bot",
    )
    # Untagged traffic must not be scanned as an agent named None.
    await insert_request(
        initialized_db,
        RequestRecord(
            provider="openai",
            model="gpt-4o",
            request_path="/v1/chat/completions",
            cost_usd=9.99,
            timestamp=now - timedelta(minutes=5),
        ),
    )

    checked = await check_active_agents(initialized_db, _config(initialized_db))
    assert checked == 1

    events = await get_recent_anomaly_events(initialized_db)
    assert len(events) == 1
    assert events[0].target == AGENT


@pytest.mark.asyncio
async def test_check_active_agents_no_agents(initialized_db: str):
    assert await check_active_agents(initialized_db, _config(initialized_db)) == 0
