"""FastAPI app — all routes registered here."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from .database import init_db, close_db
from .auth import router as auth_router
from .billing import router as billing_router
from .ingest import router as ingest_router
from .dashboard import router as dashboard_router
from .team import router as team_router
from .enterprise import router as enterprise_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database…")
    await init_db()
    logger.info("Database ready")
    yield
    logger.info("Shutting down…")
    await close_db()


app = FastAPI(
    title="BurnLens Cloud",
    version="0.1.0",
    lifespan=lifespan,
)

_DEFAULT_ALLOWED_ORIGINS = "https://burnlens.app,https://www.burnlens.app"
_allowed_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", _DEFAULT_ALLOWED_ORIGINS).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
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

app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(ingest_router)
app.include_router(dashboard_router)
app.include_router(team_router)
app.include_router(enterprise_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
