"""BurnLens Cloud API server."""

import os

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    from burnlens_cloud.api.billing import router as billing_router
    from burnlens_cloud.api.ingest import router as ingest_router
    from burnlens_cloud.api.orgs import router as orgs_router
    from burnlens_cloud.api.usage import router as usage_router

    app = FastAPI(
        title="BurnLens Cloud",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Retry-After"],
    )

    app.include_router(orgs_router)
    app.include_router(ingest_router)
    app.include_router(billing_router)
    app.include_router(usage_router)

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "env": os.getenv("ENVIRONMENT", "development"),
        }

    return app


app = create_app()


def run() -> None:
    """Entry point for burnlens-cloud CLI."""
    uvicorn.run(
        "burnlens_cloud.main:app",
        host="0.0.0.0",
        port=8000,
        reload=os.getenv("ENVIRONMENT") == "development",
    )
