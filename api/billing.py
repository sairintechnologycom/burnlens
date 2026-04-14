"""Stripe billing endpoints — checkout, webhook, portal."""
from __future__ import annotations

import logging

import stripe
from fastapi import APIRouter, HTTPException, Request

from . import config
from .auth import get_current_workspace
from .models import CheckoutRequest, CheckoutResponse, PortalResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing")

stripe.api_key = config.STRIPE_SECRET_KEY

# Map Stripe price IDs to plan names
_PRICE_TO_PLAN: dict[str, str] = {}


def _get_price_to_plan() -> dict[str, str]:
    """Lazy-init price→plan mapping (env vars may not be set at import time)."""
    if not _PRICE_TO_PLAN:
        if config.STRIPE_CLOUD_PRICE_ID:
            _PRICE_TO_PLAN[config.STRIPE_CLOUD_PRICE_ID] = "cloud"
        if config.STRIPE_TEAMS_PRICE_ID:
            _PRICE_TO_PLAN[config.STRIPE_TEAMS_PRICE_ID] = "teams"
    return _PRICE_TO_PLAN


# ---- Checkout ---------------------------------------------------------------

@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(body: CheckoutRequest, request: Request):
    """Create a Stripe Checkout Session for plan upgrade."""
    ws = await get_current_workspace(request)

    if ws["plan"] == body.plan:
        raise HTTPException(status_code=400, detail={"error": "already_on_plan"})

    price_id = (
        config.STRIPE_CLOUD_PRICE_ID
        if body.plan == "cloud"
        else config.STRIPE_TEAMS_PRICE_ID
    )

    # Fetch owner_email for the checkout session
    from .database import pool
    async with pool.acquire() as conn:
        email = await conn.fetchval(
            "SELECT owner_email FROM workspaces WHERE id = $1", ws["id"]
        )

    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        customer_email=email,
        metadata={"workspace_id": ws["id"]},
        success_url="https://burnlens.app/dashboard?upgraded=1",
        cancel_url="https://burnlens.app/dashboard",
    )

    return CheckoutResponse(checkout_url=session.url)


# ---- Webhook ----------------------------------------------------------------

@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events. No JWT auth — Stripe signs the payload."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig, config.STRIPE_WEBHOOK_SECRET
        )
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        if event["type"] == "checkout.session.completed":
            await _handle_checkout_completed(event["data"]["object"])
        elif event["type"] == "customer.subscription.deleted":
            await _handle_subscription_deleted(event["data"]["object"])
        elif event["type"] == "invoice.payment_failed":
            session_data = event["data"]["object"]
            logger.warning(
                "Payment failed for customer %s", session_data.get("customer")
            )
    except Exception:
        logger.exception("Error processing Stripe event %s", event["type"])

    # Always return 200 to Stripe
    return {"received": True}


async def _handle_checkout_completed(session: dict) -> None:
    """Upgrade workspace plan after successful checkout."""
    workspace_id = session["metadata"]["workspace_id"]
    customer_id = session["customer"]

    # Determine plan from the price in line_items
    line_items = stripe.checkout.Session.list_line_items(session["id"])
    price_id = line_items["data"][0]["price"]["id"]
    price_map = _get_price_to_plan()
    plan = price_map.get(price_id, "cloud")

    from .database import pool
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE workspaces SET plan = $1, stripe_customer_id = $2 WHERE id = $3",
            plan,
            customer_id,
            workspace_id,
        )
    logger.info("Workspace %s upgraded to %s", workspace_id, plan)


async def _handle_subscription_deleted(subscription: dict) -> None:
    """Downgrade workspace to free when subscription is cancelled."""
    customer_id = subscription["customer"]

    from .database import pool
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE workspaces SET plan = 'free' WHERE stripe_customer_id = $1",
            customer_id,
        )
    logger.info("Customer %s downgraded to free (subscription deleted)", customer_id)


# ---- Billing Portal ---------------------------------------------------------

@router.get("/portal", response_model=PortalResponse)
async def billing_portal(request: Request):
    """Create a Stripe billing portal session for managing subscription."""
    ws = await get_current_workspace(request)

    from .database import pool
    async with pool.acquire() as conn:
        cust_id = await conn.fetchval(
            "SELECT stripe_customer_id FROM workspaces WHERE id = $1", ws["id"]
        )

    if not cust_id:
        raise HTTPException(
            status_code=400, detail={"error": "no_billing_history"}
        )

    session = stripe.billing_portal.Session.create(
        customer=cust_id,
        return_url="https://burnlens.app/dashboard",
    )

    return PortalResponse(portal_url=session.url)
