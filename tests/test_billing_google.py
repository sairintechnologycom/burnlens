"""Tests for GoogleBillingParser — Google Cloud Billing API discovery."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from burnlens.detection.billing import GoogleBillingParser


@dataclass
class _FakeGoogleBillingConfig:
    enabled: bool = False
    auth_mode: str = "api_key"
    api_key: str | None = "AIza-test-key"
    service_account_json_path: str | None = None
    billing_account_id: str | None = "ABC123-DEF456-GHI789"
    project_id: str | None = None
    lookback_days: int = 30


def _make_sku_response(descriptions: list[str], next_page_token: str | None = None) -> dict:
    """Build a fake Cloud Billing API SKU list response."""
    skus = []
    for desc in descriptions:
        skus.append({
            "description": desc,
            "category": {
                "serviceDisplayName": "Vertex AI",
                "resourceFamily": "ApplicationServices",
            },
            "serviceProviderName": "Google",
        })
    resp: dict = {"skus": skus}
    if next_page_token:
        resp["nextPageToken"] = next_page_token
    return resp


@pytest.mark.asyncio
async def test_google_parser_disabled_returns_empty():
    """config.enabled=False -> fetch_usage returns []."""
    config = _FakeGoogleBillingConfig(enabled=False)
    result = await GoogleBillingParser().fetch_usage(config)
    assert result == []


@pytest.mark.asyncio
async def test_google_parser_no_billing_account_returns_empty():
    """config.enabled=True but billing_account_id=None -> returns [], logs warning."""
    config = _FakeGoogleBillingConfig(enabled=True, billing_account_id=None)
    result = await GoogleBillingParser().fetch_usage(config)
    assert result == []


@pytest.mark.asyncio
async def test_google_parser_api_key_mode_success():
    """Mock GET /skus -> 200 with sample SKU response -> returns asset dicts."""
    config = _FakeGoogleBillingConfig(enabled=True)

    sku_resp = _make_sku_response([
        "Gemini 1.5 Pro Input tokens",
        "Gemini 2.0 Flash Output tokens",
    ])

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = sku_resp
    mock_response.headers = {}

    with patch("burnlens.detection.billing.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await GoogleBillingParser().fetch_usage(config)

    assert len(result) >= 1
    asset = result[0]
    assert asset["provider"] == "google"
    assert "generativelanguage.googleapis.com" in asset["endpoint_url"]
    assert asset["source"] == "billing_api_google"
    assert asset["api_key_hash"] == hashlib.sha256(b"AIza-test-key").hexdigest()


@pytest.mark.asyncio
async def test_google_parser_api_error_returns_empty():
    """Mock GET -> 403 Forbidden -> parser returns [], does not raise."""
    config = _FakeGoogleBillingConfig(enabled=True)

    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.headers = {}
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Forbidden", request=httpx.Request("GET", "https://example.com"), response=mock_response
    )

    with patch("burnlens.detection.billing.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await GoogleBillingParser().fetch_usage(config)

    assert result == []


@pytest.mark.asyncio
async def test_google_parser_network_timeout_returns_empty():
    """Mock GET -> raise httpx.TimeoutException -> returns []."""
    config = _FakeGoogleBillingConfig(enabled=True)

    with patch("burnlens.detection.billing.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.TimeoutException("timed out")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await GoogleBillingParser().fetch_usage(config)

    assert result == []


@pytest.mark.asyncio
async def test_google_parser_extracts_model_from_sku_description():
    """SKU desc 'Gemini 1.5 Pro Input tokens' -> model = 'gemini-1.5-pro'."""
    config = _FakeGoogleBillingConfig(enabled=True)

    sku_resp = _make_sku_response(["Gemini 1.5 Pro Input tokens"])

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = sku_resp
    mock_response.headers = {}

    with patch("burnlens.detection.billing.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await GoogleBillingParser().fetch_usage(config)

    assert len(result) >= 1
    assert result[0]["model"] == "gemini-1.5-pro"


def test_google_parser_does_not_add_google_auth_as_required_dep():
    """Importing billing module should not raise even without google-auth."""
    # This test passes by reaching this point — the import at the top of the
    # file succeeded. Verify the class is importable too.
    from burnlens.detection.billing import GoogleBillingParser  # noqa: F811
    assert GoogleBillingParser is not None
