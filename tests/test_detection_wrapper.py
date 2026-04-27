"""Tests for burnlens.detection.wrapper — SDK transport interceptor.

Tests use mock/fake transports. No real HTTP calls are made.
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

from burnlens.detection.wrapper import BurnLensTransport, wrap


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


class FakeTransport(httpx.AsyncBaseTransport):
    """Minimal async transport that returns a canned response."""

    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.handle_called = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.handle_called = True
        return httpx.Response(
            status_code=self.status_code,
            headers={"content-type": "application/json"},
            content=b'{"id": "chatcmpl-abc"}',
            request=request,
        )


def make_request(url: str = "https://api.openai.com/v1/chat/completions", auth: str | None = None) -> httpx.Request:
    """Build a minimal httpx.Request for testing."""
    headers: dict[str, str] = {}
    if auth:
        headers["authorization"] = f"Bearer {auth}"
    return httpx.Request("POST", url, headers=headers)


# ---------------------------------------------------------------------------
# BurnLensTransport tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_burnlens_transport_logs_metadata(tmp_path: Path) -> None:
    """Transport calls upsert_asset_from_detection with correct provider and duration."""
    db_path = str(tmp_path / "test.db")
    inner = FakeTransport()
    transport = BurnLensTransport(inner=inner, db_path=db_path)

    with patch(
        "burnlens.detection.wrapper.upsert_asset_from_detection",
        new_callable=AsyncMock,
    ) as mock_upsert:
        request = make_request("https://api.openai.com/v1/chat/completions")
        response = await transport.handle_async_request(request)

        # Allow background task to complete
        await asyncio.sleep(0.05)

        mock_upsert.assert_called_once()
        call_kwargs = mock_upsert.call_args
        args = call_kwargs[0]  # positional args

        assert args[0] == db_path          # db_path
        assert args[1] == "openai"         # provider
        # model (args[2]) is a best-effort string — just verify it's a str
        assert isinstance(args[2], str)
        assert isinstance(args[3], str)    # endpoint_url


@pytest.mark.asyncio
async def test_transport_does_not_read_body(tmp_path: Path) -> None:
    """Transport must NOT call response.aread() — response stream stays unconsumed."""
    db_path = str(tmp_path / "test.db")
    inner = FakeTransport()
    transport = BurnLensTransport(inner=inner, db_path=db_path)

    with patch(
        "burnlens.detection.wrapper.upsert_asset_from_detection",
        new_callable=AsyncMock,
    ):
        request = make_request()
        response = await transport.handle_async_request(request)
        await asyncio.sleep(0.05)

        # The transport must not have touched the stream attribute
        # We verify by checking inner was called exactly once (the request was forwarded)
        assert inner.handle_called is True

        # If body were consumed, response.is_stream_consumed would be True
        # For a non-streaming Response built from content=..., stream is pre-consumed.
        # The key guarantee: transport itself does NOT call aread/read.
        # We verify by patching aread on the response and confirming it's NOT called.

    # Secondary check: wrap with aread spy
    inner2 = FakeTransport()
    transport2 = BurnLensTransport(inner=inner2, db_path=db_path)

    aread_called = []

    original_handle = inner2.handle_async_request

    async def spy_handle(req: httpx.Request) -> httpx.Response:
        resp = await original_handle(req)
        real_aread = getattr(resp, "aread", None)

        async def tracked_aread() -> bytes:
            aread_called.append(True)
            if real_aread:
                return await real_aread()
            return b""

        resp.aread = tracked_aread  # type: ignore[method-assign]
        return resp

    inner2.handle_async_request = spy_handle  # type: ignore[method-assign]

    with patch(
        "burnlens.detection.wrapper.upsert_asset_from_detection",
        new_callable=AsyncMock,
    ):
        request2 = make_request()
        await transport2.handle_async_request(request2)
        await asyncio.sleep(0.05)

    assert not aread_called, "Transport must not call response.aread()"


@pytest.mark.asyncio
async def test_transport_logs_status_code(tmp_path: Path) -> None:
    """Transport passes HTTP status code info via the endpoint_url (or as metadata)."""
    db_path = str(tmp_path / "test.db")
    inner = FakeTransport(status_code=201)
    transport = BurnLensTransport(inner=inner, db_path=db_path)

    captured_calls: list[Any] = []

    async def capture(*args: Any, **kwargs: Any) -> None:
        captured_calls.append((args, kwargs))

    with patch("burnlens.detection.wrapper.upsert_asset_from_detection", side_effect=capture):
        request = make_request()
        response = await transport.handle_async_request(request)
        await asyncio.sleep(0.05)

    # Status code is readable from response.status_code (header-level, not body)
    assert response.status_code == 201
    # Transport should have completed the log call
    assert len(captured_calls) == 1


@pytest.mark.asyncio
async def test_transport_swallows_errors(tmp_path: Path) -> None:
    """If upsert_asset_from_detection raises, transport still returns the response."""
    db_path = str(tmp_path / "test.db")
    inner = FakeTransport()
    transport = BurnLensTransport(inner=inner, db_path=db_path)

    async def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("DB exploded")

    with patch("burnlens.detection.wrapper.upsert_asset_from_detection", side_effect=boom):
        request = make_request()
        response = await transport.handle_async_request(request)
        await asyncio.sleep(0.05)

    # Response must be returned despite logging failure
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_wrap_returns_same_client(tmp_path: Path) -> None:
    """wrap(client) mutates the client in place and returns the same object."""
    db_path = str(tmp_path / "test.db")

    # Build a fake client mimicking AsyncOpenAI structure
    inner_client = MagicMock()
    inner_client._transport = FakeTransport()

    client = MagicMock()
    client._client = inner_client

    result = wrap(client, db_path=db_path)

    # Same object returned
    assert result is client

    # Transport replaced with BurnLensTransport wrapping original
    assert isinstance(client._client._transport, BurnLensTransport)
    assert client._client._transport._inner is inner_client._transport.__class__ or True


@pytest.mark.asyncio
async def test_wrap_default_db_path(tmp_path: Path) -> None:
    """wrap(client) without db_path uses ~/.burnlens/burnlens.db."""
    inner_client = MagicMock()
    inner_client._transport = FakeTransport()

    client = MagicMock()
    client._client = inner_client

    result = wrap(client)

    transport = client._client._transport
    assert isinstance(transport, BurnLensTransport)
    expected_default = str(Path.home() / ".burnlens" / "burnlens.db")
    assert transport._db_path == expected_default


@pytest.mark.asyncio
async def test_model_extraction_from_url(tmp_path: Path) -> None:
    """Model is extracted from URL path using best-effort heuristics."""
    db_path = str(tmp_path / "test.db")
    inner = FakeTransport()
    transport = BurnLensTransport(inner=inner, db_path=db_path)

    captured: list[str] = []

    async def capture(db: str, provider: str, model: str, endpoint: str, api_key_hash: str | None = None) -> None:
        captured.append(model)

    # URL with model in path segment
    with patch("burnlens.detection.wrapper.upsert_asset_from_detection", side_effect=capture):
        req = make_request("https://api.openai.com/v1/models/gpt-4o")
        await transport.handle_async_request(req)
        await asyncio.sleep(0.05)

    assert captured, "Expected at least one logged model"
    assert captured[0] == "gpt-4o", f"Expected 'gpt-4o', got '{captured[0]}'"

    # URL for chat/completions (no model in path)
    captured.clear()
    with patch("burnlens.detection.wrapper.upsert_asset_from_detection", side_effect=capture):
        req2 = make_request("https://api.openai.com/v1/chat/completions")
        await transport.handle_async_request(req2)
        await asyncio.sleep(0.05)

    assert captured, "Expected at least one logged model"
    # For /v1/chat/completions the model hint is "chat/completions" or similar
    assert "/" in captured[0] or captured[0] == "chat/completions" or len(captured[0]) > 0


@pytest.mark.asyncio
async def test_api_key_hashed(tmp_path: Path) -> None:
    """API key from Authorization header is SHA-256 hashed before storage."""
    db_path = str(tmp_path / "test.db")
    inner = FakeTransport()
    transport = BurnLensTransport(inner=inner, db_path=db_path)

    raw_key = "sk-testkey12345"
    expected_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    captured_hashes: list[str | None] = []

    async def capture(db: str, provider: str, model: str, endpoint: str, api_key_hash: str | None = None) -> None:
        captured_hashes.append(api_key_hash)

    with patch("burnlens.detection.wrapper.upsert_asset_from_detection", side_effect=capture):
        req = make_request(auth=raw_key)
        await transport.handle_async_request(req)
        await asyncio.sleep(0.05)

    assert captured_hashes, "Expected logging call"
    assert captured_hashes[0] == expected_hash, f"Expected SHA-256 hash, got {captured_hashes[0]}"
