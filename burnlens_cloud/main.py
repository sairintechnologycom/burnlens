import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .database import init_db, close_db
from .rate_limit import RateLimitMiddleware, DEFAULT_RULES
from .auth import router as auth_router
from .ingest import router as ingest_router
from .dashboard_api import router as dashboard_router
from .billing import router as billing_router
from .team_api import router as team_router
from .api_keys_api import router as api_keys_router
from .settings_api import router as settings_router
from .compliance.audit import router as audit_router
from .deployment_api import router as deployment_router
from .stubs_api import router as stubs_router
from .deployment.status import get_status_checker
from .compliance.purge import run_periodic_purge
from .compliance.retention_prune import run_periodic_retention_prune
from .email import drain_pending_email_tasks

# Configure logging
logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger(__name__)


async def _background_status_checker():
    """Background task: check endpoint health every N seconds."""
    checker = get_status_checker()
    while True:
        try:
            await asyncio.sleep(settings.status_check_interval_seconds)
            await checker.run_check()
        except Exception as e:
            logger.error(f"Status check error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup/shutdown."""
    # Startup
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized")

    # Start background status checker if enabled
    status_checker_task = None
    pii_purge_task = None
    retention_prune_task = None
    if settings.scheduler_enabled:
        logger.info("Starting background status checker...")
        status_checker_task = asyncio.create_task(_background_status_checker())
        logger.info("Starting background activity-PII purge...")
        pii_purge_task = asyncio.create_task(
            run_periodic_purge(
                initial_delay_s=60,
                interval_s=settings.activity_pii_purge_interval_seconds,
            )
        )
        logger.info("Starting background retention prune (daily 03:00 UTC)...")
        retention_prune_task = asyncio.create_task(run_periodic_retention_prune())

    yield

    # Shutdown
    # WR-03: give outstanding fire-and-forget email tasks a brief grace
    # period to complete their SendGrid POSTs before cancellation.
    try:
        await drain_pending_email_tasks(timeout=5.0)
    except Exception as exc:
        logger.warning("drain_pending_email_tasks failed: %s", exc)

    for task, name in (
        (status_checker_task, "status checker"),
        (pii_purge_task, "activity-PII purge"),
        (retention_prune_task, "retention prune"),
    ):
        if task:
            logger.info("Stopping background %s...", name)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    logger.info("Closing database...")
    await close_db()
    logger.info("Database closed")


def get_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="BurnLens Cloud Backend",
        description="Cost aggregation and billing service for BurnLens",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS — restrict to known frontends. Override via ALLOWED_ORIGINS env (comma-sep).
    _default_origins = f"{settings.burnlens_frontend_url},https://www.burnlens.app"
    _allowed_origins = [
        o.strip()
        for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",")
        if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
        # Shrink browser preflight cache from Starlette's 600s default to 60s so
        # CORS-related deploys don't leave active sessions with stale preflights
        # for ~10 min. See project_billing_summary_cors_regression.md.
        max_age=60,
    )

    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            response = await call_next(request)
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
            return response

    app.add_middleware(SecurityHeadersMiddleware)

    # Rate limit auth + ingest paths (per-IP sliding window, in-process).
    app.add_middleware(RateLimitMiddleware, rules=DEFAULT_RULES)

    # Health check endpoint (outside /api prefix)
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    # Root endpoint
    @app.get("/")
    async def root():
        return {"message": "BurnLens Cloud Backend"}

    # Register routers
    app.include_router(auth_router)      # /auth/login, /auth/signup
    app.include_router(ingest_router)    # /v1/ingest
    app.include_router(dashboard_router) # /api/v1/* (usage/summary, usage/by-model, etc.)
    app.include_router(billing_router)   # /billing/checkout, /billing/portal, /billing/webhook (Paddle)
    app.include_router(team_router)      # /team/invite, /team/members, /team/activity
    app.include_router(settings_router)  # /settings/otel, /settings/pricing
    app.include_router(audit_router)     # /api/audit-log, /api/audit-log/export
    app.include_router(deployment_router) # /status, /api/status
    app.include_router(stubs_router)     # stub endpoints — see burnlens_cloud/stubs_api.py
    app.include_router(api_keys_router)  # /api-keys CRUD (Phase 9 GATE-04)

    return app


# Create app instance for Vercel
app = get_app()
