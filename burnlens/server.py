"""burnlens.server — top-level app factory used by integration tests and the CLI."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

from burnlens.alerts.engine import AlertEngine
from burnlens.config import BurnLensConfig
from burnlens.proxy.interceptor import handle_request
from burnlens.proxy.providers import get_provider_for_path
from burnlens.storage.database import init_db

logger = logging.getLogger(__name__)


def create_app(
    db_path: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    """Create the BurnLens ASGI app.

    Accepts an optional *db_path* override so tests can point at a temp DB
    without needing a full BurnLensConfig.  Uses a general ``/{path:path}``
    catch-all route so tests can call short provider prefixes like
    ``/openai/v1/chat/completions`` after patching DEFAULT_PROVIDERS.
    """
    config = BurnLensConfig()
    if db_path is not None:
        config.db_path = db_path

    # Use mutable containers so the closures below can rebind them.
    _state: dict[str, object] = {}

    _owns_client = http_client is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await init_db(config.db_path)
        _state["alert_engine"] = AlertEngine(config, config.db_path)
        _state["http_client"] = http_client if http_client is not None else httpx.AsyncClient(
            timeout=httpx.Timeout(300.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        yield
        if _owns_client:
            client: httpx.AsyncClient = _state["http_client"]  # type: ignore[assignment]
            await client.aclose()

    app = FastAPI(title="BurnLens", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    )
    async def proxy_handler(request: Request, path: str) -> Response:
        full_path = f"/{path}"
        provider = get_provider_for_path(full_path)

        if provider is None:
            return Response(
                content=f"Unknown provider path: {full_path}",
                status_code=404,
            )

        body_bytes = await request.body()
        headers = dict(request.headers)
        query_string = str(request.url.query)

        client: httpx.AsyncClient = _state["http_client"]  # type: ignore[assignment]
        alert_engine: AlertEngine | None = _state.get("alert_engine")  # type: ignore[assignment]

        try:
            status, resp_headers, body, stream = await handle_request(
                client=client,
                provider=provider,
                path=full_path,
                method=request.method,
                headers=headers,
                body_bytes=body_bytes,
                query_string=query_string,
                db_path=config.db_path,
                alert_engine=alert_engine,
            )
        except httpx.RequestError as exc:
            logger.error("Upstream request failed: %s", exc)
            return Response(content=f"Upstream error: {exc}", status_code=502)

        if stream is not None:
            return StreamingResponse(
                content=stream,
                status_code=status,
                headers=resp_headers,
                media_type=resp_headers.get("content-type", "text/event-stream"),
            )

        return Response(
            content=body,
            status_code=status,
            headers=resp_headers,
            media_type=resp_headers.get("content-type", "application/json"),
        )

    return app
