"""Regression: 500 responses must emit CORS headers when the request comes
from an allowed origin. Otherwise browsers misreport real backend errors as
CORS errors, masking the actual bug. See QA report 2026-05-01 evening.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def cloud_app_with_failing_route():
    os.environ.setdefault("ALLOWED_ORIGINS", "https://burnlens.app")
    from burnlens_cloud.main import get_app
    app = get_app()

    @app.get("/__test_500__")
    async def _boom():
        raise RuntimeError("intentional test error")

    return app


def test_500_response_has_cors_headers_for_allowed_origin(cloud_app_with_failing_route):
    client = TestClient(cloud_app_with_failing_route, raise_server_exceptions=False)
    resp = client.get("/__test_500__", headers={"Origin": "https://burnlens.app"})
    assert resp.status_code == 500
    assert resp.headers.get("access-control-allow-origin") == "https://burnlens.app"
    assert resp.headers.get("access-control-allow-credentials") == "true"
    assert resp.headers.get("vary") == "Origin"
    assert resp.json() == {"detail": "Internal Server Error"}


def test_500_response_does_not_leak_cors_to_disallowed_origin(cloud_app_with_failing_route):
    client = TestClient(cloud_app_with_failing_route, raise_server_exceptions=False)
    resp = client.get("/__test_500__", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 500
    assert resp.headers.get("access-control-allow-origin") is None
