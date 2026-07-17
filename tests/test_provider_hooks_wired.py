"""Guard against the recurring dead-abstraction bug: a Provider hook that exists,
is implemented, is unit-tested against the provider object — and is never called
by the proxy.

This has bitten BurnLens six times:

* v1.6.1 — the interceptor passed ``provider.name`` to the pricing lookup instead
  of ``pricing_key``; every Azure request cost $0.
* v1.8.2 — ``extract_model()`` was never called; Azure deployment aliases and the
  BURNLENS_AZURE_DEPLOYMENTS map were dead, so those requests cost $0.
* v1.8.3 — ``resolve_upstream_url()``, ``headers_to_strip()`` and
  ``should_buffer_chunk()`` were all never called (latent, no live mispricing).
* v1.9.0 — ``is_streaming()`` did not exist; streaming detection hardcoded
  Google's URL suffix.

Every one of them hid behind green tests that exercised the provider object
directly. These tests drive ``handle_request`` and assert the hooks are actually
reached, so a future refactor that quietly inlines one fails here.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from burnlens.providers import get
from burnlens.proxy.interceptor import handle_request


class _RecordingProvider:
    """Delegates to the real openai provider, recording which hooks get called."""

    def __init__(self) -> None:
        self._inner = get("openai")
        self.calls: set[str] = set()

    # -- config passthrough --------------------------------------------------
    @property
    def config(self):
        return self._inner.config

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def proxy_prefix(self) -> str:
        return self._inner.proxy_prefix

    @property
    def upstream_base(self) -> str:
        return self._inner.upstream_base

    @property
    def env_var(self) -> str:
        return self._inner.env_var

    # -- hooks under audit ---------------------------------------------------
    def resolve_upstream_url(self, request_path, headers):
        self.calls.add("resolve_upstream_url")
        return self._inner.resolve_upstream_url(request_path, headers)

    def extract_model(self, request_body, request_path):
        self.calls.add("extract_model")
        return self._inner.extract_model(request_body, request_path)

    def is_streaming(self, request_body, request_path):
        self.calls.add("is_streaming")
        return self._inner.is_streaming(request_body, request_path)

    def extract_usage(self, response_body):
        self.calls.add("extract_usage")
        return self._inner.extract_usage(response_body)

    def extract_usage_from_stream_chunk(self, chunk, accumulator):
        self.calls.add("extract_usage_from_stream_chunk")
        return self._inner.extract_usage_from_stream_chunk(chunk, accumulator)

    def should_buffer_chunk(self, chunk):
        self.calls.add("should_buffer_chunk")
        return self._inner.should_buffer_chunk(chunk)

    def headers_to_strip(self):
        self.calls.add("headers_to_strip")
        return self._inner.headers_to_strip()

    def rewrite_path_for_routing(self, path, routed_model):
        self.calls.add("rewrite_path_for_routing")
        return self._inner.rewrite_path_for_routing(path, routed_model)


class _Transport(httpx.AsyncBaseTransport):
    def __init__(self, body: bytes, stream: bool = False):
        self._body = body
        self._stream = stream
        self.captured: httpx.Request | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.captured = request
        ct = "text/event-stream" if self._stream else "application/json"
        return httpx.Response(200, content=self._body, headers={"content-type": ct})


async def _flush() -> None:
    for _ in range(10):
        await asyncio.sleep(0.05)


async def _run(provider, body: bytes, transport, db_path: str) -> None:
    _, _, _, stream = await handle_request(
        client=httpx.AsyncClient(transport=transport),
        provider=provider,
        path="/proxy/openai/v1/chat/completions",
        method="POST",
        headers={"content-type": "application/json"},
        body_bytes=body,
        query_string="",
        db_path=db_path,
        alert_engine=None,
    )
    if stream is not None:
        # The usage-extraction work lives in the generator's finally block, so it
        # only runs once a client drains the stream. Not draining it here would
        # make the streaming hook assertions vacuously pass.
        async for _chunk in stream:
            pass
    await _flush()


class TestNonStreamingHooksReached:
    async def test_hooks_called(self, initialized_db):
        provider = _RecordingProvider()
        transport = _Transport(json.dumps({
            "model": "gpt-4o",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }).encode())
        await _run(provider, json.dumps({"model": "gpt-4o", "messages": []}).encode(),
                   transport, initialized_db)

        for hook in ("resolve_upstream_url", "extract_model", "is_streaming",
                     "extract_usage", "headers_to_strip"):
            assert hook in provider.calls, (
                f"{hook}() was never called by handle_request — the proxy is "
                "bypassing the Provider interface again (see module docstring)"
            )


class TestStreamingHooksReached:
    async def test_stream_hooks_called(self, initialized_db):
        provider = _RecordingProvider()
        sse = (
            b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
            b'data: {"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n'
            b"data: [DONE]\n\n"
        )
        transport = _Transport(sse, stream=True)
        await _run(
            provider,
            json.dumps({"model": "gpt-4o", "messages": [], "stream": True}).encode(),
            transport,
            initialized_db,
        )

        for hook in ("is_streaming", "should_buffer_chunk",
                     "extract_usage_from_stream_chunk"):
            assert hook in provider.calls, (
                f"{hook}() was never called on the streaming path — usage gating "
                "or extraction has been inlined again (see module docstring)"
            )


class TestHeadersToStripIsAdditive:
    """headers_to_strip() must not replace the x-burnlens-* prefix rule.

    The base set names only 4 headers; the prefix rule covers every tag header.
    Swapping one for the other would leak tag_repo/tag_dev/tag_pr — internal git
    context — to the upstream provider.
    """

    async def test_git_tags_never_forwarded_upstream(self, initialized_db):
        transport = _Transport(json.dumps({
            "model": "gpt-4o", "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }).encode())
        await handle_request(
            client=httpx.AsyncClient(transport=transport),
            provider=get("openai"),
            path="/proxy/openai/v1/chat/completions",
            method="POST",
            headers={
                "content-type": "application/json",
                "x-burnlens-tag-repo": "acme/secret-repo",
                "x-burnlens-tag-dev": "bhushan",
                "x-burnlens-tag-pr": "42",
                "x-burnlens-key": "sk-internal-label",
            },
            body_bytes=json.dumps({"model": "gpt-4o", "messages": []}).encode(),
            query_string="",
            db_path=initialized_db,
            alert_engine=None,
        )
        await _flush()

        assert transport.captured is not None
        forwarded = {k.lower() for k in transport.captured.headers.keys()}
        for leaked in ("x-burnlens-tag-repo", "x-burnlens-tag-dev",
                       "x-burnlens-tag-pr", "x-burnlens-key"):
            assert leaked not in forwarded, f"{leaked} leaked upstream"


def test_every_declared_hook_is_covered_by_this_file():
    """If someone adds a new Provider hook, make them wire it AND cover it here.

    Catches the failure mode at its source: a hook added to the interface but
    never called by the proxy.
    """
    import inspect

    from burnlens.providers.base import Provider

    hooks = {
        name
        for name, member in inspect.getmembers(Provider, inspect.isfunction)
        if not name.startswith("_")
    }
    covered = set(_RecordingProvider.__dict__) & hooks
    missing = hooks - covered
    assert not missing, (
        f"Provider hooks not spied on in this file: {sorted(missing)}. Add them to "
        "_RecordingProvider and assert they're reached by handle_request."
    )
