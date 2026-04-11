"""Billing endpoints — checkout, webhook, and local test-upgrade."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from burnlens_cloud.api.auth import get_current_org
from burnlens_cloud.config import settings
from burnlens_cloud.db.engine import get_db
from burnlens_cloud.db.models import Organization, WebhookEvent
from burnlens_cloud.lib.dodo import create_checkout, verify_webhook_signature

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])

VALID_TIERS = {"personal", "team", "enterprise"}


class CheckoutRequest(BaseModel):
    tier: str


class CheckoutResponse(BaseModel):
    checkout_url: str


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout_session(
    body: CheckoutRequest,
    org: Organization = Depends(get_current_org),
) -> CheckoutResponse:
    """Create a Dodo checkout session for tier upgrade."""
    if body.tier not in VALID_TIERS:
        raise HTTPException(status_code=400, detail=f"Invalid tier: {body.tier}")
    if org.tier == body.tier:
        raise HTTPException(status_code=400, detail="Already on this tier")

    url = await create_checkout(str(org.id), body.tier)
    return CheckoutResponse(checkout_url=url)


@router.get("/test-upgrade")
async def test_upgrade(
    org_id: str | None = None,
    tier: str = "team",
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Local development only: instantly upgrade an org's tier."""
    if settings.environment != "development":
        raise HTTPException(status_code=404)

    if org_id:
        result = await db.execute(
            select(Organization).where(Organization.id == org_id)
        )
    else:
        result = await db.execute(select(Organization).limit(1))

    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="No organization found")

    org.tier = tier
    await db.commit()
    return {"status": "upgraded", "org_id": str(org.id), "tier": tier}


@router.post("/webhook")
async def dodo_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Handle Dodo payment webhook events with idempotency."""
    payload = await request.body()
    signature = request.headers.get("x-dodo-signature", "")

    if not verify_webhook_signature(payload, signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    data = await request.json()
    webhook_id = data.get("id", "")
    event_name = data.get("event", "")

    if not webhook_id or not event_name:
        raise HTTPException(status_code=400, detail="Missing id or event")

    # Idempotency check
    existing = await db.execute(
        select(WebhookEvent).where(WebhookEvent.webhook_id == webhook_id)
    )
    if existing.scalar_one_or_none():
        return {"status": "already_processed"}

    # Extract org_id from metadata
    metadata = data.get("metadata", {})
    org_id = metadata.get("org_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="Missing org_id in metadata")

    result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Handle event types
    if event_name == "payment.succeeded":
        tier = metadata.get("tier", "team")
        org.tier = tier
        org.subscription_status = "active"
        org.subscription_id = data.get("subscription_id")

    elif event_name == "subscription.cancelled":
        org.tier = "free"
        org.subscription_status = "cancelled"

    elif event_name == "subscription.renewed":
        org.subscription_status = "active"

    # Record for idempotency
    db.add(WebhookEvent(webhook_id=webhook_id, event_name=event_name))
    await db.commit()

    return {"status": "processed", "event": event_name}
