"""FastAPI application: proxy routes + dashboard serving."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from burnlens.alerts.engine import AlertEngine
from burnlens.config import BurnLensConfig
from burnlens.proxy.interceptor import handle_request
from burnlens.proxy.providers import get_provider_for_path
from burnlens.storage.database import init_db

logger = logging.getLogger(__name__)

# Module-level references set during startup
_http_client: httpx.AsyncClient | None = None
_config: BurnLensConfig | None = None
_alert_engine: AlertEngine | None = None


def get_app(config: BurnLensConfig) -> FastAPI:
    """Build and return the FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        global _http_client, _config, _alert_engine
        _config = config
        app.state.db_path = config.db_path
        app.state.config = config

        # Init DB (creates tables if needed)
        await init_db(config.db_path)
        logger.info("Database ready at %s", config.db_path)

        # Build alert engine (one instance per proxy run; holds dedup state)
        _alert_engine = AlertEngine(config, config.db_path)

        # Shared HTTP client — reused across all requests
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(300.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        logger.info("BurnLens proxy ready on http://%s:%d", config.host, config.port)
        yield

        await _http_client.aclose()
        _http_client = None

    app = FastAPI(title="BurnLens", version="0.1.0", lifespan=lifespan)

    # ------------------------------------------------------------------ health

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    # ------------------------------------------------------------------ proxy

    @app.api_route(
        "/proxy/{path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    )
    async def proxy_handler(request: Request, path: str) -> Response:
        full_path = f"/{path}"
        provider = get_provider_for_path(f"/proxy/{path}")

        if provider is None:
            return Response(
                content=f"Unknown provider path: /proxy/{path}",
                status_code=404,
            )

        body_bytes = await request.body()
        headers = dict(request.headers)
        query_string = str(request.url.query)

        assert _http_client is not None, "HTTP client not initialized"
        assert _config is not None, "Config not initialized"

        try:
            status, resp_headers, body, stream = await handle_request(
                client=_http_client,
                provider=provider,
                path=f"/proxy/{path}",
                method=request.method,
                headers=headers,
                body_bytes=body_bytes,
                query_string=query_string,
                db_path=_config.db_path,
                alert_engine=_alert_engine,
            )
        except httpx.RequestError as exc:
            logger.error("Upstream request failed: %s", exc)
            return Response(
                content=f"Upstream error: {exc}",
                status_code=502,
            )

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

    # ---------------------------------------------------------------- dashboard

    @app.get("/ui")
    async def ui_redirect() -> RedirectResponse:
        return RedirectResponse(url="/ui/", status_code=301)

    try:
        from pathlib import Path as _Path

        _static_dir = _Path(__file__).parent.parent / "dashboard" / "static"
        if _static_dir.exists():
            app.mount("/ui", StaticFiles(directory=str(_static_dir), html=True), name="ui")
    except Exception as exc:
        logger.warning("Could not mount dashboard static files: %s", exc)

    # ---------------------------------------------------------------- dashboard API

    try:
        from burnlens.dashboard.routes import router as dashboard_router

        app.include_router(dashboard_router, prefix="/api")
    except Exception as exc:
        logger.warning("Could not load dashboard API routes: %s", exc)

    return app
