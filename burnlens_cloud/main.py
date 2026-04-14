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

# Configure logging
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup/shutdown."""
    # Startup
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized")

    yield

    # Shutdown
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
    app.include_router(dashboard_router) # /api/* (summary, costs/by-model, etc.)
    app.include_router(billing_router)   # /billing/portal, /billing/webhooks/stripe
    app.include_router(team_router)      # /team/invite, /team/members, /team/activity

    return app


# Create app instance for Vercel
app = get_app()
