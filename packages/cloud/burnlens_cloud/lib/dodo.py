"""Dodo Payments integration — test shim in development, real API in production."""

import httpx

from burnlens_cloud.config import settings

DODO_API_BASE = "https://api.dodopayments.com"


async def create_checkout(org_id: str, tier: str) -> str:
    """Create a checkout session and return the checkout URL.

    In development mode, returns a local test-upgrade URL
    without making any real HTTP calls.
    """
    if settings.environment == "development":
        return f"http://localhost:8000/api/v1/billing/test-upgrade?org_id={org_id}&tier={tier}"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{DODO_API_BASE}/v1/checkout/sessions",
            headers={
                "Authorization": f"Bearer {settings.dodo_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "product_id": f"burnlens_{tier}",
                "metadata": {"org_id": org_id, "tier": tier},
                "success_url": f"https://app.burnlens.dev/settings?upgraded={tier}",
                "cancel_url": "https://app.burnlens.dev/settings",
            },
        )
        resp.raise_for_status()
        return resp.json()["url"]


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify Dodo webhook signature.

    In development mode, always returns True.
    """
    if settings.environment == "development":
        return True

    import hashlib
    import hmac

    expected = hmac.new(
        settings.dodo_webhook_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
