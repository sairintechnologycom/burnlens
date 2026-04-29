"""CODE-2 STEP 7: per-API-key daily-cap 50% / 80% / 100% alerts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from burnlens.alerts.engine import (
    AlertEngine,
    KEY_BUDGET_THRESHOLDS,
    KeyBudgetAlert,
    check_key_budgets,
)
from burnlens.alerts.slack import _build_key_budget_payload
from burnlens.config import (
    AlertsConfig,
    ApiKeyBudgetsConfig,
    BurnLensConfig,
    KeyBudgetEntry,
)
from burnlens.keys import register_key
from burnlens.storage.database import insert_request
from burnlens.storage.models import RequestRecord


def _make_config(
    keys: dict[str, KeyBudgetEntry] | None = None,
    default: KeyBudgetEntry | None = None,
    tz: str = "UTC",
    slack_webhook: str | None = None,
    terminal: bool = False,
) -> BurnLensConfig:
    return BurnLensConfig(
        alerts=AlertsConfig(
            slack_webhook=slack_webhook,
            terminal=terminal,
            api_key_budgets=ApiKeyBudgetsConfig(
                keys=keys or {},
                default=default,
                reset_timezone=tz,
            ),
        ),
    )


async def _seed_spend(
    db_path: str,
    label: str,
    cost: float,
    timestamp: datetime | None = None,
) -> None:
    await insert_request(
        db_path,
        RequestRecord(
            provider="openai", model="gpt-4o", request_path="/v1/chat",
            timestamp=timestamp or datetime.now(timezone.utc),
            input_tokens=0, output_tokens=0, reasoning_tokens=0,
            cache_read_tokens=0, cache_write_tokens=0,
            cost_usd=cost, duration_ms=0, status_code=200,
            tags={"key_label": label},
        ),
    )


# ---------------------------------------------------------------------------
# check_key_budgets — pure logic
# ---------------------------------------------------------------------------


def test_thresholds_constant_is_ascending() -> None:
    """Iteration order matters for picking the highest crossed threshold."""
    assert KEY_BUDGET_THRESHOLDS == (50, 80, 100)


@pytest.mark.asyncio
async def test_no_alerts_when_no_caps_configured(initialized_db: str) -> None:
    config = _make_config()  # no keys, no default
    await register_key(initialized_db, "k", "openai", "sk-test")
    await _seed_spend(initialized_db, "k", cost=99.0)

    alerts = await check_key_budgets(config, initialized_db)
    assert alerts == []


@pytest.mark.asyncio
async def test_no_alerts_below_50_percent(initialized_db: str) -> None:
    config = _make_config(keys={"low": KeyBudgetEntry(daily_usd=10.0)})
    await register_key(initialized_db, "low", "openai", "sk-low")
    await _seed_spend(initialized_db, "low", cost=4.99)  # 49.9%

    alerts = await check_key_budgets(config, initialized_db)
    assert alerts == []


@pytest.mark.asyncio
async def test_warning_fires_at_50_percent(initialized_db: str) -> None:
    config = _make_config(keys={"k50": KeyBudgetEntry(daily_usd=10.0)})
    await register_key(initialized_db, "k50", "anthropic", "sk-ant-50")
    await _seed_spend(initialized_db, "k50", cost=5.00)

    alerts = await check_key_budgets(config, initialized_db)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.severity == "WARNING"
    assert a.threshold == 50
    assert a.provider == "anthropic"
    assert a.spent_today == pytest.approx(5.00)
    assert a.daily_budget == pytest.approx(10.00)
    assert a.pct == pytest.approx(50.0)


@pytest.mark.asyncio
async def test_warning_fires_at_80_percent(initialized_db: str) -> None:
    config = _make_config(keys={"k80": KeyBudgetEntry(daily_usd=10.0)})
    await register_key(initialized_db, "k80", "anthropic", "sk-ant-80")
    await _seed_spend(initialized_db, "k80", cost=8.00)

    alerts = await check_key_budgets(config, initialized_db)
    assert len(alerts) == 1
    assert alerts[0].severity == "WARNING"
    assert alerts[0].threshold == 80


@pytest.mark.asyncio
async def test_critical_fires_at_100_percent(initialized_db: str) -> None:
    config = _make_config(keys={"k100": KeyBudgetEntry(daily_usd=10.0)})
    await register_key(initialized_db, "k100", "openai", "sk-100")
    await _seed_spend(initialized_db, "k100", cost=10.00)

    alerts = await check_key_budgets(config, initialized_db)
    assert len(alerts) == 1
    assert alerts[0].severity == "CRITICAL"
    assert alerts[0].threshold == 100


@pytest.mark.asyncio
async def test_default_cap_applies_when_label_lacks_override(
    initialized_db: str,
) -> None:
    config = _make_config(default=KeyBudgetEntry(daily_usd=2.00))
    await register_key(initialized_db, "fallback", "openai", "sk-fb")
    await _seed_spend(initialized_db, "fallback", cost=2.00)

    alerts = await check_key_budgets(config, initialized_db)
    assert len(alerts) == 1
    assert alerts[0].threshold == 100


@pytest.mark.asyncio
async def test_unregistered_label_shows_unknown_provider(
    initialized_db: str,
) -> None:
    """Spend logged with a label that was never registered still alerts.

    Provider falls back to 'unknown' since api_keys has no row for it.
    """
    config = _make_config(default=KeyBudgetEntry(daily_usd=1.00))
    await _seed_spend(initialized_db, "stray", cost=1.00)

    alerts = await check_key_budgets(config, initialized_db)
    assert len(alerts) == 1
    assert alerts[0].provider == "unknown"


# ---------------------------------------------------------------------------
# AlertEngine dedup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_same_threshold_same_day(initialized_db: str) -> None:
    """Calling check twice on the same threshold must only dispatch once."""
    config = _make_config(keys={"d": KeyBudgetEntry(daily_usd=10.0)})
    await register_key(initialized_db, "d", "openai", "sk-d")
    await _seed_spend(initialized_db, "d", cost=5.00)  # 50%

    engine = AlertEngine(config, initialized_db)
    await engine.check_and_dispatch_key_budgets()
    fired_after_first = {k for k in engine._fired if isinstance(k, tuple) and k[:2] == ("key_budget", "d")}
    assert len(fired_after_first) == 1

    # Second call — must not dispatch a second alert.
    await engine.check_and_dispatch_key_budgets()
    fired_after_second = {k for k in engine._fired if isinstance(k, tuple) and k[:2] == ("key_budget", "d")}
    assert fired_after_first == fired_after_second


@pytest.mark.asyncio
async def test_higher_threshold_fires_after_lower(initialized_db: str) -> None:
    """A label that crosses 50% and later 80% should produce a fresh alert."""
    config = _make_config(keys={"esc": KeyBudgetEntry(daily_usd=10.0)})
    await register_key(initialized_db, "esc", "openai", "sk-esc")
    await _seed_spend(initialized_db, "esc", cost=5.00)  # 50%

    engine = AlertEngine(config, initialized_db)
    await engine.check_and_dispatch_key_budgets()
    after_50 = {k for k in engine._fired if isinstance(k, tuple) and k[:2] == ("key_budget", "esc")}
    assert any(k[2] == 50 for k in after_50)

    # Now bump spend to 80% and re-check.
    await _seed_spend(initialized_db, "esc", cost=3.00)  # cumulative 8.00 → 80%
    await engine.check_and_dispatch_key_budgets()
    after_80 = {k for k in engine._fired if isinstance(k, tuple) and k[:2] == ("key_budget", "esc")}
    assert any(k[2] == 80 for k in after_80)
    # Both 50 and 80 dedup keys present — they don't overwrite each other.
    assert {k[2] for k in after_80} >= {50, 80}


@pytest.mark.asyncio
async def test_engine_swallows_errors(initialized_db: str) -> None:
    """check_and_dispatch_key_budgets must never raise (asyncio.create_task safe)."""
    config = _make_config(keys={"ok": KeyBudgetEntry(daily_usd=1.0)})
    engine = AlertEngine(config, "/nonexistent/path/nope.db")
    # Should log an error but NOT raise.
    await engine.check_and_dispatch_key_budgets()


# ---------------------------------------------------------------------------
# Slack payload
# ---------------------------------------------------------------------------


def test_slack_payload_matches_spec_example() -> None:
    alert = KeyBudgetAlert(
        key_label="cursor-main",
        provider="anthropic",
        spent_today=40.12,
        daily_budget=50.00,
        pct=80.24,
        threshold=80,
        severity="WARNING",
        resets_at=datetime(2026, 4, 29, 18, 30, tzinfo=timezone.utc),
        resets_tz="Asia/Kolkata",
    )
    payload = _build_key_budget_payload(alert)
    text = payload["blocks"][0]["text"]["text"]
    assert ":warning:" in text
    assert "BurnLens daily cap 80%" in text
    assert "`cursor-main`" in text
    assert "(anthropic)" in text
    assert "$40.12" in text
    assert "$50.00" in text
    assert "Resets 00:00 Asia/Kolkata." in text


def test_slack_payload_uses_red_circle_at_100_percent() -> None:
    alert = KeyBudgetAlert(
        key_label="blown",
        provider="openai",
        spent_today=10.0,
        daily_budget=10.0,
        pct=100.0,
        threshold=100,
        severity="CRITICAL",
        resets_at=datetime(2026, 4, 29, tzinfo=timezone.utc),
        resets_tz="UTC",
    )
    text = _build_key_budget_payload(alert)["blocks"][0]["text"]["text"]
    assert ":red_circle:" in text
    assert "BurnLens daily cap 100%" in text


def test_slack_payload_uses_blue_circle_at_50_percent() -> None:
    alert = KeyBudgetAlert(
        key_label="warn",
        provider="openai",
        spent_today=5.0,
        daily_budget=10.0,
        pct=50.0,
        threshold=50,
        severity="WARNING",
        resets_at=datetime(2026, 4, 29, tzinfo=timezone.utc),
        resets_tz="UTC",
    )
    text = _build_key_budget_payload(alert)["blocks"][0]["text"]["text"]
    assert ":large_blue_circle:" in text
    assert "BurnLens daily cap 50%" in text
