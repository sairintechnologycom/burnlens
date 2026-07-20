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


def test_cors_allows_vercel_preview_hosts(cloud_app):
    """Vercel preview deploys (burnlens-app-git-<branch>-<team>.vercel.app)
    must pass CORS so preview-deploy E2E tests aren't blocked. See
    reference_vercel_preview_env_gap.md."""
    client = TestClient(cloud_app)
    preview_origin = (
        "https://burnlens-app-git-feat-foo-sairintechnologycom.vercel.app"
    )
    resp = client.options(
        "/billing/summary",
        headers={
            "Origin": preview_origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == preview_origin


def test_cors_rejects_unrelated_vercel_hosts(cloud_app):
    """The preview regex must be anchored to the burnlens-app project — an
    attacker-controlled vercel.app subdomain must not be allowed."""
    client = TestClient(cloud_app)
    resp = client.options(
        "/billing/summary",
        headers={
            "Origin": "https://malicious-project.vercel.app",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    # Starlette returns 400 for disallowed preflight origins
    assert resp.headers.get("access-control-allow-origin") != "https://malicious-project.vercel.app"


def test_csrf_403_carries_cors_headers(cloud_app):
    """Regression: CORS must be the OUTERMOST middleware.

    Before 2026-07-20, CsrfMiddleware was outside CORSMiddleware, so its 403
    had no Access-Control-Allow-Origin — browsers hid the status behind an
    unreadable "Failed to fetch". That masked a week-long /auth outage (the
    setup page's raw fetch() calls never sent X-Requested-With).
    """
    client = TestClient(cloud_app)
    resp = client.post(
        "/auth/login",
        json={"email": "x@example.com", "password": "irrelevant"},
        headers={"Origin": "https://burnlens.app"},  # no X-Requested-With
    )
    assert resp.status_code == 403  # CSRF rejection, not auth
    assert resp.json()["detail"].startswith("CSRF")
    assert resp.headers.get("access-control-allow-origin") == "https://burnlens.app"


def test_login_with_xrw_header_passes_csrf(cloud_app):
    """The header the frontend now sends must get past the CSRF gate — the
    request should reach the auth handler (401/500-family), never CSRF 403."""
    client = TestClient(cloud_app)
    resp = client.post(
        "/auth/login",
        json={"email": "x@example.com", "password": "irrelevant"},
        headers={
            "Origin": "https://burnlens.app",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    assert resp.status_code != 403
