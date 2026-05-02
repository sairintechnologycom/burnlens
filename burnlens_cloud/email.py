"""Email utilities for BurnLens Cloud."""

import html as _html
import logging
import asyncio
import urllib.parse
from pathlib import Path
from typing import Optional, TypedDict
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content
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

    Called from the FastAPI lifespan shutdown so in-flight SendGrid POSTs
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
    if not settings.sendgrid_api_key:
        logger.warning("SendGrid API key not configured, skipping email send")
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

        # Create email
        message = Mail(
            from_email=Email(settings.sendgrid_from_email),
            to_emails=To(recipient_email),
            subject=subject,
            html_content=Content("text/html", html_content),
        )

        # Send email asynchronously (fire and forget)
        def _send():
            try:
                sg = SendGridAPIClient(settings.sendgrid_api_key)
                sg.send(message)
                logger.info(f"Invitation email sent to {recipient_email}")
                return True
            except Exception as e:
                logger.error(f"Failed to send invitation email to {recipient_email}: {e}")
                return False

        async def _send_background():
            """Send email in background."""
            await asyncio.to_thread(_send)

        # Run in background task (non-blocking). Register with track_email_task
        # so the lifespan shutdown drain covers invitation sends too.
        track_email_task(asyncio.create_task(_send_background()))

        return True

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
    # Fail-open: no SendGrid configuration -> nothing to do.
    if not settings.sendgrid_api_key:
        logger.warning(
            "SendGrid API key not configured, skipping usage warning email for workspace=%s",
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

        message = Mail(
            from_email=Email(settings.sendgrid_from_email),
            to_emails=To(recipient_email),
            subject=subject,
            html_content=Content("text/html", html_content),
        )

        def _send():
            try:
                sg = SendGridAPIClient(settings.sendgrid_api_key)
                sg.send(message)
                logger.info(
                    "Usage warning email sent (threshold=%s%%) for workspace=%s",
                    threshold,
                    workspace_id,
                )
                return True
            except Exception as e:
                logger.error(
                    "Failed to send usage warning email (threshold=%s%%) for workspace=%s: %s",
                    threshold,
                    workspace_id,
                    e,
                )
                return False

        # Define background wrapper BEFORE scheduling — avoids the NameError trap
        # present in send_invitation_email's analog.
        async def _send_background():
            """Send email in background thread, off the ingest hot path."""
            await asyncio.to_thread(_send)

        # WR-03: register with module-level set so the task is not dropped
        # by GC and the lifespan shutdown can drain outstanding sends.
        track_email_task(asyncio.create_task(_send_background()))
        return True

    except Exception as e:
        logger.error(
            "Error preparing usage warning email for workspace=%s: %s",
            workspace_id,
            e,
        )
        return False


async def send_welcome_email(recipient_email: str, workspace_name: str) -> None:
    """Send welcome email to new user. Fail-open — never raises."""
    if not settings.sendgrid_api_key:
        logger.warning("send_welcome_email: SendGrid not configured, skipping")
        return

    async def _send_background() -> None:
        try:
            spec = TEMPLATE_REGISTRY["welcome"]
            template = (_TEMPLATE_DIR / spec["template_file"]).read_text(encoding="utf-8")
            html_body = template.replace("{{workspace_name}}", _html.escape(workspace_name))
            message = Mail(
                from_email=Email(settings.sendgrid_from_email),
                to_emails=[To(recipient_email)],
                subject=spec["subject"],
                html_content=Content("text/html", html_body),
            )
            sg = SendGridAPIClient(settings.sendgrid_api_key)
            sg.send(message)
        except Exception:
            logger.exception("send_welcome_email: failed for %s", recipient_email)

    track_email_task(asyncio.create_task(_send_background()))


async def send_verify_email(recipient_email: str, verify_url: str) -> None:
    """Send email-verification link. Fail-open — never raises."""
    if not settings.sendgrid_api_key:
        logger.warning("send_verify_email: SendGrid not configured, skipping")
        return

    async def _send_background() -> None:
        try:
            spec = TEMPLATE_REGISTRY["verify_email"]
            template = (_TEMPLATE_DIR / spec["template_file"]).read_text(encoding="utf-8")
            html_body = template.replace("{{verify_url}}", verify_url)
            message = Mail(
                from_email=Email(settings.sendgrid_from_email),
                to_emails=[To(recipient_email)],
                subject=spec["subject"],
                html_content=Content("text/html", html_body),
            )
            sg = SendGridAPIClient(settings.sendgrid_api_key)
            sg.send(message)
        except Exception:
            logger.exception("send_verify_email: failed for %s", recipient_email)

    track_email_task(asyncio.create_task(_send_background()))


async def send_password_changed_email(recipient_email: str) -> None:
    """Notify user their password was changed. Fail-open — never raises."""
    if not settings.sendgrid_api_key:
        logger.warning("send_password_changed_email: SendGrid not configured, skipping")
        return

    async def _send_background() -> None:
        try:
            spec = TEMPLATE_REGISTRY["password_changed"]
            template = (_TEMPLATE_DIR / spec["template_file"]).read_text(encoding="utf-8")
            message = Mail(
                from_email=Email(settings.sendgrid_from_email),
                to_emails=[To(recipient_email)],
                subject=spec["subject"],
                html_content=Content("text/html", template),
            )
            sg = SendGridAPIClient(settings.sendgrid_api_key)
            sg.send(message)
        except Exception:
            logger.exception("send_password_changed_email: failed for %s", recipient_email)

    track_email_task(asyncio.create_task(_send_background()))


async def send_reset_password_email(recipient_email: str, reset_url: str) -> None:
    """Send password-reset link email. Fail-open — never raises."""
    if not settings.sendgrid_api_key:
        logger.warning("send_reset_password_email: SendGrid not configured, skipping")
        return

    async def _send_background() -> None:
        try:
            spec = TEMPLATE_REGISTRY["reset_password"]
            template = (_TEMPLATE_DIR / spec["template_file"]).read_text(encoding="utf-8")
            html_body = template.replace("{{reset_url}}", reset_url)
            message = Mail(
                from_email=Email(settings.sendgrid_from_email),
                to_emails=[To(recipient_email)],
                subject=spec["subject"],
                html_content=Content("text/html", html_body),
            )
            sg = SendGridAPIClient(settings.sendgrid_api_key)
            sg.send(message)
        except Exception:
            logger.exception("send_reset_password_email: failed for %s", recipient_email)

    track_email_task(asyncio.create_task(_send_background()))


async def send_payment_receipt_email(
    recipient_email: str,
    workspace_name: str,
    amount_str: str,
    plan_name: str,
) -> None:
    """Send payment receipt after successful Paddle transaction. Fail-open — never raises."""
    if not settings.sendgrid_api_key:
        logger.warning("send_payment_receipt_email: SendGrid not configured, skipping")
        return

    async def _send_background() -> None:
        try:
            spec = TEMPLATE_REGISTRY["payment_receipt"]
            template = (_TEMPLATE_DIR / spec["template_file"]).read_text(encoding="utf-8")
            html_body = (
                template
                .replace("{{workspace_name}}", _html.escape(workspace_name))
                .replace("{{amount_str}}", _html.escape(amount_str))
                .replace("{{plan_name}}", _html.escape(plan_name))
            )
            message = Mail(
                from_email=Email(settings.sendgrid_from_email),
                to_emails=[To(recipient_email)],
                subject=spec["subject"],
                html_content=Content("text/html", html_body),
            )
            sg = SendGridAPIClient(settings.sendgrid_api_key)
            sg.send(message)
        except Exception:
            logger.exception("send_payment_receipt_email: failed for %s", recipient_email)

    track_email_task(asyncio.create_task(_send_background()))
