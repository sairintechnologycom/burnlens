"""Paddle Billing endpoints — checkout (server-side transaction), webhook, portal."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .auth import verify_token, TokenPayload
from .config import settings
from .database import execute_insert, execute_query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


# ---------------------------------------------------------------------------
# Paddle HTTP client helpers
# ---------------------------------------------------------------------------

def _paddle_base_url() -> str:
    if (settings.paddle_environment or "").lower() == "sandbox":
        return "https://sandbox-api.paddle.com"
    return "https://api.paddle.com"


def _paddle_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.paddle_api_key}",
        "Content-Type": "application/json",
        "Paddle-Version": "1",
    }


def _plan_to_price_id(plan: str) -> Optional[str]:
    if plan == "cloud":
        return settings.paddle_cloud_price_id or None
    if plan == "teams":
        return settings.paddle_teams_price_id or None
    return None


def _plan_from_price_id(price_id: str) -> str:
    if price_id and price_id == settings.paddle_cloud_price_id:
        return "cloud"
    if price_id and price_id == settings.paddle_teams_price_id:
        return "teams"
    return "free"


# ---------------------------------------------------------------------------
# Checkout — create a Paddle transaction, return id + hosted URL
# ---------------------------------------------------------------------------

class CheckoutBody(BaseModel):
    plan: str = "cloud"


@router.post("/checkout")
async def create_checkout(
    body: Optional[CheckoutBody] = None,
    token: TokenPayload = Depends(verify_token),
):
    """
    Create a Paddle transaction for the requested plan.

    Frontend opens `Paddle.Checkout.open({ transactionId })` with the returned id.
    The `url` is a hosted-checkout fallback.
    """
    if not settings.paddle_api_key:
        raise HTTPException(status_code=500, detail="Paddle not configured")

    plan = (body.plan if body else "cloud").lower()
    price_id = _plan_to_price_id(plan)
    if not price_id:
        raise HTTPException(
            status_code=400,
            detail="Unsupported plan; set PADDLE_CLOUD_PRICE_ID / PADDLE_TEAMS_PRICE_ID",
        )

    rows = await execute_query(
        "SELECT owner_email, paddle_customer_id FROM workspaces WHERE id = $1",
        str(token.workspace_id),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Workspace not found")
    owner_email = rows[0].get("owner_email")
    paddle_customer_id = rows[0].get("paddle_customer_id")

    payload: dict[str, Any] = {
        "items": [{"price_id": price_id, "quantity": 1}],
        "collection_mode": "automatic",
        "custom_data": {"workspace_id": str(token.workspace_id)},
    }
    if paddle_customer_id:
        payload["customer_id"] = paddle_customer_id
    elif owner_email:
        payload["customer"] = {"email": owner_email}

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{_paddle_base_url()}/transactions",
            headers=_paddle_headers(),
            json=payload,
        )

    if resp.status_code >= 400:
        logger.error("Paddle create transaction failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(status_code=502, detail="Failed to create checkout")

    data = resp.json().get("data", {}) or {}
    checkout = data.get("checkout") or {}
    return {
        "transaction_id": data.get("id"),
        "url": checkout.get("url"),
    }


# ---------------------------------------------------------------------------
# Webhook — HMAC-signed event stream from Paddle
# ---------------------------------------------------------------------------

def _verify_signature(header: str, raw_body: bytes, secret: str, tolerance: int = 300) -> bool:
    """Verify Paddle-Signature header (`ts=...;h1=...`) via HMAC-SHA256."""
    if not header:
        return False
    try:
        parts = dict(p.split("=", 1) for p in header.split(";"))
    except ValueError:
        return False
    ts = parts.get("ts")
    h1 = parts.get("h1")
    if not ts or not h1:
        return False
    try:
        if abs(int(time.time()) - int(ts)) > tolerance:
            return False
    except ValueError:
        return False
    signed = f"{ts}:".encode("utf-8") + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, h1)


@router.post("/webhook")
async def paddle_webhook(request: Request):
    """Handle Paddle webhook events. Auth is HMAC signature — no JWT."""
    if not settings.paddle_webhook_secret:
        raise HTTPException(status_code=500, detail="Paddle webhook secret not configured")

    sig_header = request.headers.get("paddle-signature", "")
    raw_body = await request.body()

    if not _verify_signature(sig_header, raw_body, settings.paddle_webhook_secret):
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = event.get("event_type", "")
    data = event.get("data", {}) or {}

    try:
        if event_type == "subscription.activated":
            await _handle_subscription_activated(data)
        elif event_type == "subscription.updated":
            await _handle_subscription_updated(data)
        elif event_type in ("subscription.canceled", "subscription.paused"):
            await _handle_subscription_canceled(data)
        elif event_type == "transaction.payment_failed":
            logger.warning("Payment failed for customer %s", data.get("customer_id"))
        else:
            logger.debug("Unhandled Paddle event: %s", event_type)
    except Exception:
        # Log but return 200 so Paddle doesn't retry-storm on a bug.
        logger.exception("Error handling Paddle event %s", event_type)

    return {"received": True}


async def _handle_subscription_activated(data: dict) -> None:
    """Subscription is paid and live. Upgrade workspace plan + persist IDs."""
    workspace_id = (data.get("custom_data") or {}).get("workspace_id")
    customer_id = data.get("customer_id")
    subscription_id = data.get("id")
    items = data.get("items") or []
    price_id = (items[0].get("price") or {}).get("id") if items else None
    plan = _plan_from_price_id(price_id or "")

    if not workspace_id:
        logger.warning(
            "subscription.activated missing workspace_id (custom_data): sub=%s",
            subscription_id,
        )
        return

    await execute_insert(
        """
        UPDATE workspaces
        SET plan = $1,
            paddle_customer_id = $2,
            paddle_subscription_id = $3,
            subscription_status = 'active'
        WHERE id = $4::uuid
        """,
        plan, customer_id, subscription_id, workspace_id,
    )
    logger.info(
        "Workspace %s activated on %s (customer=%s sub=%s)",
        workspace_id, plan, customer_id, subscription_id,
    )


async def _handle_subscription_updated(data: dict) -> None:
    """Plan change or renewal. Sync plan + status from the subscription."""
    subscription_id = data.get("id")
    status = data.get("status") or "active"
    items = data.get("items") or []
    price_id = (items[0].get("price") or {}).get("id") if items else None
    plan = _plan_from_price_id(price_id or "")

    await execute_insert(
        """
        UPDATE workspaces
        SET plan = $1,
            subscription_status = $2
        WHERE paddle_subscription_id = $3
        """,
        plan, status, subscription_id,
    )
    logger.info("Subscription %s updated: plan=%s status=%s", subscription_id, plan, status)


async def _handle_subscription_canceled(data: dict) -> None:
    """Subscription ended. Downgrade to free."""
    subscription_id = data.get("id")
    await execute_insert(
        """
        UPDATE workspaces
        SET plan = 'free',
            subscription_status = 'canceled'
        WHERE paddle_subscription_id = $1
        """,
        subscription_id,
    )
    logger.info("Subscription %s canceled; workspace downgraded to free", subscription_id)


# ---------------------------------------------------------------------------
# Customer portal — self-serve plan management
# ---------------------------------------------------------------------------

@router.get("/portal")
async def billing_portal(token: TokenPayload = Depends(verify_token)):
    """Create a Paddle customer portal session and return its URL."""
    if not settings.paddle_api_key:
        raise HTTPException(status_code=500, detail="Paddle not configured")

    rows = await execute_query(
        "SELECT paddle_customer_id FROM workspaces WHERE id = $1",
        str(token.workspace_id),
    )
    if not rows or not rows[0].get("paddle_customer_id"):
        raise HTTPException(
            status_code=404,
            detail="No billing information found for this workspace",
        )

    customer_id = rows[0]["paddle_customer_id"]
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{_paddle_base_url()}/customers/{customer_id}/portal-sessions",
            headers=_paddle_headers(),
            json={},
        )

    if resp.status_code >= 400:
        logger.error("Paddle portal-session failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(status_code=502, detail="Failed to create billing portal")

    data = resp.json().get("data", {}) or {}
    urls = (data.get("urls") or {}).get("general") or {}
    url = urls.get("overview")
    if not url:
        raise HTTPException(status_code=502, detail="Portal URL missing in Paddle response")
    return {"url": url}
