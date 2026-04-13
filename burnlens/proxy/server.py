"""FastAPI application: proxy routes + dashboard serving."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiosqlite
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
_cloud_sync_task: asyncio.Task | None = None  # type: ignore[type-arg]
_scheduler = None  # APScheduler instance (type declared at assignment)


def get_app(config: BurnLensConfig) -> FastAPI:
    """Build and return the FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        global _http_client, _config, _alert_engine, _scheduler
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
        # Start cloud sync background task if enabled
        global _cloud_sync_task
        if config.cloud.enabled and config.cloud.api_key:
            try:
                from burnlens.cloud.sync import CloudSync

                cloud = CloudSync(config.cloud)
                app.state.cloud_sync = cloud
                _cloud_sync_task = asyncio.create_task(
                    cloud.start_sync_loop(config.db_path)
                )
                logger.info("Cloud sync enabled — pushing to %s", config.cloud.endpoint)
            except Exception:
                logger.warning("Could not start cloud sync", exc_info=True)

        # Start detection scheduler (hourly, first run deferred)
        from burnlens.alerts.discovery import DiscoveryAlertEngine
        from burnlens.detection.scheduler import (
            get_scheduler,
            register_alert_jobs,
            register_detection_jobs,
        )

        _discovery_alert_engine = DiscoveryAlertEngine(config, config.db_path)

        _scheduler = get_scheduler()
        register_detection_jobs(_scheduler, config.db_path, config)
        register_alert_jobs(_scheduler, config.db_path, config, _discovery_alert_engine)
        _scheduler.start()
        logger.info("Detection scheduler started (hourly)")
        logger.info("Alert jobs registered (hourly discovery, daily digest, weekly digest)")

        logger.info("BurnLens proxy ready on http://%s:%d", config.host, config.port)
        yield

        # Shut down detection scheduler
        _scheduler.shutdown(wait=False)
        logger.info("Detection scheduler stopped")

        # Shut down cloud sync
        if _cloud_sync_task is not None:
            _cloud_sync_task.cancel()
            try:
                await _cloud_sync_task
            except asyncio.CancelledError:
                pass
            if hasattr(app.state, "cloud_sync"):
                await app.state.cloud_sync.close()
            _cloud_sync_task = None

        await _http_client.aclose()
        _http_client = None

    app = FastAPI(title="BurnLens", version="0.1.0", lifespan=lifespan)

    # --------------------------------------------------------- dashboard auth
    import os
    import secrets

    if config.dashboard_user and config.dashboard_pass:
        import base64

        _auth_user = config.dashboard_user
        _auth_pass = config.dashboard_pass

        @app.middleware("http")
        async def dashboard_basic_auth(request: Request, call_next):  # type: ignore[no-untyped-def]
            """Require basic auth for /ui and /api routes (not /proxy or /health)."""
            path = request.url.path
            if path.startswith("/proxy") or path == "/health":
                return await call_next(request)

            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Basic "):
                try:
                    decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                    user, password = decoded.split(":", 1)
                    if (
                        secrets.compare_digest(user, _auth_user)
                        and secrets.compare_digest(password, _auth_pass)
                    ):
                        return await call_next(request)
                except Exception:
                    pass

            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="BurnLens Dashboard"'},
                content="Unauthorized",
            )

        logger.info("Dashboard basic auth enabled")

    # ------------------------------------------------------------------ CORS
    from fastapi.middleware.cors import CORSMiddleware

    _default_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
    _env_origins = os.environ.get("ALLOWED_ORIGINS", "")
    _origins = [o.strip() for o in _env_origins.split(",") if o.strip()] if _env_origins else _default_origins

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------ health

    @app.get("/health")
    async def health() -> dict:
        from burnlens import __version__

        db_status = "disconnected"
        try:
            async with aiosqlite.connect(app.state.db_path) as db:
                await db.execute("SELECT 1")
                db_status = "connected"
        except Exception:
            pass

        status = "ok" if db_status == "connected" else "degraded"
        return {"status": status, "version": __version__, "db": db_status}

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

        if _http_client is None or _config is None:
            return Response(
                content="Proxy not initialized — server is starting up",
                status_code=503,
            )

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
                customer_budgets=_config.alerts.customer_budgets,
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
        from fastapi.responses import FileResponse

        _static_dir = _Path(__file__).parent.parent / "dashboard" / "static"
        if _static_dir.exists():
            @app.get("/ui/discovery")
            async def discovery_ui() -> FileResponse:
                return FileResponse(_static_dir / "discovery.html")

            app.mount("/ui", StaticFiles(directory=str(_static_dir), html=True), name="ui")
    except Exception as exc:
        logger.warning("Could not mount dashboard static files: %s", exc)

    # ---------------------------------------------------------------- dashboard API

    try:
        from burnlens.dashboard.routes import router as dashboard_router

        app.include_router(dashboard_router, prefix="/api")
    except Exception as exc:
        logger.warning("Could not load dashboard API routes: %s", exc)

    # ----------------------------------------- cloud-compatible API (for Next.js frontend)

    try:
        from burnlens.dashboard.cloud_compat import usage_router, requests_router

        app.include_router(usage_router, prefix="/api/v1/usage")
        app.include_router(requests_router, prefix="/api/v1")
    except Exception as exc:
        logger.warning("Could not load cloud-compat API routes: %s", exc)

    # --------------------------------------------------------- asset management API v1

    try:
        from burnlens.api.assets import router as assets_router
        from burnlens.api.discovery import router as discovery_router
        from burnlens.api.providers import router as providers_router

        app.include_router(assets_router, prefix="/api/v1/assets")
        app.include_router(discovery_router, prefix="/api/v1")
        app.include_router(providers_router, prefix="/api/v1")
    except Exception as exc:
        logger.warning("Could not load API v1 routes: %s", exc)

    return app
