"""Azure OpenAI provider — registration, env-based endpoint resolution,
deployment-name model extraction, and inherited OpenAI wire-format handling."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from burnlens.providers import get, get_by_proxy_path
from burnlens.providers.azure import UPSTREAM_ENV, AzureOpenAIProvider
from burnlens.proxy.interceptor import handle_request
from burnlens.storage.queries import get_recent_requests


def test_registered():
    provider = get("azure")
    assert isinstance(provider, AzureOpenAIProvider)
    assert provider.config.proxy_path == "/proxy/azure"
    assert provider.config.auth_header == "api-key"
    assert provider.config.streaming_format == "sse-openai"
    assert provider.config.pricing_key == "openai"


def test_proxy_path_routing():
    provider = get_by_proxy_path("/proxy/azure/openai/deployments/gpt-4o/chat/completions")
    assert provider is not None and provider.config.name == "azure"


def test_upstream_from_env(monkeypatch):
    monkeypatch.setenv(UPSTREAM_ENV, "https://myres.openai.azure.com/")
    provider = get("azure")
    path = "/openai/deployments/gpt-4o/chat/completions?api-version=2024-02-01"
    assert (
        provider.resolve_upstream_url(path, {})
        == "https://myres.openai.azure.com/openai/deployments/gpt-4o/chat/completions?api-version=2024-02-01"
    )


def test_missing_endpoint_raises(monkeypatch):
    monkeypatch.delenv(UPSTREAM_ENV, raising=False)
    with pytest.raises(RuntimeError, match=UPSTREAM_ENV):
        _ = get("azure").upstream_base


def test_model_from_body():
    provider = get("azure")
    assert provider.extract_model({"model": "gpt-4o"}, "/openai/deployments/gpt-4o/chat/completions") == "gpt-4o"


def test_model_from_path_when_body_empty():
    provider = get("azure")
    model = provider.extract_model(
        {}, "/openai/deployments/my-gpt4o/chat/completions?api-version=2024-02-01"
    )
    assert model == "my-gpt4o"


def test_gpt35_spelling_aliased_and_prices():
    from burnlens.cost.calculator import calculate_cost, TokenUsage
    provider = get("azure")
    # Azure spells it without dots; extract_model maps to the canonical key.
    # NOTE: this tests the provider object only — see TestAzureCostsThroughProxy
    # for the interceptor path, which is where this mapping was dead until v1.8.2.
    model = provider.extract_model({"model": "gpt-35-turbo"}, "")
    assert model == "gpt-3.5-turbo"
    assert calculate_cost("azure", model, TokenUsage(input_tokens=1_000_000)) > 0


def test_arbitrary_deployment_maps_via_env(monkeypatch):
    from burnlens.cost.calculator import calculate_cost, TokenUsage
    monkeypatch.setenv("BURNLENS_AZURE_DEPLOYMENTS", "prod-gpt4o=gpt-4o, cheap=gpt-4o-mini")
    provider = get("azure")
    assert provider.extract_model({"model": "prod-gpt4o"}, "") == "gpt-4o"
    assert provider.extract_model({"model": "cheap"}, "") == "gpt-4o-mini"
    # unmapped deployment falls through to its own name (resolves if == a model)
    assert provider.extract_model({"model": "gpt-4o"}, "") == "gpt-4o"
    assert calculate_cost("azure", provider.extract_model({"model": "prod-gpt4o"}, ""),
                          TokenUsage(input_tokens=1_000_000)) > 0


def test_cost_resolves_via_provider_name():
    # The interceptor calls calculate_cost(provider.name, ...) — for azure the
    # name ("azure") differs from the pricing_key ("openai"). Regression guard:
    # this must NOT silently cost $0.
    from burnlens.cost.calculator import calculate_cost, TokenUsage
    from burnlens.cost.pricing import get_model_pricing

    assert get_model_pricing("azure", "gpt-4o") is not None
    cost = calculate_cost("azure", "gpt-4o", TokenUsage(input_tokens=1_000_000, output_tokens=0))
    assert cost > 0


def test_stream_usage_extraction_inherited():
    provider = get("azure")
    chunk = b'data: {"usage":{"prompt_tokens":100,"completion_tokens":25}}\n\n'
    acc: dict = {}
    provider.extract_usage_from_stream_chunk(chunk, acc)
    assert acc["input_tokens"] == 100 and acc["output_tokens"] == 25


# ---------------------------------------------------------------------------
# v1.8.2 regression: cost must be correct through the INTERCEPTOR, not just the
# provider object.  Until v1.8.2 the interceptor never called
# provider.extract_model(), so _AZURE_ALIASES and _deployment_map() were dead
# code in the proxy path and every such request logged $0.  The tests above pass
# against the provider object and did NOT catch it — these drive handle_request.
# ---------------------------------------------------------------------------


class _CannedTransport(httpx.AsyncBaseTransport):
    def __init__(self, payload: dict):
        self._payload = payload

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            content=json.dumps(self._payload).encode(),
            headers={"content-type": "application/json"},
        )


async def _logged_row(deployment: str, db_path: str) -> dict:
    """Route one Azure request through the interceptor; return its logged row."""
    transport = _CannedTransport({
        "id": "chatcmpl-test",
        "model": deployment,
        "choices": [{"message": {"role": "assistant", "content": "Hi"}}],
        "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 0},
    })
    await handle_request(
        client=httpx.AsyncClient(transport=transport),
        provider=get("azure"),
        path=f"/proxy/azure/openai/deployments/{deployment}/chat/completions",
        method="POST",
        headers={"content-type": "application/json"},
        body_bytes=json.dumps({"model": deployment, "messages": []}).encode(),
        query_string="",
        db_path=db_path,
        alert_engine=None,
    )
    for _ in range(10):
        await asyncio.sleep(0.05)
    rows = await get_recent_requests(db_path, limit=5)
    assert len(rows) == 1
    return rows[0]


class TestAzureCostsThroughProxy:
    async def test_dotless_gpt35_deployment_costs_nonzero(self, initialized_db, monkeypatch):
        monkeypatch.setenv(UPSTREAM_ENV, "https://myres.openai.azure.com")
        row = await _logged_row("gpt-35-turbo", initialized_db)
        assert row["model"] == "gpt-3.5-turbo"
        assert row["cost_usd"] == pytest.approx(0.50)  # $0.50/MTok in

    async def test_mapped_deployment_name_costs_nonzero(self, initialized_db, monkeypatch):
        monkeypatch.setenv(UPSTREAM_ENV, "https://myres.openai.azure.com")
        monkeypatch.setenv("BURNLENS_AZURE_DEPLOYMENTS", "prod-gpt4o=gpt-4o")
        row = await _logged_row("prod-gpt4o", initialized_db)
        assert row["model"] == "gpt-4o"
        assert row["cost_usd"] == pytest.approx(2.50)  # $2.50/MTok in

    async def test_google_model_in_path_still_extracted(self, initialized_db):
        """The deleted _extract_model_from_path was google-only; guard the
        behaviour it used to provide now that the provider owns it."""
        assert get("google").extract_model(
            {}, "/v1beta/models/gemini-1.5-pro:generateContent"
        ) == "gemini-1.5-pro"
