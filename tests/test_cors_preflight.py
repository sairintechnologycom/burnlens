"""Regression: CORS preflight max_age must stay short to keep the deploy
window small for active sessions. See project_billing_summary_cors_regression.md.

This test intentionally skips the conftest fixtures (which target api.main).
It exercises the actually-deployed burnlens_cloud.main app directly.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def cloud_app():
    os.environ.setdefault("ALLOWED_ORIGINS", "https://burnlens.app")
    from burnlens_cloud.main import get_app
    return get_app()


def test_cors_preflight_max_age_is_short(cloud_app):
    """Browser preflight cache must be ≤120s so a CORS-relevant deploy can't
    leave active sessions with stale preflights for ~10 min (Starlette's
    default 600s)."""
    client = TestClient(cloud_app)
    resp = client.options(
        "/billing/summary",
        headers={
            "Origin": "https://burnlens.app",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert resp.status_code == 200
    max_age = resp.headers.get("access-control-max-age")
    assert max_age is not None, "preflight must declare max-age"
    assert int(max_age) <= 120, f"preflight cache too long: {max_age}s"


def test_cors_preflight_origin_credentials_vary(cloud_app):
    """Sanity: preflight still reflects the origin, allows credentials, and
    sets Vary: Origin so downstream CDNs key responses by Origin."""
    client = TestClient(cloud_app)
    resp = client.options(
        "/billing/summary",
        headers={
            "Origin": "https://burnlens.app",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert resp.headers.get("access-control-allow-origin") == "https://burnlens.app"
    assert resp.headers.get("access-control-allow-credentials") == "true"
    assert "Origin" in (resp.headers.get("vary") or "")
