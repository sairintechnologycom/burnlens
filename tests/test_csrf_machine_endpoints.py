"""Regression: the CSRF middleware must not block machine-to-machine endpoints.

CsrfMiddleware (burnlens_cloud/main.py) 403s any state-changing request that
lacks X-Requested-With. Browsers can't set that header cross-origin without a
preflight, which is the point — but machine callers don't send it either, and
three endpoints are called exclusively by non-browser clients that carry their
own credential:

  - POST /v1/ingest          (OSS proxy sync, X-API-Key)
  - POST /cron/evaluate-alerts (GitHub Actions hourly cron, Bearer CRON_SECRET)
  - POST /billing/webhook    (Paddle, signature-verified)

Found 2026-07-13: the un-exempted middleware silently broke cloud ingest for
every OSS install and made the hourly alert cron fail with HTTP 403 for days.

Like test_cors_preflight.py, this exercises the actually-deployed
burnlens_cloud.main app directly, skipping the conftest fixtures.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def cloud_client():
    os.environ.setdefault("ALLOWED_ORIGINS", "https://burnlens.app")
    from burnlens_cloud.main import get_app
    return TestClient(get_app(), raise_server_exceptions=False)


def _csrf_blocked(resp) -> bool:
    return resp.status_code == 403 and "X-Requested-With" in resp.text


def test_ingest_not_csrf_blocked(cloud_client):
    """POST /v1/ingest without X-Requested-With must reach the endpoint.

    It may fail later (401 missing key, 500 without a DB in tests) — but it
    must not be the CSRF middleware's 403.
    """
    resp = cloud_client.post("/v1/ingest", json={"records": []})
    assert not _csrf_blocked(resp), resp.text


def test_cron_evaluate_alerts_not_csrf_blocked(cloud_client):
    """The hourly GH Actions cron sends only Authorization: Bearer."""
    resp = cloud_client.post(
        "/cron/evaluate-alerts",
        headers={"Authorization": "Bearer not-the-secret"},
    )
    assert not _csrf_blocked(resp), resp.text
    # Bearer auth must still be enforced — exemption skips CSRF, not auth.
    assert resp.status_code == 401


def test_billing_webhook_not_csrf_blocked(cloud_client):
    """Paddle webhooks are signature-verified, never cookie-authenticated."""
    resp = cloud_client.post("/billing/webhook", content=b"{}")
    assert not _csrf_blocked(resp), resp.text


def test_browser_endpoints_still_csrf_protected(cloud_client):
    """The exemption must not weaken protection for cookie-auth browser routes."""
    resp = cloud_client.post("/billing/checkout", json={})
    assert _csrf_blocked(resp), (
        f"expected CSRF 403 for /billing/checkout without X-Requested-With, "
        f"got {resp.status_code}: {resp.text[:200]}"
    )
