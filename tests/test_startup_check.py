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


# ---------------------------------------------------------------------------
# probe_webhook_secret
#
# The API key fails loudly (checkout 502s). A mismatched webhook secret fails
# SILENTLY: Paddle signs with the real secret, _verify_signature rejects it,
# /billing/webhook 401s, and the customer who just paid stays on free. These
# tests exist because nothing else in the system would notice.
# ---------------------------------------------------------------------------

def _settings_response(destinations):
    resp = MagicMock(status_code=200)
    resp.json = MagicMock(return_value={"data": destinations})
    return resp


def _client_returning(resp):
    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


ACTIVE = {"id": "ntfset_active", "description": "v2", "type": "url",
          "active": True, "endpoint_secret_key": "pdl_ntfset_REAL"}
DISABLED = {"id": "ntfset_old", "description": "v1", "type": "url",
            "active": False, "endpoint_secret_key": "pdl_ntfset_OLD"}


@pytest.mark.asyncio
async def test_probe_webhook_secret_matches_active_destination(caplog):
    from burnlens_cloud import config as config_mod
    from burnlens_cloud.startup_check import probe_webhook_secret

    alert = AsyncMock()
    with patch.object(config_mod.settings, "paddle_api_key", "pdl_live_good"), \
         patch.object(config_mod.settings, "paddle_webhook_secret", "pdl_ntfset_REAL"), \
         patch("burnlens_cloud.startup_check.httpx.AsyncClient",
               return_value=_client_returning(_settings_response([ACTIVE, DISABLED]))), \
         patch("burnlens_cloud.email.send_ops_alert", alert):
        with caplog.at_level("INFO"):
            ok = await probe_webhook_secret()

    assert ok is True
    alert.assert_not_awaited()
    # The secret must never reach a log line.
    assert "pdl_ntfset_REAL" not in caplog.text


@pytest.mark.asyncio
async def test_probe_webhook_secret_alerts_when_it_matches_a_disabled_destination():
    """The likeliest real failure: the destination was replaced, the env var
    kept the old one. Everything looks configured; every event 401s."""
    from burnlens_cloud import config as config_mod
    from burnlens_cloud.startup_check import probe_webhook_secret

    alert = AsyncMock()
    with patch.object(config_mod.settings, "paddle_api_key", "pdl_live_good"), \
         patch.object(config_mod.settings, "paddle_webhook_secret", "pdl_ntfset_OLD"), \
         patch("burnlens_cloud.startup_check.httpx.AsyncClient",
               return_value=_client_returning(_settings_response([ACTIVE, DISABLED]))), \
         patch("burnlens_cloud.email.send_ops_alert", alert):
        ok = await probe_webhook_secret()

    assert ok is False
    assert alert.await_count == 1
    body = alert.await_args.args[1]
    # Name the disabled destination — that is what saves the investigation.
    assert "ntfset_old" in body
    # And name the symptom, since there is no other one.
    assert "FREE PLAN" in body
    # Never leak either secret into an alert body.
    assert "pdl_ntfset_OLD" not in body and "pdl_ntfset_REAL" not in body


@pytest.mark.asyncio
async def test_probe_webhook_secret_alerts_when_it_matches_nothing():
    from burnlens_cloud import config as config_mod
    from burnlens_cloud.startup_check import probe_webhook_secret

    alert = AsyncMock()
    with patch.object(config_mod.settings, "paddle_api_key", "pdl_live_good"), \
         patch.object(config_mod.settings, "paddle_webhook_secret", "pdl_ntfset_UNRELATED"), \
         patch("burnlens_cloud.startup_check.httpx.AsyncClient",
               return_value=_client_returning(_settings_response([ACTIVE]))), \
         patch("burnlens_cloud.email.send_ops_alert", alert):
        ok = await probe_webhook_secret()

    assert ok is False
    assert alert.await_count == 1
    assert "no destination at all" in alert.await_args.args[1]


@pytest.mark.asyncio
async def test_probe_webhook_secret_transport_error_does_not_alert():
    """A Paddle outage is not proof of a mismatch — don't cry wolf."""
    from burnlens_cloud import config as config_mod
    from burnlens_cloud.startup_check import probe_webhook_secret

    alert = AsyncMock()
    with patch.object(config_mod.settings, "paddle_api_key", "pdl_live_good"), \
         patch.object(config_mod.settings, "paddle_webhook_secret", "pdl_ntfset_REAL"), \
         patch("burnlens_cloud.startup_check.httpx.AsyncClient", side_effect=OSError("boom")), \
         patch("burnlens_cloud.email.send_ops_alert", alert):
        ok = await probe_webhook_secret()

    assert ok is False
    alert.assert_not_awaited()


@pytest.mark.asyncio
async def test_webhook_probe_is_skipped_when_the_api_key_is_dead():
    """One dead credential must produce ONE alert naming the right credential,
    not a second one blaming the webhook secret it could not check."""
    from burnlens_cloud.startup_check import _run_probes

    with patch("burnlens_cloud.startup_check.probe_paddle",
               AsyncMock(return_value=False)) as paddle, \
         patch("burnlens_cloud.startup_check.probe_webhook_secret",
               AsyncMock()) as webhook:
        await _run_probes()

    paddle.assert_awaited_once()
    webhook.assert_not_awaited()
