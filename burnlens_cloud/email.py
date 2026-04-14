"""Email utilities for BurnLens Cloud."""

import logging
import asyncio
from typing import Optional
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content
from .config import settings

logger = logging.getLogger(__name__)


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
