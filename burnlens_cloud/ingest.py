import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from dateutil import tz

from .auth import get_workspace_by_api_key
from .config import settings
from .database import execute_query, execute_bulk_insert
from .models import IngestRequest, IngestResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ingest"])


async def check_free_tier_limit(workspace_id: str) -> bool:
    """
    Check if workspace has exceeded free tier monthly limit.
    Returns True if under limit, False if exceeded.
    """
    # Get first day of current month (UTC)
    now = datetime.now(tz.UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    result = await execute_query(
        """
        SELECT COUNT(*) as count FROM request_records
        WHERE workspace_id = $1 AND received_at >= $2
        """,
        workspace_id,
        month_start,
    )

    count = result[0]["count"] if result else 0
    return count < settings.free_tier_monthly_limit


@router.post("/v1/ingest", response_model=IngestResponse)
async def ingest(request: IngestRequest):
    """
    Bulk ingest cost records from OSS proxy.

    Expected request body:
    {
        "api_key": "bl_live_...",
        "records": [
            {
                "timestamp": "2024-01-15T10:30:00Z",
                "provider": "openai",
                "model": "gpt-4o",
                "input_tokens": 100,
                "output_tokens": 50,
                ...
            }
        ]
    }

    Returns:
    {
        "accepted": 500,
        "rejected": 0
    }
    """
    # Validate API key and get workspace
    workspace_result = await get_workspace_by_api_key(request.api_key)
    if not workspace_result:
        logger.warning(f"Ingest request with invalid API key")
        raise HTTPException(status_code=401, detail="Invalid API key")

    workspace_id, plan = workspace_result

    # Check free tier limit
    if plan == "free":
        if not await check_free_tier_limit(workspace_id):
            logger.warning(f"Free tier limit exceeded for workspace {workspace_id}")
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "free_tier_limit",
                    "message": f"Free tier limit ({settings.free_tier_monthly_limit} records/month) exceeded",
                    "upgrade_url": "https://burnlens.app/upgrade",
                },
            )

    # Prepare bulk insert data
    insert_data = []
    for record in request.records:
        insert_data.append(
            (
                workspace_id,
                record.timestamp,
                record.provider,
                record.model,
                record.input_tokens,
                record.output_tokens,
                record.reasoning_tokens,
                record.cache_read_tokens,
                record.cache_write_tokens,
                float(record.cost_usd),
                record.duration_ms,
                record.status_code,
                record.tags,
                record.system_prompt_hash,
                datetime.utcnow(),
            )
        )

    # Bulk insert records
    try:
        await execute_bulk_insert(
            """
            INSERT INTO request_records
            (workspace_id, ts, provider, model, input_tokens, output_tokens,
             reasoning_tokens, cache_read_tokens, cache_write_tokens,
             cost_usd, duration_ms, status_code, tags, system_prompt_hash, received_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            """,
            insert_data,
        )

        logger.info(
            f"Ingested {len(request.records)} records for workspace {workspace_id}"
        )

        return IngestResponse(accepted=len(request.records), rejected=0)

    except Exception as e:
        logger.error(f"Failed to ingest records: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to ingest records. Please retry.",
        )
