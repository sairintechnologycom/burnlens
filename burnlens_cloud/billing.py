"""Paddle Billing endpoints — checkout (server-side transaction), webhook, portal."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .auth import verify_token, TokenPayload
from .config import settings
from .database import execute_insert, execute_query
from .models import BillingSummary, ChangePlanBody, CancelBody

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


async def _plan_from_price_id(price_id: str) -> str:
    """Map Paddle price_id → internal plan.

    DB first (Phase 6 plan_limits.paddle_price_id, indexed via
    idx_plan_limits_paddle_price). Env fallback for safety if the seed
    hasn't run in this environment.
    """
    if not price_id:
        return "free"
    rows = await execute_query(
        "SELECT plan FROM plan_limits WHERE paddle_price_id = $1",
        price_id,
    )
    if rows:
        return rows[0]["plan"]
    # Legacy env fallback — matches pre-Phase-7 behaviour.
    if price_id == settings.paddle_cloud_price_id:
        return "cloud"
    if price_id == settings.paddle_teams_price_id:
        return "teams"
    return "free"


# ---------------------------------------------------------------------------
# Paddle payload extraction — fail-soft helpers. Return None / False on any
# KeyError / TypeError / ValueError so a malformed payload never crashes the
# handler (D-11 silent-success invariant).
# ---------------------------------------------------------------------------

def _parse_iso(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        # Paddle emits e.g. "2026-05-19T00:00:00Z" — fromisoformat handles "+00:00" after replace.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _extract_period_end(data: dict) -> Optional[datetime]:
    try:
        return _parse_iso((data.get("current_billing_period") or {}).get("ends_at"))
    except Exception:
        return None


def _extract_trial_end(data: dict) -> Optional[datetime]:
    # Populated whenever Paddle gives us trial_dates, regardless of status — the
    # Settings card only renders it for status=='trialing' (D-14 is UI concern).
    try:
        return _parse_iso((data.get("trial_dates") or {}).get("ends_at"))
    except Exception:
        return None


def _extract_cancel_at_period_end(data: dict) -> bool:
    try:
        sc = data.get("scheduled_change") or {}
        return sc.get("action") == "cancel"
    except Exception:
        return False


def _extract_price(data: dict) -> tuple[Optional[int], Optional[str]]:
    try:
        items = data.get("items") or []
        if not items:
            return (None, None)
        price = (items[0] or {}).get("price") or {}
        unit = price.get("unit_price") or {}
        amount = unit.get("amount")
        currency = unit.get("currency_code")
        cents = int(amount) if amount is not None else None
        return (cents, currency.upper() if isinstance(currency, str) else None)
    except (TypeError, ValueError):
        return (None, None)


def _extract_price_id(data: dict) -> Optional[str]:
    try:
        items = data.get("items") or []
        if not items:
            return None
        return ((items[0] or {}).get("price") or {}).get("id")
    except Exception:
        return None


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

    if not sig_header:
        # ROADMAP SC-1: signature-level failures are HTTP 401.
        raise HTTPException(status_code=401, detail="Missing signature")
    if not _verify_signature(sig_header, raw_body, settings.paddle_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_id = event.get("event_id") or event.get("id")
    event_type = event.get("event_type", "")
    data = event.get("data", {}) or {}

    if not event_id:
        # Signature passed but the envelope is malformed (no dedup key). This is a
        # client-formatting error, distinct from SC-1's signature-rejection path,
        # so it stays as 400 (per must_haves.truths[0]).
        raise HTTPException(status_code=400, detail="Missing event_id")

    # Dedup: insert-or-skip. If the INSERT returns no row, we already saw this event.
    # $3::jsonb cast — no JSONB codec registered on the asyncpg pool, so the explicit
    # cast converts the json.dumps(event) string to jsonb at the SQL layer.
    inserted = await execute_query(
        """
        INSERT INTO paddle_events (event_id, event_type, payload)
        VALUES ($1, $2, $3::jsonb)
        ON CONFLICT (event_id) DO NOTHING
        RETURNING event_id
        """,
        event_id, event_type, json.dumps(event),
    )
    if not inserted:
        return {"received": True, "deduped": True}

    try:
        if event_type == "subscription.activated":
            await _handle_subscription_activated(data)
        elif event_type == "subscription.updated":
            await _handle_subscription_updated(data)
        elif event_type in ("subscription.canceled", "subscription.paused"):
            await _handle_subscription_canceled(data)
        elif event_type == "transaction.payment_failed":
            await _handle_payment_failed(data)
        else:
            logger.debug("Unhandled Paddle event: %s", event_type)
        await execute_insert(
            "UPDATE paddle_events SET processed_at = now() WHERE event_id = $1",
            event_id,
        )
    except Exception as e:
        logger.exception("Error handling Paddle event %s", event_type)
        await execute_insert(
            "UPDATE paddle_events SET error = $1 WHERE event_id = $2",
            str(e), event_id,
        )

    return {"received": True}


async def _handle_subscription_activated(data: dict) -> None:
    """Subscription is paid and live. Upgrade workspace plan + persist IDs + period cache."""
    workspace_id = (data.get("custom_data") or {}).get("workspace_id")
    customer_id = data.get("customer_id")
    subscription_id = data.get("id")
    status = data.get("status") or "active"
    price_id = _extract_price_id(data) or ""
    plan = await _plan_from_price_id(price_id)
    trial_ends_at = _extract_trial_end(data)
    current_period_ends_at = _extract_period_end(data)
    cancel_at_period_end = _extract_cancel_at_period_end(data)
    price_cents, currency = _extract_price(data)

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
            subscription_status = $4,
            trial_ends_at = $5,
            current_period_ends_at = $6,
            cancel_at_period_end = $7,
            price_cents = $8,
            currency = $9
        WHERE id = $10::uuid
        """,
        plan, customer_id, subscription_id, status,
        trial_ends_at, current_period_ends_at, cancel_at_period_end,
        price_cents, currency,
        workspace_id,
    )
    logger.info(
        "Workspace %s activated on %s (status=%s customer=%s sub=%s)",
        workspace_id, plan, status, customer_id, subscription_id,
    )


async def _handle_subscription_updated(data: dict) -> None:
    """Plan change, renewal, or status transition (D-03)."""
    subscription_id = data.get("id")
    status = data.get("status") or "active"
    price_id = _extract_price_id(data) or ""
    plan = await _plan_from_price_id(price_id)
    trial_ends_at = _extract_trial_end(data)
    current_period_ends_at = _extract_period_end(data)
    cancel_at_period_end = _extract_cancel_at_period_end(data)
    price_cents, currency = _extract_price(data)

    await execute_insert(
        """
        UPDATE workspaces
        SET plan = $1,
            subscription_status = $2,
            trial_ends_at = $3,
            current_period_ends_at = $4,
            cancel_at_period_end = $5,
            price_cents = $6,
            currency = $7
        WHERE paddle_subscription_id = $8
        """,
        plan, status, trial_ends_at, current_period_ends_at,
        cancel_at_period_end, price_cents, currency,
        subscription_id,
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


async def _handle_payment_failed(data: dict) -> None:
    """transaction.payment_failed → flip workspace to past_due; plan unchanged (D-21).

    Paddle will retry payment automatically; a successful retry fires
    subscription.updated with status='active' and clears past_due upstream.
    """
    subscription_id = (
        data.get("subscription_id")
        or (data.get("subscription") or {}).get("id")
    )
    if not subscription_id:
        logger.warning(
            "transaction.payment_failed missing subscription_id: %s",
            data.get("id"),
        )
        return
    await execute_insert(
        """
        UPDATE workspaces
        SET subscription_status = 'past_due'
        WHERE paddle_subscription_id = $1
        """,
        subscription_id,
    )
    logger.warning("Subscription %s flipped to past_due", subscription_id)


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


# ---------------------------------------------------------------------------
# Read-only billing summary — feeds Topbar + Settings via polling (D-16..D-18)
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=BillingSummary)
async def billing_summary(token: TokenPayload = Depends(verify_token)):
    """Read the workspaces-row cache for the caller's workspace.

    Single indexed lookup; no Paddle API round-trip. Polled by the frontend
    every 30s (and on window focus) to satisfy the 60s freshness SLA (D-18).
    Workspace-scoped via verify_token (D-17) — cross-tenant reads are impossible.
    """
    rows = await execute_query(
        """
        SELECT plan, price_cents, currency, subscription_status,
               trial_ends_at, current_period_ends_at, cancel_at_period_end
        FROM workspaces
        WHERE id = $1
        """,
        str(token.workspace_id),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Workspace not found")
    row = rows[0]
    return BillingSummary(
        plan=row["plan"],
        price_cents=row["price_cents"],
        currency=row["currency"],
        status=row["subscription_status"] or "active",
        trial_ends_at=row["trial_ends_at"],
        current_period_ends_at=row["current_period_ends_at"],
        cancel_at_period_end=bool(row["cancel_at_period_end"])
            if row["cancel_at_period_end"] is not None
            else False,
    )


# ---------------------------------------------------------------------------
# Phase 8 (D-04/D-05/D-07/W1): change plan between paid tiers
# ---------------------------------------------------------------------------

_PLAN_TIER = {"free": 0, "cloud": 1, "teams": 2}


async def _load_billing_summary(workspace_id: str) -> BillingSummary:
    """Read the workspaces-row cache and shape as BillingSummary.

    Mirrors GET /billing/summary exactly so mutation endpoints
    (/change-plan, /cancel, /reactivate) can return a post-mutation
    snapshot without a second round-trip (D-22).

    W1: includes `scheduled_plan` + `scheduled_change_at` so the UI can
    render a pending-downgrade info line above the Billing action row.
    """
    rows = await execute_query(
        """
        SELECT plan, price_cents, currency, subscription_status,
               trial_ends_at, current_period_ends_at, cancel_at_period_end,
               scheduled_plan, scheduled_change_at
        FROM workspaces
        WHERE id = $1
        """,
        workspace_id,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Workspace not found")
    row = rows[0]
    return BillingSummary(
        plan=row["plan"],
        price_cents=row["price_cents"],
        currency=row["currency"],
        status=row["subscription_status"] or "active",
        trial_ends_at=row["trial_ends_at"],
        current_period_ends_at=row["current_period_ends_at"],
        cancel_at_period_end=bool(row["cancel_at_period_end"])
            if row["cancel_at_period_end"] is not None
            else False,
        scheduled_plan=row["scheduled_plan"],
        scheduled_change_at=row["scheduled_change_at"],
    )


@router.post("/change-plan", response_model=BillingSummary)
async def change_plan(
    body: ChangePlanBody,
    token: TokenPayload = Depends(verify_token),
):
    """Switch between paid plans (Cloud <-> Teams).

    D-32: only client input is `target_plan`, validated by Pydantic allowlist.
    D-33: workspace_id comes from the JWT.
    D-31: idempotent — if target_plan == current plan, return current summary, no Paddle call.
    D-04: Cloud -> Teams => proration_billing_mode='prorated_immediately'.
    D-05: Teams -> Cloud => effective_from='next_billing_period' (no proration).
    D-06: Cloud -> Free is NOT supported here; client must call /billing/cancel.
    D-20: On 2xx, write expected end-state to workspaces row synchronously.
    D-22: Response body is the fresh BillingSummary.
    D-28: On Paddle 5xx/timeout, return 502 and DO NOT mutate workspaces row.
    W1:   On downgrade 2xx, write scheduled_plan + scheduled_change_at so the UI
          can render "Pending downgrade to Cloud on {date}" without a second call.
    """
    if not settings.paddle_api_key:
        raise HTTPException(status_code=500, detail="Paddle not configured")

    workspace_id = str(token.workspace_id)
    rows = await execute_query(
        """
        SELECT plan, paddle_subscription_id, paddle_customer_id,
               current_period_ends_at
        FROM workspaces WHERE id = $1
        """,
        workspace_id,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Workspace not found")
    current_plan = (rows[0]["plan"] or "free").lower()
    subscription_id = rows[0]["paddle_subscription_id"]
    current_period_ends_at = rows[0]["current_period_ends_at"]
    target_plan = body.target_plan  # already lowercased + allowlisted by validator

    # D-31: idempotent no-op
    if current_plan == target_plan:
        return await _load_billing_summary(workspace_id)

    # D-06: Cloud -> Free is a cancel, not a change
    if target_plan == "free":
        raise HTTPException(
            status_code=400,
            detail="Downgrading to Free is a cancel. Call /billing/cancel instead.",
        )

    # Paid-to-paid requires an existing subscription
    if not subscription_id:
        raise HTTPException(
            status_code=400,
            detail="No active subscription to change. Start a new checkout via /billing/checkout.",
        )

    target_price_id = _plan_to_price_id(target_plan)
    if not target_price_id:
        raise HTTPException(
            status_code=500,
            detail=f"Missing Paddle price_id for plan '{target_plan}'",
        )

    # Build PATCH payload per direction.
    is_upgrade = _PLAN_TIER.get(target_plan, -1) > _PLAN_TIER.get(current_plan, -1)
    payload: dict[str, Any] = {
        "items": [{"price_id": target_price_id, "quantity": 1}],
    }
    if is_upgrade:
        # D-04: prorate now, switch immediately.
        payload["proration_billing_mode"] = "prorated_immediately"
    else:
        # D-05: swap at next billing period, no proration.
        payload["proration_billing_mode"] = "do_not_bill"
        payload["effective_from"] = "next_billing_period"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.patch(
                f"{_paddle_base_url()}/subscriptions/{subscription_id}",
                headers=_paddle_headers(),
                json=payload,
            )
    except (httpx.TimeoutException, httpx.TransportError) as e:
        logger.error(
            "Paddle change-plan transport failure: workspace=%s op=change-plan target=%s err=%s",
            workspace_id, target_plan, e,
        )
        raise HTTPException(status_code=502, detail="Billing provider did not respond")

    if resp.status_code >= 500:
        logger.error(
            "Paddle change-plan upstream 5xx: workspace=%s op=change-plan target=%s status=%s body=%s",
            workspace_id, target_plan, resp.status_code, resp.text,
        )
        raise HTTPException(status_code=502, detail="Billing provider error")
    if resp.status_code >= 400:
        logger.error(
            "Paddle change-plan rejected: workspace=%s op=change-plan target=%s status=%s body=%s",
            workspace_id, target_plan, resp.status_code, resp.text,
        )
        raise HTTPException(status_code=502, detail="Failed to change plan")

    # D-20: sync DB write after 2xx Paddle response.
    if is_upgrade:
        # Plan flips NOW; price_cents/currency come from next webhook (authoritative).
        # Clear any stale scheduled_plan so the UI doesn't render a pending-downgrade
        # line for a subscription that has been upgraded past it.
        await execute_insert(
            """
            UPDATE workspaces
            SET plan = $1,
                scheduled_plan = NULL,
                scheduled_change_at = NULL
            WHERE id = $2::uuid
            """,
            target_plan, workspace_id,
        )
    else:
        # W1: Downgrade — plan stays until period end. Record the scheduled state
        # so the UI can render "Pending downgrade to Cloud on {date}" immediately
        # without waiting for the webhook. `current_period_ends_at` is the
        # best-known effective date; the webhook `subscription.updated` will
        # reconcile if Paddle chose a slightly different timestamp.
        await execute_insert(
            """
            UPDATE workspaces
            SET scheduled_plan = $1,
                scheduled_change_at = $2
            WHERE id = $3::uuid
            """,
            target_plan, current_period_ends_at, workspace_id,
        )

    return await _load_billing_summary(workspace_id)


# ---------------------------------------------------------------------------
# Phase 8 (D-08/D-10/D-11): cancel-at-period-end
# ---------------------------------------------------------------------------

async def _insert_cancel_survey(
    workspace_id: str,
    plan_at_cancel: str,
    reason_code: Optional[str],
    reason_text: Optional[str],
) -> None:
    """Best-effort write of the optional cancel-reason survey row.

    Swallows ALL exceptions — D-10: cancel must never block on survey-write failure.
    """
    if reason_code is None and reason_text is None:
        return
    try:
        await execute_insert(
            """
            INSERT INTO cancellation_surveys
                (workspace_id, reason_code, reason_text, plan_at_cancel)
            VALUES ($1::uuid, $2, $3, $4)
            """,
            workspace_id, reason_code, reason_text, plan_at_cancel,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "cancellation_surveys insert failed (best-effort, ignored): workspace=%s err=%s",
            workspace_id, e,
        )


@router.post("/cancel", response_model=BillingSummary)
async def cancel_subscription(
    body: Optional[CancelBody] = None,
    token: TokenPayload = Depends(verify_token),
):
    """Cancel-at-period-end.

    D-11: Paddle POST /subscriptions/{id}/cancel with effective_from=next_billing_period.
    D-20: On 2xx, write cancel_at_period_end=true to workspaces row synchronously.
          subscription_status stays 'active' (user still has access until period end).
          plan stays as-is.
    D-22: Response body is the fresh BillingSummary.
    D-31: Idempotent — if cancel_at_period_end already true, return current summary, no Paddle call.
    D-28: Paddle 5xx/timeout -> 502 + logger.error, no DB mutation.
    D-33: workspace_id from JWT only.
    D-10: Optional survey write, best-effort, never blocks.
    """
    if not settings.paddle_api_key:
        raise HTTPException(status_code=500, detail="Paddle not configured")

    workspace_id = str(token.workspace_id)
    rows = await execute_query(
        """
        SELECT plan, paddle_subscription_id, cancel_at_period_end
        FROM workspaces WHERE id = $1
        """,
        workspace_id,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Workspace not found")
    current_plan = (rows[0]["plan"] or "free").lower()
    subscription_id = rows[0]["paddle_subscription_id"]
    already_canceled = bool(rows[0]["cancel_at_period_end"])

    # D-31 idempotent: already scheduled for cancel.
    if already_canceled:
        return await _load_billing_summary(workspace_id)

    # No active paid subscription to cancel.
    if current_plan == "free" or not subscription_id:
        raise HTTPException(
            status_code=400,
            detail="No active subscription to cancel.",
        )

    payload = {"effective_from": "next_billing_period"}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{_paddle_base_url()}/subscriptions/{subscription_id}/cancel",
                headers=_paddle_headers(),
                json=payload,
            )
    except (httpx.TimeoutException, httpx.TransportError) as e:
        logger.error(
            "Paddle cancel transport failure: workspace=%s op=cancel err=%s",
            workspace_id, e,
        )
        raise HTTPException(status_code=502, detail="Billing provider did not respond")

    if resp.status_code >= 500:
        logger.error(
            "Paddle cancel upstream 5xx: workspace=%s op=cancel status=%s body=%s",
            workspace_id, resp.status_code, resp.text,
        )
        raise HTTPException(status_code=502, detail="Billing provider error")
    if resp.status_code >= 400:
        logger.error(
            "Paddle cancel rejected: workspace=%s status=%s body=%s",
            workspace_id, resp.status_code, resp.text,
        )
        raise HTTPException(status_code=502, detail="Failed to cancel subscription")

    # D-20: write expected end-state synchronously.
    # subscription_status stays 'active' until period end; plan unchanged.
    await execute_insert(
        """
        UPDATE workspaces
        SET cancel_at_period_end = true
        WHERE id = $1::uuid
        """,
        workspace_id,
    )

    # D-10: best-effort survey write.
    reason_code = body.reason_code if body else None
    reason_text = body.reason_text if body else None
    await _insert_cancel_survey(workspace_id, current_plan, reason_code, reason_text)

    return await _load_billing_summary(workspace_id)


# ---------------------------------------------------------------------------
# Phase 8 (D-13/D-14/D-15): reactivate a canceled-but-not-ended subscription
# ---------------------------------------------------------------------------


@router.post("/reactivate", response_model=BillingSummary)
async def reactivate_subscription(
    token: TokenPayload = Depends(verify_token),
):
    """Remove a scheduled cancel.

    D-13: Paddle PATCH /subscriptions/{id} with scheduled_change=null.
    D-15: If the period has already ended (cancel materialized), return 400 —
          user must re-checkout. We do NOT secretly do fresh checkout.
    D-31: Idempotent — if nothing is scheduled, return current summary, no Paddle call.
    D-20: On 2xx, flip cancel_at_period_end=false synchronously.
    D-22: Response body is the fresh BillingSummary.
    D-28: Paddle 5xx/timeout -> 502 + logger.error.
    D-33: workspace_id from JWT.
    """
    if not settings.paddle_api_key:
        raise HTTPException(status_code=500, detail="Paddle not configured")

    workspace_id = str(token.workspace_id)
    rows = await execute_query(
        """
        SELECT plan, paddle_subscription_id, cancel_at_period_end,
               current_period_ends_at, subscription_status
        FROM workspaces WHERE id = $1
        """,
        workspace_id,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Workspace not found")

    subscription_id = rows[0]["paddle_subscription_id"]
    is_canceled = bool(rows[0]["cancel_at_period_end"])
    period_ends_at = rows[0]["current_period_ends_at"]
    status_str = (rows[0]["subscription_status"] or "").lower()

    # D-31 idempotent: nothing scheduled.
    if not is_canceled:
        return await _load_billing_summary(workspace_id)

    # D-15: period already ended — Paddle will reject reactivate; return 400.
    now = datetime.now(timezone.utc)  # uses module-level imports (Edit A)
    if status_str == "canceled" or (period_ends_at is not None and period_ends_at <= now):
        raise HTTPException(
            status_code=400,
            detail="Subscription period has ended. Start a new checkout instead.",
        )

    if not subscription_id:
        raise HTTPException(
            status_code=400,
            detail="No subscription to reactivate.",
        )

    payload = {"scheduled_change": None}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.patch(
                f"{_paddle_base_url()}/subscriptions/{subscription_id}",
                headers=_paddle_headers(),
                json=payload,
            )
    except (httpx.TimeoutException, httpx.TransportError) as e:
        logger.error(
            "Paddle reactivate transport failure: workspace=%s op=reactivate err=%s",
            workspace_id, e,
        )
        raise HTTPException(status_code=502, detail="Billing provider did not respond")

    if resp.status_code >= 500:
        logger.error(
            "Paddle reactivate upstream 5xx: workspace=%s op=reactivate status=%s body=%s",
            workspace_id, resp.status_code, resp.text,
        )
        raise HTTPException(status_code=502, detail="Billing provider error")
    if resp.status_code >= 400:
        logger.error(
            "Paddle reactivate rejected: workspace=%s status=%s body=%s",
            workspace_id, resp.status_code, resp.text,
        )
        raise HTTPException(status_code=502, detail="Failed to reactivate subscription")

    # D-20: write expected end-state synchronously.
    await execute_insert(
        """
        UPDATE workspaces
        SET cancel_at_period_end = false
        WHERE id = $1::uuid
        """,
        workspace_id,
    )

    return await _load_billing_summary(workspace_id)
