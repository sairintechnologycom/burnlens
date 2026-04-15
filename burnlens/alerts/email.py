"""Async email sender for BurnLens alerts using stdlib smtplib.

Uses asyncio.to_thread() to wrap blocking smtplib calls, keeping the
proxy event loop unblocked. No external dependencies -- smtplib is stdlib.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from burnlens.config import EmailConfig

logger = logging.getLogger(__name__)


class EmailSender:
    """Async email sender backed by smtplib.

    Wraps all blocking SMTP operations in asyncio.to_thread() so the
    event loop is never blocked. Follows the fail-open pattern -- all
    errors are caught and logged; the caller never sees an exception.

    When smtp_host is None the sender is unconfigured and send() is a no-op.
    """

    def __init__(self, config: EmailConfig) -> None:
        """Initialise EmailSender with SMTP configuration.

        Args:
            config: EmailConfig instance. If smtp_host is None, all
                    send() calls are silently dropped.
        """
        self._config = config

    async def send(
        self,
        to_addrs: list[str],
        subject: str,
        body_html: str,
    ) -> None:
        """Send an HTML email to one or more recipients.

        Uses asyncio.to_thread() to avoid blocking the event loop.
        Uses STARTTLS when port is 587; plain SMTP otherwise.
        Silently drops the message when smtp_host is None.
        All SMTP errors are caught and logged (fail-open).

        Args:
            to_addrs: List of recipient email addresses.
            subject:  Email subject line.
            body_html: HTML content for the email body.
        """
        config = self._config
        if not config.smtp_host:
            logger.debug("EmailSender: smtp_host not configured, skipping send")
            return

        def _send_blocking() -> None:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = config.from_addr or ""
            msg["To"] = ", ".join(to_addrs)
            msg.attach(MIMEText(body_html, "html"))

            with smtplib.SMTP(config.smtp_host, config.smtp_port) as smtp:
                if config.smtp_port == 587:
                    smtp.starttls()
                if config.smtp_user and config.smtp_password:
                    smtp.login(config.smtp_user, config.smtp_password)
                smtp.send_message(msg)

        try:
            await asyncio.to_thread(_send_blocking)
        except Exception as exc:
            logger.error("EmailSender: failed to send email to %s: %s", to_addrs, exc)


async def send_email(
    config: EmailConfig,
    to_addrs: list[str],
    subject: str,
    body_html: str,
) -> None:
    """Module-level convenience wrapper around EmailSender.send().

    Args:
        config:    EmailConfig instance.
        to_addrs:  Recipient email addresses.
        subject:   Email subject line.
        body_html: HTML body content.
    """
    sender = EmailSender(config)
    await sender.send(to_addrs=to_addrs, subject=subject, body_html=body_html)
