"""Phase 3: workspace_activity ip_address / user_agent 90-day purge.

Locks three invariants:

1. The purge SQL targets ONLY the two PII columns and the age/age-NULL
   filter — a typo that widened the scope could redact the whole audit log.
2. `retention_days <= 0` is treated as a misconfiguration and is a no-op,
   not a full-table nuke.
3. `purge_old_activity_pii` returns the asyncpg command-tag rowcount so the
   operator can see progress in logs.
"""
from __future__ import annotations

import os
import pathlib
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/burnlens_test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests-32ch")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault(
    "PII_MASTER_KEY",
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
)
_FAKE_ENV = pathlib.Path(__file__).parent / "_activity_pii_purge_test.env"
if not _FAKE_ENV.exists():
    _FAKE_ENV.write_text("")
import pydantic_settings.sources as _ps_sources  # noqa: E402
_ps_sources.dotenv_values = lambda *a, **k: {}


@pytest.mark.asyncio
async def test_purge_sql_narrowly_targets_pii_columns_and_age_filter():
    """The SQL must UPDATE only ip_address + user_agent, gated by age.

    Regression guard against ever rewriting this to a DELETE or a wider UPDATE.
    """
    captured = []

    async def fake_execute_insert(sql, *args):
        captured.append((sql, args))
        return "UPDATE 0"

    from burnlens_cloud.compliance import purge as purge_mod

    with patch.object(purge_mod, "execute_insert", side_effect=fake_execute_insert):
        await purge_mod.purge_old_activity_pii(retention_days=90)

    assert len(captured) == 1
    sql, args = captured[0]
    assert "UPDATE workspace_activity" in sql
    assert "SET ip_address = NULL, user_agent = NULL" in sql
    assert "DELETE" not in sql.upper()
    assert "created_at <" in sql
    # The idempotence guard keeps already-purged rows out of subsequent ticks.
    assert "ip_address IS NOT NULL OR user_agent IS NOT NULL" in sql
    assert args == (90,)


@pytest.mark.asyncio
async def test_purge_returns_rowcount_from_command_tag():
    async def fake_execute_insert(sql, *args):
        return "UPDATE 137"

    from burnlens_cloud.compliance import purge as purge_mod

    with patch.object(purge_mod, "execute_insert", side_effect=fake_execute_insert):
        count = await purge_mod.purge_old_activity_pii(retention_days=90)
    assert count == 137


@pytest.mark.asyncio
async def test_purge_refuses_nonpositive_retention():
    """Zero / negative retention must short-circuit — never redact everything."""
    called = []

    async def fake_execute_insert(sql, *args):
        called.append(True)
        return "UPDATE 999999"

    from burnlens_cloud.compliance import purge as purge_mod

    with patch.object(purge_mod, "execute_insert", side_effect=fake_execute_insert):
        count_zero = await purge_mod.purge_old_activity_pii(retention_days=0)
        count_neg = await purge_mod.purge_old_activity_pii(retention_days=-1)

    assert count_zero == 0
    assert count_neg == 0
    assert called == []  # SQL never issued


@pytest.mark.asyncio
async def test_purge_defaults_to_settings_retention_window():
    """When retention_days is omitted, fall back to settings.activity_pii_retention_days."""
    captured = []

    async def fake_execute_insert(sql, *args):
        captured.append(args)
        return "UPDATE 0"

    from burnlens_cloud.compliance import purge as purge_mod
    from burnlens_cloud.config import settings

    # Force a distinctive value to prove the default is read from settings,
    # not hardcoded.
    original = settings.activity_pii_retention_days
    try:
        settings.activity_pii_retention_days = 45
        with patch.object(purge_mod, "execute_insert", side_effect=fake_execute_insert):
            await purge_mod.purge_old_activity_pii()  # no arg → use settings
    finally:
        settings.activity_pii_retention_days = original

    assert captured == [(45,)]
