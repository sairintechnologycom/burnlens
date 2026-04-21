import asyncio
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException

from .auth import get_workspace_by_api_key
from .database import execute_query, execute_bulk_insert
from .encryption import get_encryption_manager
from .models import IngestRequest, IngestResponse
from .telemetry.forwarder import get_forwarder

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ingest"])


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

    # Fetch full workspace details (including OTEL config)
    workspace_details = await execute_query(
        "SELECT otel_endpoint, otel_api_key_encrypted, otel_enabled FROM workspaces WHERE id = $1",
        workspace_id,
    )
    otel_config = workspace_details[0] if workspace_details else None

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

        # Queue OTEL forward as background task (never block on this)
        if otel_config and otel_config.get("otel_enabled"):
            try:
                forwarder = get_forwarder()
                endpoint = otel_config.get("otel_endpoint")
                encrypted_key = otel_config.get("otel_api_key_encrypted")

                if endpoint and encrypted_key:
                    # Decrypt API key
                    encryption_manager = get_encryption_manager()
                    api_key = encryption_manager.decrypt(encrypted_key)

                    # Convert records to dicts for OTEL forwarding
                    otel_records = []
                    for record in request.records:
                        otel_records.append(record.dict())

                    # Forward as background task (fire and forget)
                    asyncio.create_task(
                        forwarder.forward_batch(otel_records, endpoint, api_key)
                    )
            except Exception as e:
                logger.warning(f"Failed to queue OTEL forward: {e}")
                # Don't fail ingest on OTEL error

        return IngestResponse(accepted=len(request.records), rejected=0)

    except Exception as e:
        logger.error(f"Failed to ingest records: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to ingest records. Please retry.",
        )
