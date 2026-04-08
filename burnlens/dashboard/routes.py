"""JSON API endpoints for the BurnLens dashboard."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request

from burnlens.storage.queries import get_recent_requests, get_total_cost, get_usage_by_model

logger = logging.getLogger(__name__)
router = APIRouter()

_DEFAULT_DB = str(Path.home() / ".burnlens" / "burnlens.db")


def _db_path(request: Request) -> str:
    """Get db_path from app state (set by lifespan) or fall back to default."""
    return getattr(request.app.state, "db_path", _DEFAULT_DB)


@router.get("/summary")
async def summary(request: Request) -> dict:
    """Total cost and request count."""
    db = _db_path(request)
    total_cost = await get_total_cost(db)
    models = await get_usage_by_model(db)
    return {
        "total_cost_usd": round(total_cost, 6),
        "total_requests": sum(m.request_count for m in models),
        "models_used": len(models),
    }


@router.get("/models")
async def models(request: Request) -> list:
    """Per-model cost breakdown."""
    db = _db_path(request)
    rows = await get_usage_by_model(db)
    return [
        {
            "model": r.model,
            "provider": r.provider,
            "request_count": r.request_count,
            "total_input_tokens": r.total_input_tokens,
            "total_output_tokens": r.total_output_tokens,
            "total_cost_usd": round(r.total_cost_usd, 6),
        }
        for r in rows
    ]


@router.get("/requests")
async def recent_requests(request: Request, limit: int = 50) -> list:
    """Most recent N requests."""
    db = _db_path(request)
    return await get_recent_requests(db, limit=min(limit, 500))
