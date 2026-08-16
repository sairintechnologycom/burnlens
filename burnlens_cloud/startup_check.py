"""Startup credential inventory — state what is wired up, once per boot.

Three production outages in one day traced to the same shape: a feature fully
built, merged and tested, but inert in production because a credential was
never set or had silently lapsed. Every one of them was fail-open by design
(a dead mail provider must not break signup), so nothing ever complained.

- Paddle API key expired 2026-07-16 → checkout 502'd for every customer for
  three weeks. The key was PRESENT the whole time, which is why presence
  checks alone are not enough.
- Paddle webhook was not subscribed to `subscription.trialing` or
  `transaction.completed`.
- No mail provider was configured at all → password reset returned 200 and
  sent nothing, locking users out with no recovery path.

This module does two things at boot:

1. Logs an inventory of every external credential: configured or not, and what
   breaks when it isn't. Presence only — cheap, no network.
2. Probes Paddle for liveness, because presence was the exact thing that lied.
3. Probes the webhook secret for *agreement* with Paddle. Same lesson, worse
   symptom: a mismatched signing secret makes `/billing/webhook` 401 every real
   event, so a customer who paid silently stays on the free plan.

It never blocks or fails startup. A crashlooping API is worse than a degraded
one, and Railway would restart it forever.
"""

import asyncio
import hmac
import logging
from typing import Callable, NamedTuple

import httpx

from .config import settings

logger = logging.getLogger(__name__)


class Credential(NamedTuple):
    name: str            # env var name
    configured: Callable[[], bool]
    breaks: str          # what stops working when unset
    required: bool       # True = the service is meaningfully broken without it


# Ordered roughly by blast radius. `breaks` is written for whoever reads this
# log at 3am, so it names the user-visible symptom, not the subsystem.
CREDENTIALS: list[Credential] = [
    Credential("DATABASE_URL", lambda: bool(settings.database_url), "everything", True),
    Credential("JWT_SECRET", lambda: bool(settings.jwt_secret), "all authentication", True),
    Credential("PII_MASTER_KEY", lambda: _pii_configured(),
               "signup, login, any PII read/write", True),
    Credential("PADDLE_API_KEY", lambda: bool(settings.paddle_api_key),
               "checkout, plan changes, cancellation (502 to customers)", True),
    Credential("PADDLE_WEBHOOK_SECRET", lambda: bool(settings.paddle_webhook_secret),
               "plan flips after payment — subscribers stay on free", True),
    Credential("PADDLE_CLOUD_PRICE_ID", lambda: bool(settings.paddle_cloud_price_id),
               "Cloud plan checkout", True),
    Credential("PADDLE_TEAMS_PRICE_ID", lambda: bool(settings.paddle_teams_price_id),
               "Teams plan checkout", True),
    Credential("SMTP_PASSWORD", lambda: bool(settings.smtp_password),
               "password reset (permanent lockout), invitations, receipts", True),
    Credential("OPS_ALERT_EMAIL", lambda: bool(settings.ops_alert_email),
               "operator alerts — credential expiry goes unnoticed", False),
    Credential("CRON_SECRET", lambda: bool(settings.cron_secret),
               "scheduled job authentication", False),
    Credential("PADDLE_CLOUD_ANNUAL_PRICE_ID", lambda: bool(settings.paddle_cloud_annual_price_id),
               "annual Cloud checkout", False),
    Credential("PADDLE_TEAMS_ANNUAL_PRICE_ID", lambda: bool(settings.paddle_teams_annual_price_id),
               "annual Teams checkout", False),
    Credential("OTEL_ENCRYPTION_KEY", lambda: bool(settings.otel_encryption_key),
               "OTEL exporter credentials and reconciliation billing keys "
               "(503 on save, daily reconciliation stops)", False),
]


def _pii_configured() -> bool:
    """PII_MASTER_KEY is validated inside pii_crypto, not exposed on settings."""
    import os
    return bool(os.getenv("PII_MASTER_KEY", "").strip())


def log_credential_inventory() -> None:
    """Log the full credential inventory. Never raises."""
    missing_required, missing_optional = [], []
    for cred in CREDENTIALS:
        try:
            ok = cred.configured()
        except Exception:  # a broken predicate must not take down boot
            ok = False
        if not ok:
            (missing_required if cred.required else missing_optional).append(cred)

    total = len(CREDENTIALS)
    logger.info(
        "Credential inventory: %d/%d configured (env=%s, paddle=%s, mail_from=%s)",
        total - len(missing_required) - len(missing_optional), total,
        settings.environment, settings.paddle_environment, settings.mail_from,
    )
    for cred in missing_required:
        logger.error("  MISSING (required) %s — breaks: %s", cred.name, cred.breaks)
    for cred in missing_optional:
        logger.warning("  missing (optional) %s — breaks: %s", cred.name, cred.breaks)
    if not missing_required and not missing_optional:
        logger.info("  all credentials present")


async def probe_paddle() -> bool:
    """Verify the Paddle key actually works — presence is not validity.

    An expired Paddle key returns 403 on every endpoint, reads included, which
    reads exactly like a permissions problem. `GET /prices` is the cheapest
    call that distinguishes a live key from a dead one.

    Returns True when the key works. Never raises; a Paddle outage must not
    affect our boot.
    """
    if not settings.paddle_api_key:
        return False

    base = (
        "https://sandbox-api.paddle.com"
        if settings.paddle_environment == "sandbox"
        else "https://api.paddle.com"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{base}/prices?per_page=1",
                headers={"Authorization": f"Bearer {settings.paddle_api_key}"},
            )
    except Exception as exc:
        # Network trouble is not proof the key is bad — say so and move on.
        logger.warning("Paddle liveness probe inconclusive (transport): %s", exc)
        return False

    if resp.status_code == 200:
        logger.info("Paddle credential OK (%s)", settings.paddle_environment)
        return True

    from .email import send_ops_alert
    await send_ops_alert(
        "Paddle API key is not working",
        f"GET {base}/prices returned {resp.status_code}.\n\n"
        f"Checkout is DOWN: POST /billing/checkout will return 502 and no "
        f"customer can subscribe.\n\n"
        f"A 403 on a plain read means the key is expired or revoked, not that "
        f"it lacks scopes. Create a replacement with transaction/subscription/"
        f"customer read+write and set PADDLE_API_KEY on burnlens-proxy.",
    )
    return False


async def probe_webhook_secret() -> bool:
    """Verify PADDLE_WEBHOOK_SECRET is the secret Paddle actually signs with.

    The inventory above only proves the secret is PRESENT — the same weakness
    that let a dead API key report healthy for three weeks. A webhook secret is
    worse in one way: the API key fails loudly (checkout 502s), while a
    mismatched webhook secret fails *silently*. Paddle signs with the real
    secret, `_verify_signature` rejects it, `/billing/webhook` returns 401, and
    the customer who just paid sits on the free plan. Nothing else notices.

    This is easy to hit because a destination's secret and the env var are
    rotated in separate places: regenerate one and forget the other and the two
    drift with no error anywhere.

    Returns True only when the configured secret matches an ACTIVE url
    destination. Never raises.
    """
    if not settings.paddle_webhook_secret:
        return False  # the inventory has already reported this

    base = (
        "https://sandbox-api.paddle.com"
        if settings.paddle_environment == "sandbox"
        else "https://api.paddle.com"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{base}/notification-settings?per_page=200",
                headers={"Authorization": f"Bearer {settings.paddle_api_key}"},
            )
    except Exception as exc:
        logger.warning("Paddle webhook probe inconclusive (transport): %s", exc)
        return False

    if resp.status_code != 200:
        logger.warning(
            "Paddle webhook probe inconclusive: GET /notification-settings "
            "returned %s", resp.status_code,
        )
        return False

    try:
        payload = resp.json()
    except ValueError as exc:
        logger.warning("Paddle webhook probe inconclusive (bad JSON): %s", exc)
        return False

    destinations = payload.get("data") or payload.get("notification-settings") or []
    ours = settings.paddle_webhook_secret

    def _matches(dest: dict) -> bool:
        # compare_digest over the raw secret — constant time, and the secret
        # itself never reaches a log line or an alert body.
        return hmac.compare_digest(str(dest.get("endpoint_secret_key") or ""), ours)

    active = [d for d in destinations if d.get("active") and d.get("type") == "url"]
    for dest in active:
        if _matches(dest):
            logger.info(
                "Paddle webhook secret matches active destination %s (%s)",
                dest.get("id"), dest.get("description"),
            )
            return True

    # No active destination signs with our secret. Say which one it DOES match
    # if any — "you kept the secret of a destination you disabled" is by far
    # the most likely way to get here, and naming it saves the investigation.
    stale = [d.get("id") for d in destinations if not d.get("active") and _matches(d)]
    detail = (
        f"It matches DISABLED destination {stale[0]} — that destination no "
        f"longer receives events, so every real webhook will 401."
        if stale else
        "It matches no destination at all, active or disabled."
    )
    active_ids = ", ".join(str(d.get("id")) for d in active) or "none"
    from .email import send_ops_alert
    await send_ops_alert(
        "Paddle webhook secret does not match Paddle",
        f"PADDLE_WEBHOOK_SECRET does not match any active notification "
        f"destination.\n\n{detail}\n\n"
        f"Nothing will look broken: POST /billing/webhook returns 401, Paddle "
        f"records a failed delivery, and a customer who just paid STAYS ON THE "
        f"FREE PLAN. There is no other symptom.\n\n"
        f"Active url destinations: {active_ids}\n\n"
        f"Fix: copy the signing secret from the active destination in Paddle > "
        f"Developer tools > Notifications and set PADDLE_WEBHOOK_SECRET on "
        f"burnlens-proxy. Paddle retains notifications for 90 days and can "
        f"replay them, and /billing/webhook dedups on event_id, so anything "
        f"rejected meanwhile can be replayed safely once the secret is fixed.",
    )
    return False


def schedule_startup_checks() -> "asyncio.Task":
    """Run the inventory now and the liveness probes in the background.

    The probes are detached so a slow or unreachable Paddle cannot delay boot;
    Railway health checks would kill the deploy long before a 15s timeout.
    """
    log_credential_inventory()
    return asyncio.create_task(_run_probes())


async def _run_probes() -> None:
    """Paddle probes, in order. Never raises.

    The webhook probe only runs once the key is known good: it authenticates
    with the same key, so a dead key would make it fail too and emit a second
    alert blaming the wrong credential.
    """
    if await probe_paddle():
        await probe_webhook_secret()
