"""Pydantic v2 request/response schemas for the BurnLens asset management API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from burnlens.storage.models import AiAsset, DiscoveryEvent, ProviderSignature


# ---------------------------------------------------------------------------
# Asset schemas
# ---------------------------------------------------------------------------


class AssetResponse(BaseModel):
    """Single asset in list or detail response."""

    id: int
    provider: str
    model_name: str
    endpoint_url: str
    api_key_hash: str | None
    owner_team: str | None
    project: str | None
    status: str
    risk_tier: str
    first_seen_at: datetime
    last_active_at: datetime
    monthly_spend_usd: float
    monthly_requests: int
    tags: dict[str, str]
    created_at: datetime
    updated_at: datetime


class AssetListResponse(BaseModel):
    """Paginated asset list."""

    items: list[AssetResponse]
    total: int
    limit: int
    offset: int


class AssetUpdateRequest(BaseModel):
    """PATCH body for updating asset fields. All fields are optional."""

    owner_team: str | None = None
    risk_tier: str | None = None
    tags: dict[str, str] | None = None
    status: str | None = None


class AssetApproveResponse(BaseModel):
    """Response after approving an asset — returns the updated asset and event id."""

    asset: AssetResponse
    event_id: int


# ---------------------------------------------------------------------------
# Summary schema
# ---------------------------------------------------------------------------


class AssetSummaryResponse(BaseModel):
    """Aggregated asset counts for the summary dashboard widget."""

    total: int
    by_provider: dict[str, int]
    by_status: dict[str, int]
    by_risk_tier: dict[str, int]
    new_this_week: int


# ---------------------------------------------------------------------------
# Discovery event schemas
# ---------------------------------------------------------------------------


class DiscoveryEventResponse(BaseModel):
    """Single discovery event."""

    id: int
    event_type: str
    asset_id: int | None
    details: dict
    detected_at: datetime


class DiscoveryEventListResponse(BaseModel):
    """Paginated discovery event list."""

    items: list[DiscoveryEventResponse]
    total: int


# ---------------------------------------------------------------------------
# Provider signature schemas
# ---------------------------------------------------------------------------


class SignatureResponse(BaseModel):
    """Single provider signature."""

    id: int
    provider: str
    endpoint_pattern: str
    header_signature: dict
    model_field_path: str


class SignatureCreateRequest(BaseModel):
    """Request body for creating a new provider signature."""

    provider: str
    endpoint_pattern: str
    header_signature: dict = Field(default_factory=dict)
    model_field_path: str = "body.model"


# ---------------------------------------------------------------------------
# Dataclass → Pydantic converter helpers
# ---------------------------------------------------------------------------


def asset_to_response(asset: AiAsset) -> AssetResponse:
    """Convert an AiAsset dataclass to an AssetResponse Pydantic model.

    Raises:
        ValueError: If asset.id is None (not yet persisted to DB).
    """
    if asset.id is None:
        raise ValueError("Cannot convert unsaved AiAsset (id is None) to AssetResponse")
    return AssetResponse(
        id=asset.id,
        provider=asset.provider,
        model_name=asset.model_name,
        endpoint_url=asset.endpoint_url,
        api_key_hash=asset.api_key_hash,
        owner_team=asset.owner_team,
        project=asset.project,
        status=asset.status,
        risk_tier=asset.risk_tier,
        first_seen_at=asset.first_seen_at,
        last_active_at=asset.last_active_at,
        monthly_spend_usd=asset.monthly_spend_usd,
        monthly_requests=asset.monthly_requests,
        tags=asset.tags,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )


def event_to_response(event: DiscoveryEvent) -> DiscoveryEventResponse:
    """Convert a DiscoveryEvent dataclass to a DiscoveryEventResponse Pydantic model.

    Raises:
        ValueError: If event.id is None (not yet persisted to DB).
    """
    if event.id is None:
        raise ValueError("Cannot convert unsaved DiscoveryEvent (id is None) to DiscoveryEventResponse")
    return DiscoveryEventResponse(
        id=event.id,
        event_type=event.event_type,
        asset_id=event.asset_id,
        details=event.details,
        detected_at=event.detected_at,
    )


def signature_to_response(sig: ProviderSignature) -> SignatureResponse:
    """Convert a ProviderSignature dataclass to a SignatureResponse Pydantic model.

    Raises:
        ValueError: If sig.id is None (not yet persisted to DB).
    """
    if sig.id is None:
        raise ValueError("Cannot convert unsaved ProviderSignature (id is None) to SignatureResponse")
    return SignatureResponse(
        id=sig.id,
        provider=sig.provider,
        endpoint_pattern=sig.endpoint_pattern,
        header_signature=sig.header_signature,
        model_field_path=sig.model_field_path,
    )
