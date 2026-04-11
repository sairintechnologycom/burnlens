"""Batch ingest endpoint for syncing request logs from local proxy."""

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from burnlens_cloud.api.auth import rate_limit
from burnlens_cloud.config import settings
from burnlens_cloud.db.engine import get_db
from burnlens_cloud.db.models import Organization, RequestLog

router = APIRouter(prefix="/api/v1", tags=["ingest"])

IDENTIFIER_FIELDS = ("provider", "model", "tag_feature", "tag_team", "tag_customer")


class IngestRecord(BaseModel):
    timestamp: datetime
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: Decimal
    duration_ms: int | None = None
    status_code: int | None = None
    system_prompt_hash: str | None = None
    tag_feature: str | None = None
    tag_team: str | None = None
    tag_customer: str | None = None

    @field_validator("cost_usd")
    @classmethod
    def cost_sanity_check(cls, v: Decimal) -> Decimal:
        if v > 100:
            raise ValueError("cost_usd exceeds sanity limit")
        return v


class IngestBatch(BaseModel):
    records: list[IngestRecord]

    @field_validator("records")
    @classmethod
    def max_batch_size(cls, v: list[IngestRecord]) -> list[IngestRecord]:
        limit = settings.max_ingest_batch_size
        if len(v) > limit:
            raise ValueError(f"max {limit} records per batch")
        return v


class IngestResponse(BaseModel):
    inserted: int
    rejected: int
    errors: list[str]


def _check_privacy(record: IngestRecord) -> str | None:
    """Reject records where identifier fields look like prose."""
    for field_name in IDENTIFIER_FIELDS:
        value = getattr(record, field_name, None)
        if value and " " in value and len(value) > 60:
            return f"field '{field_name}' looks like prose (len={len(value)})"
    return None


@router.post("/ingest", response_model=IngestResponse)
async def ingest_batch(
    body: IngestBatch,
    org: Organization = Depends(rate_limit),
    db: AsyncSession = Depends(get_db),
) -> IngestResponse:
    """Insert a batch of request log records for the authenticated org."""
    rejected = 0
    errors: list[str] = []
    valid_rows: list[dict] = []

    for i, record in enumerate(body.records):
        privacy_err = _check_privacy(record)
        if privacy_err:
            rejected += 1
            errors.append(f"record[{i}]: {privacy_err}")
            continue

        valid_rows.append(
            {
                "org_id": org.id,
                "timestamp": record.timestamp,
                "provider": record.provider,
                "model": record.model,
                "input_tokens": record.input_tokens,
                "output_tokens": record.output_tokens,
                "reasoning_tokens": record.reasoning_tokens,
                "cache_read_tokens": record.cache_read_tokens,
                "cache_write_tokens": record.cache_write_tokens,
                "cost_usd": record.cost_usd,
                "duration_ms": record.duration_ms,
                "status_code": record.status_code,
                "system_prompt_hash": record.system_prompt_hash,
                "tag_feature": record.tag_feature,
                "tag_team": record.tag_team,
                "tag_customer": record.tag_customer,
            }
        )

    inserted = 0
    if valid_rows:
        try:
            await db.execute(insert(RequestLog), valid_rows)
            await db.commit()
            inserted = len(valid_rows)
        except Exception as exc:
            await db.rollback()
            rejected += len(valid_rows)
            inserted = 0
            errors.append(f"bulk insert failed: {str(exc)[:200]}")

    return IngestResponse(inserted=inserted, rejected=rejected, errors=errors)
