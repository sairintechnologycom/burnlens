"""Email utilities for BurnLens Cloud."""

import html as _html
import logging
import asyncio
import smtplib
import urllib.parse
from pathlib import Path
from typing import Optional, TypedDict
# NOTE: this module is itself named `email`, but Python 3 absolute imports mean
# `email.message` resolves to the stdlib package, not to us. Relative imports
# require an explicit dot.
from email.message import EmailMessage
from .config import settings
from .database import execute_query
from .pii_crypto import decrypt_pii

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "emails" / "templates"


class TemplateSpec(TypedDict):
    subject: str
    template_file: str
    required_vars: list[str]


TEMPLATE_REGISTRY: dict[str, TemplateSpec] = {
    "welcome": {
        "subject": "Welcome to BurnLens",
        "template_file": "welcome.html",
        "required_vars": ["workspace_name"],
    },
    "verify_email": {
        "subject": "Verify your BurnLens email address",
        "template_file": "verify_email.html",
        "required_vars": ["verify_url"],
    },
    "password_changed": {
        "subject": "Your BurnLens password has been changed",
        "template_file": "password_changed.html",
        "required_vars": [],
    },
    "reset_password": {
        "subject": "Reset your BurnLens password",
        "template_file": "reset_password.html",
        "required_vars": ["reset_url"],
    },
    "payment_receipt": {
        "subject": "BurnLens payment receipt",
        "template_file": "payment_receipt.html",
        "required_vars": ["workspace_name", "amount_str", "plan_name"],
    },
    "invitation": {
        "subject": "You've been invited to {{workspace_name}} on BurnLens",
        "template_file": "invitation.html",
        "required_vars": ["workspace_name", "invited_by_intro", "invite_url"],
    },
}

# WR-03: Module-level registry for outstanding fire-and-forget email tasks.
# asyncio.create_task returns a reference the event loop holds weakly; without
# a strong reference, the GC may drop a scheduled task mid-flight. Keeping the
# task in this set (and discarding on completion) ensures the coroutine runs
# to completion, and lets the FastAPI lifespan shutdown wait briefly on the
# outstanding set before cancelling. Call track_email_task() to register.
_pending_email_tasks: "set[asyncio.Task]" = set()


def mail_configured() -> bool:
    """Whether outbound email can be sent at all.

    Every sender checks this and no-ops when false. That is deliberately
    fail-open — a dead mail provider must never break signup or billing — but
    it also means a missing credential is invisible, which is how production
    ran with no email configured at all. `main.py` logs a startup banner when
    this is false so the condition is at least stated once per boot.
    """
    return bool(settings.smtp_password)


def _smtp_send(recipient_email: str, subject: str, html_body: str) -> None:
    """Deliver one HTML email over SMTP. Blocking — call via asyncio.to_thread.

    Provider-agnostic: works with Resend, Brevo, SES, Postmark. STARTTLS on the
    submission port is the common denominator; the implicit-TLS port (465)
    would need SMTP_SSL instead.
    """
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = recipient_email
    msg["Subject"] = subject
    # Multipart alternative: text part first, HTML second. A bare HTML body
    # scores badly with spam filters and breaks text-only clients.
    msg.set_content("This email requires an HTML-capable client to display.")
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
        server.starttls()
        server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)


def deliver(recipient_email: str, subject: str, html_body: str, what: str) -> bool:
    """Queue an email for background delivery. Fail-open — never raises.

    Returns True when the send was queued, False when email is unconfigured.
    A True return means queued, not delivered: SMTP failures surface in the
    logs from the background task, not here.
    """
    if not mail_configured():
        logger.warning("%s: email not configured (SMTP_PASSWORD unset), skipping", what)
        return False

    async def _send_background() -> None:
        try:
            await asyncio.to_thread(_smtp_send, recipient_email, subject, html_body)
            logger.info("%s: sent to %s", what, recipient_email)
        except Exception:
            logger.exception("%s: failed for %s", what, recipient_email)

    track_email_task(asyncio.create_task(_send_background()))
    return True


async def deliver_now(recipient_email: str, subject: str, html_body: str, what: str) -> bool:
    """Deliver one email and report the real outcome. Fail-open — never raises.

    The awaited counterpart to `deliver`. True here means the mail provider
    accepted the message, not that a background task was queued — so a caller
    can return a count someone is willing to trust.

    Use from cron jobs only. `deliver` exists because request handlers must not
    wait on an SMTP handshake; a weekly job has no such latency to protect, and
    a queued-but-failed send is invisible unless the log tail happens to still
    hold the line.
    """
    if not mail_configured():
        logger.warning("%s: email not configured (SMTP_PASSWORD unset), skipping", what)
        return False

    try:
        await asyncio.to_thread(_smtp_send, recipient_email, subject, html_body)
        logger.info("%s: delivered to %s", what, recipient_email)
        return True
    except Exception:
        logger.exception("%s: delivery failed for %s", what, recipient_email)
        return False


def track_email_task(task: "asyncio.Task") -> "asyncio.Task":
    """Register a fire-and-forget email task so the event loop retains it.

    Returns the same task for call-site convenience:
      task = track_email_task(asyncio.create_task(_send_background()))
    """
    _pending_email_tasks.add(task)
    task.add_done_callback(_pending_email_tasks.discard)
    return task


async def drain_pending_email_tasks(timeout: float = 5.0) -> None:
    """Wait up to `timeout` seconds for outstanding email tasks to finish.

    Called from the FastAPI lifespan shutdown so in-flight SMTP sends
    have a grace period to complete before the process exits. Any tasks
    still pending after the timeout are left to whatever cleanup the event
    loop performs during shutdown (typically cancellation).
    """
    if not _pending_email_tasks:
        return
    try:
        await asyncio.wait(
            set(_pending_email_tasks), timeout=timeout
        )
    except Exception as exc:  # pragma: no cover — best-effort drain
        logger.warning("drain_pending_email_tasks error: %s", exc)


async def send_invitation_email(
    recipient_email: str,
    workspace_name: str,
    invitation_token: str,
    invited_by_name: Optional[str] = None,
) -> bool:
    """
    Send invitation email asynchronously.

    Args:
        recipient_email: Email address of invitee
        workspace_name: Name of workspace
        invitation_token: Token for accepting invitation
        invited_by_name: Name of person who invited (optional)

    Returns:
        True if email sent successfully, False otherwise
    """
    if not mail_configured():
        logger.warning("send_invitation_email: email not configured, skipping")
        return False

    try:
        # HTML-escape user-supplied values and render via the template system
        # (WR-05 / CR-04) so invitation emails are consistent with other senders
        # and XSS payloads in user-supplied fields are neutralised before
        # reaching the HTML body.
        safe_workspace = _html.escape(workspace_name)
        safe_inviter = _html.escape(invited_by_name) if invited_by_name else None
        invited_by_intro = (
            f"<strong>{safe_inviter}</strong> has invited you to join"
            if safe_inviter
            else "You've been invited to join"
        )
        # Build invitation link; quote for safety in href context.
        raw_invite_url = f"{settings.burnlens_frontend_url}/invite/{invitation_token}"
        safe_url = urllib.parse.quote(raw_invite_url, safe=":/?=&")

        spec = TEMPLATE_REGISTRY["invitation"]
        template = (_TEMPLATE_DIR / spec["template_file"]).read_text(encoding="utf-8")
        html_content = (
            template
            .replace("{{workspace_name}}", safe_workspace)
            .replace("{{invited_by_intro}}", invited_by_intro)
            .replace("{{invite_url}}", safe_url)
        )
        # Resolve dynamic subject (spec subject also uses a placeholder).
        subject = spec["subject"].replace("{{workspace_name}}", safe_workspace)

        return deliver(recipient_email, subject, html_content, "send_invitation_email")

    except Exception as e:
        logger.error(f"Error preparing invitation email: {e}")
        return False


async def send_usage_warning_email(
    workspace_id: str,
    threshold: str,             # "80" or "100"
    current: int,
    limit: int,
    cycle_end_date: str,        # pre-formatted "Month D, YYYY"
    plan_label: str,            # e.g. "Cloud", "Teams", "Free"
) -> bool:
    """Send the 80% or 100% quota warning email to the workspace owner.

    Returns False and logs a warning on any failure — never raises. This is a
    fire-and-forget SMTP send invoked from the ingest hot path (see D-08).
    """
    # Fail-open: no mail configuration -> nothing to do.
    if not mail_configured():
        logger.warning(
            "send_usage_warning_email: email not configured, skipping for workspace=%s",
            workspace_id,
        )
        return False

    # Threshold guard: blocks any path-traversal via threshold string (T-09-08).
    if threshold not in ("80", "100"):
        logger.warning(
            "send_usage_warning_email: invalid threshold=%r for workspace=%s (expected '80' or '100')",
            threshold,
            workspace_id,
        )
        return False

    try:
        # Resolve recipient: owner of the workspace via workspace_members join.
        rows = await execute_query(
            """
            SELECT u.email_encrypted
            FROM workspace_members wm
            JOIN users u ON u.id = wm.user_id
            WHERE wm.workspace_id = $1
              AND wm.role = 'owner'
              AND wm.active = true
            LIMIT 1
            """,
            workspace_id,
        )
        if not rows:
            logger.warning(
                "send_usage_warning_email: no active owner found for workspace=%s",
                workspace_id,
            )
            return False

        encrypted_email = rows[0].get("email_encrypted") if hasattr(rows[0], "get") else rows[0]["email_encrypted"]
        if not encrypted_email:
            logger.warning(
                "send_usage_warning_email: owner has no email_encrypted for workspace=%s",
                workspace_id,
            )
            return False

        try:
            recipient_email = decrypt_pii(encrypted_email)
        except Exception as e:
            logger.warning(
                "send_usage_warning_email: decrypt_pii failed for workspace=%s: %s",
                workspace_id,
                e,
            )
            return False

        if not recipient_email:
            logger.warning(
                "send_usage_warning_email: decrypted owner email is empty for workspace=%s",
                workspace_id,
            )
            return False

        # Load template from disk (single read per call — ~1KB, T-09-10 accepted).
        template_path = _TEMPLATE_DIR / f"usage_{threshold}_percent.html"
        try:
            template = template_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(
                "send_usage_warning_email: failed to read template %s: %s",
                template_path,
                e,
            )
            return False

        upgrade_url = f"{settings.burnlens_frontend_url}/settings#billing"
        html_content = template.format(
            plan_label=plan_label,
            current=current,
            limit=limit,
            cycle_end_date=cycle_end_date,
            upgrade_url=upgrade_url,
        )

        subject = (
            "Heads up: 80% of your BurnLens quota used"
            if threshold == "80"
            else "You've hit your BurnLens monthly cap"
        )

        return deliver(
            recipient_email,
            subject,
            html_content,
            f"send_usage_warning_email(threshold={threshold}%, workspace={workspace_id})",
        )

    except Exception as e:
        logger.error(
            "Error preparing usage warning email for workspace=%s: %s",
            workspace_id,
            e,
        )
        return False


def _render(template_key: str, **replacements: str) -> tuple[str, str]:
    """Render a registry template to (subject, html). Placeholders are literal
    `{{name}}` markers — callers escape any user-supplied value first."""
    spec = TEMPLATE_REGISTRY[template_key]
    html_body = (_TEMPLATE_DIR / spec["template_file"]).read_text(encoding="utf-8")
    subject = spec["subject"]
    for key, value in replacements.items():
        html_body = html_body.replace(f"{{{{{key}}}}}", value)
        subject = subject.replace(f"{{{{{key}}}}}", value)
    return subject, html_body


async def send_welcome_email(recipient_email: str, workspace_name: str) -> None:
    """Send welcome email to new user. Fail-open — never raises."""
    subject, html_body = _render("welcome", workspace_name=_html.escape(workspace_name))
    deliver(recipient_email, subject, html_body, "send_welcome_email")


async def send_verify_email(recipient_email: str, verify_url: str) -> None:
    """Send email-verification link. Fail-open — never raises."""
    subject, html_body = _render("verify_email", verify_url=verify_url)
    deliver(recipient_email, subject, html_body, "send_verify_email")


async def send_password_changed_email(recipient_email: str) -> None:
    """Notify user their password was changed. Fail-open — never raises."""
    subject, html_body = _render("password_changed")
    deliver(recipient_email, subject, html_body, "send_password_changed_email")


async def send_reset_password_email(recipient_email: str, reset_url: str) -> None:
    """Send password-reset link email. Fail-open — never raises."""
    subject, html_body = _render("reset_password", reset_url=reset_url)
    deliver(recipient_email, subject, html_body, "send_reset_password_email")


async def send_payment_receipt_email(
    recipient_email: str,
    workspace_name: str,
    amount_str: str,
    plan_name: str,
) -> None:
    """Send payment receipt after successful Paddle transaction. Fail-open — never raises."""
    subject, html_body = _render(
        "payment_receipt",
        workspace_name=_html.escape(workspace_name),
        amount_str=_html.escape(amount_str),
        plan_name=_html.escape(plan_name),
    )
    deliver(recipient_email, subject, html_body, "send_payment_receipt_email")


async def send_ops_alert(subject: str, body: str) -> None:
    """Email the operator about an infrastructure problem. Fail-open — never raises.

    No template: these are rare, operator-facing, and must not depend on the
    template registry staying in sync. Falls back to a CRITICAL log when
    OPS_ALERT_EMAIL or SMTP is unconfigured, so the signal is never lost
    entirely.
    """
    logger.critical("OPS ALERT: %s — %s", subject, body)
    if not settings.ops_alert_email:
        return

    html_body = f"<h2>{_html.escape(subject)}</h2><pre>{_html.escape(body)}</pre>"
    deliver(
        settings.ops_alert_email,
        f"[BurnLens ops] {subject}",
        html_body,
        "send_ops_alert",
    )
