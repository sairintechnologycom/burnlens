import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db, close_db
from .auth import router as auth_router
from .ingest import router as ingest_router
from .dashboard_api import router as dashboard_router
from .billing import router as billing_router
from .team_api import router as team_router
from .settings_api import router as settings_router
from .compliance.audit import router as audit_router
from .deployment_api import router as deployment_router
from .deployment.status import get_status_checker

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
    if settings.scheduler_enabled:
        logger.info("Starting background status checker...")
        status_checker_task = asyncio.create_task(_background_status_checker())

    yield

    # Shutdown
    if status_checker_task:
        logger.info("Stopping background status checker...")
        status_checker_task.cancel()
        try:
            await status_checker_task
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

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # TODO: restrict to burnlens.app domains in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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

    return app


# Create app instance for Vercel
app = get_app()
