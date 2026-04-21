"""Email utilities for BurnLens Cloud."""

import logging
import asyncio
from pathlib import Path
from typing import Optional
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content
from .config import settings
from .database import execute_query
from .pii_crypto import decrypt_pii

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "emails" / "templates"


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
        # Build invitation link
        invite_url = f"{settings.burnlens_frontend_url}/invite/{invitation_token}"

        # Build email content
        subject = f"You've been invited to {workspace_name} on BurnLens"

        html_content = f"""
        <html>
            <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2>You've been invited to BurnLens</h2>

                    <p>
                        {f"<strong>{invited_by_name}</strong> has invited you to join" if invited_by_name else "You've been invited to join"}
                        the <strong>{workspace_name}</strong> workspace on BurnLens.
                    </p>

                    <p>
                        <a href="{invite_url}" style="display: inline-block; background-color: #3b82f6; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: 500;">
                            Accept Invitation
                        </a>
                    </p>

                    <p style="color: #666; font-size: 14px;">
                        Or copy this link into your browser:<br>
                        <code style="background-color: #f3f4f6; padding: 2px 4px; border-radius: 2px;">{invite_url}</code>
                    </p>

                    <p style="color: #999; font-size: 12px; margin-top: 40px; border-top: 1px solid #eee; padding-top: 20px;">
                        This invitation will expire in 48 hours.
                    </p>
                </div>
            </body>
        </html>
        """

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

        # Run in background task (non-blocking)
        asyncio.create_task(_send_background())

        async def _send_background():
            """Send email in background."""
            await asyncio.to_thread(_send)

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

        asyncio.create_task(_send_background())
        return True

    except Exception as e:
        logger.error(
            "Error preparing usage warning email for workspace=%s: %s",
            workspace_id,
            e,
        )
        return False
