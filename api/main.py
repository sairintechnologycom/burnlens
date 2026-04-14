"""FastAPI app — all routes registered here."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db, close_db
from .auth import router as auth_router
from .billing import router as billing_router
from .ingest import router as ingest_router
from .dashboard import router as dashboard_router

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(ingest_router)
app.include_router(dashboard_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
