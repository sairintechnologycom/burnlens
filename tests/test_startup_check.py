"""Startup credential inventory + Paddle liveness probe.

Guards the failure shape that took checkout down for three weeks: a credential
that is PRESENT but dead. Presence checks alone would have reported healthy the
entire time, which is why probe_paddle exists.
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/burnlens_test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests")
os.environ.setdefault("ENVIRONMENT", "test")


def test_inventory_reports_missing_required(caplog):
    from burnlens_cloud import config as config_mod
    from burnlens_cloud.startup_check import log_credential_inventory

    with patch.object(config_mod.settings, "paddle_api_key", ""), \
         patch.object(config_mod.settings, "smtp_password", ""):
        with caplog.at_level("WARNING"):
            log_credential_inventory()

    text = caplog.text
    assert "MISSING (required) PADDLE_API_KEY" in text
    assert "MISSING (required) SMTP_PASSWORD" in text
    # The log must name the user-visible symptom, not just the variable —
    # that is what makes it actionable at 3am.
    assert "502" in text and "lockout" in text


def test_inventory_quiet_when_everything_present(caplog):
    from burnlens_cloud import config as config_mod
    from burnlens_cloud.startup_check import CREDENTIALS, log_credential_inventory

    with patch("burnlens_cloud.startup_check.CREDENTIALS",
               [c._replace(configured=lambda: True) for c in CREDENTIALS]):
        with caplog.at_level("WARNING"):
            log_credential_inventory()

    assert "MISSING" not in caplog.text
    assert "missing (optional)" not in caplog.text


@pytest.mark.asyncio
async def test_probe_paddle_alerts_on_dead_key():
    """403 on a plain read = expired/revoked key = checkout is down."""
    from burnlens_cloud import config as config_mod
    from burnlens_cloud.startup_check import probe_paddle

    resp = MagicMock(status_code=403)
    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    alert = AsyncMock()
    with patch.object(config_mod.settings, "paddle_api_key", "pdl_live_dead"), \
         patch.object(config_mod.settings, "paddle_environment", "production"), \
         patch("burnlens_cloud.startup_check.httpx.AsyncClient", return_value=client), \
         patch("burnlens_cloud.email.send_ops_alert", alert):
        ok = await probe_paddle()

    assert ok is False
    assert alert.await_count == 1
    body = alert.await_args.args[1]
    assert "403" in body and "checkout" in body.lower()


@pytest.mark.asyncio
async def test_probe_paddle_ok_on_200():
    from burnlens_cloud import config as config_mod
    from burnlens_cloud.startup_check import probe_paddle

    resp = MagicMock(status_code=200)
    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    alert = AsyncMock()
    with patch.object(config_mod.settings, "paddle_api_key", "pdl_live_good"), \
         patch("burnlens_cloud.startup_check.httpx.AsyncClient", return_value=client), \
         patch("burnlens_cloud.email.send_ops_alert", alert):
        ok = await probe_paddle()

    assert ok is True
    alert.assert_not_awaited()


@pytest.mark.asyncio
async def test_probe_paddle_transport_error_does_not_alert():
    """A Paddle outage is not proof our key is bad — don't cry wolf, and don't
    let it break boot."""
    from burnlens_cloud import config as config_mod
    from burnlens_cloud.startup_check import probe_paddle

    alert = AsyncMock()
    with patch.object(config_mod.settings, "paddle_api_key", "pdl_live_good"), \
         patch("burnlens_cloud.startup_check.httpx.AsyncClient", side_effect=OSError("boom")), \
         patch("burnlens_cloud.email.send_ops_alert", alert):
        ok = await probe_paddle()

    assert ok is False
    alert.assert_not_awaited()
