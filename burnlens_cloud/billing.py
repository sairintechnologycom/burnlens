import logging
from fastapi import APIRouter, HTTPException, Depends, Request
import stripe

from .auth import verify_token, TokenPayload
from .config import settings
from .database import execute_query, execute_insert

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

# Initialize Stripe
stripe.api_key = settings.stripe_api_key


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    """
    Handle Stripe webhook events.
    Updates workspace plan based on subscription events.
    """
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=500, detail="Stripe webhook secret not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            settings.stripe_webhook_secret,
        )
    except ValueError:
        logger.error("Invalid payload")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVeratureError:
        logger.error("Invalid signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]

    try:
        if event_type == "customer.subscription.created":
            await handle_subscription_created(event["data"]["object"])
        elif event_type == "customer.subscription.updated":
            await handle_subscription_updated(event["data"]["object"])
        elif event_type == "customer.subscription.deleted":
            await handle_subscription_deleted(event["data"]["object"])
        elif event_type == "invoice.payment_failed":
            await handle_payment_failed(event["data"]["object"])
    except Exception as e:
        logger.error(f"Error handling webhook: {e}")
        # Don't raise — Stripe retries if we don't acknowledge

    return {"status": "received"}


async def handle_subscription_created(subscription: dict):
    """Handle subscription.created event."""
    customer_id = subscription.get("customer")
    items = subscription.get("items", {}).get("data", [])

    if not items:
        return

    # Map product/price to plan
    product_id = items[0]["product"]
    plan = await get_plan_from_product(product_id)

    # Update workspace
    await execute_insert(
        """
        UPDATE workspaces
        SET plan = $1, stripe_customer_id = $2
        WHERE stripe_customer_id = $3
        """,
        plan,
        customer_id,
        customer_id,
    )

    logger.info(f"Subscription created for {customer_id}: plan={plan}")


async def handle_subscription_updated(subscription: dict):
    """Handle subscription.updated event."""
    customer_id = subscription.get("customer")
    items = subscription.get("items", {}).get("data", [])

    if not items:
        return

    product_id = items[0]["product"]
    plan = await get_plan_from_product(product_id)

    # Update workspace
    await execute_insert(
        """
        UPDATE workspaces
        SET plan = $1
        WHERE stripe_customer_id = $2
        """,
        plan,
        customer_id,
    )

    logger.info(f"Subscription updated for {customer_id}: plan={plan}")


async def handle_subscription_deleted(subscription: dict):
    """Handle subscription.deleted event (downgrade to free)."""
    customer_id = subscription.get("customer")

    # Downgrade to free
    await execute_insert(
        """
        UPDATE workspaces
        SET plan = 'free'
        WHERE stripe_customer_id = $1
        """,
        customer_id,
    )

    logger.info(f"Subscription cancelled for {customer_id}: downgraded to free")


async def handle_payment_failed(invoice: dict):
    """Handle invoice.payment_failed event."""
    customer_id = invoice.get("customer")
    logger.warning(f"Payment failed for {customer_id}")

    # TODO: Send email notification to workspace owner


async def get_plan_from_product(product_id: str) -> str:
    """Map Stripe product/price to plan name."""
    # Simplified mapping — in production, store price IDs in config
    plan_mapping = {
        "prod_cloud": "cloud",
        "prod_teams": "teams",
        "prod_enterprise": "enterprise",
    }

    return plan_mapping.get(product_id, "free")


@router.post("/checkout")
async def create_checkout_session(token: TokenPayload = Depends(verify_token)):
    """
    Create a Stripe Checkout session for plan upgrade.
    Returns a redirect URL to the hosted Stripe checkout page.
    """
    if not settings.stripe_api_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    # Pick price based on current workspace plan (personal → team upgrade)
    price_id = settings.stripe_price_team or settings.stripe_price_personal
    if not price_id:
        raise HTTPException(status_code=500, detail="Stripe price IDs not configured")

    # Get or create Stripe customer for this workspace
    result = await execute_query(
        "SELECT stripe_customer_id FROM workspaces WHERE id = $1",
        str(token.workspace_id),
    )
    customer_id = result[0].get("stripe_customer_id") if result else None

    try:
        session_params = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": f"{settings.burnlens_frontend_url}/dashboard?upgraded=1",
            "cancel_url": f"{settings.burnlens_frontend_url}/settings",
        }
        if customer_id:
            session_params["customer"] = customer_id

        session = stripe.checkout.Session.create(**session_params)
        return {"url": session.url}
    except stripe.error.StripeError as e:
        logger.error(f"Failed to create checkout session: {e}")
        raise HTTPException(status_code=500, detail="Failed to create checkout session")


@router.get("/portal")
async def billing_portal(token: TokenPayload = Depends(verify_token)):
    """
    Return Stripe billing portal URL for self-serve plan management.
    """
    # Get workspace's Stripe customer ID
    result = await execute_query(
        "SELECT stripe_customer_id FROM workspaces WHERE id = $1",
        str(token.workspace_id),
    )

    if not result or not result[0].get("stripe_customer_id"):
        raise HTTPException(
            status_code=404,
            detail="No billing information found for this workspace",
        )

    customer_id = result[0]["stripe_customer_id"]

    try:
        # Create billing portal session
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url="https://burnlens.app/dashboard",
        )

        return {"url": session.url}
    except stripe.error.StripeError as e:
        logger.error(f"Failed to create billing portal session: {e}")
        raise HTTPException(status_code=500, detail="Failed to create billing portal")
