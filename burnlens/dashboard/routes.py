"""JSON API endpoints for the BurnLens dashboard."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from burnlens.storage.queries import get_recent_requests, get_total_cost, get_usage_by_model

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_db_path(request: Request) -> str:
    # Config is stored in app state by server.py lifespan
    return request.app.state.db_path if hasattr(request.app.state, "db_path") else _fallback_db()


def _fallback_db() -> str:
    from pathlib import Path

    return str(Path.home() / ".burnlens" / "burnlens.db")


@router.get("/summary")
async def summary(request: Request) -> dict:
    """Total cost and request count."""
    db_path = _fallback_db()
    total_cost = await get_total_cost(db_path)
    models = await get_usage_by_model(db_path)
    return {
        "total_cost_usd": round(total_cost, 6),
        "total_requests": sum(m.request_count for m in models),
        "models_used": len(models),
    }


@router.get("/models")
async def models(request: Request) -> list:
    """Per-model cost breakdown."""
    db_path = _fallback_db()
    rows = await get_usage_by_model(db_path)
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
async def recent_requests(limit: int = 50) -> list:
    """Most recent N requests."""
    db_path = _fallback_db()
    return await get_recent_requests(db_path, limit=min(limit, 500))
