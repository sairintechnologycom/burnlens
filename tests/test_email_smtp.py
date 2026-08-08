"""SMTP delivery path — provider-agnostic transactional email.

Replaced the SendGrid SDK: every provider (Resend, Brevo, SES, Postmark) speaks
SMTP, so the provider is an env var rather than a code dependency. These tests
pin the wire behaviour that the provider actually cares about.
"""
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/burnlens_test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests")
os.environ.setdefault("ENVIRONMENT", "test")


def _smtp_mock():
    """Mock smtplib.SMTP used as a context manager."""
    server = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=server)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, server


def test_smtp_send_uses_starttls_and_login():
    from burnlens_cloud import config as config_mod
    from burnlens_cloud.email import _smtp_send

    ctx, server = _smtp_mock()
    with patch.object(config_mod.settings, "smtp_host", "smtp.resend.com"), \
         patch.object(config_mod.settings, "smtp_port", 587), \
         patch.object(config_mod.settings, "smtp_username", "resend"), \
         patch.object(config_mod.settings, "smtp_password", "re_fake"), \
         patch.object(config_mod.settings, "mail_from", "noreply@burnlens.app"), \
         patch("burnlens_cloud.email.smtplib.SMTP", return_value=ctx) as smtp_cls:
        _smtp_send("user@example.com", "Test subject", "<p>hello</p>")

    smtp_cls.assert_called_once()
    assert smtp_cls.call_args.args[0] == "smtp.resend.com"
    assert smtp_cls.call_args.args[1] == 587
    # Credentials must never cross the wire before TLS is negotiated.
    assert server.method_calls[0][0] == "starttls", (
        f"starttls must precede login, got {[c[0] for c in server.method_calls]}"
    )
    server.login.assert_called_once_with("resend", "re_fake")
    server.send_message.assert_called_once()


def test_smtp_send_builds_multipart_with_html_and_text():
    from burnlens_cloud import config as config_mod
    from burnlens_cloud.email import _smtp_send

    ctx, server = _smtp_mock()
    with patch.object(config_mod.settings, "smtp_password", "re_fake"), \
         patch.object(config_mod.settings, "mail_from", "noreply@burnlens.app"), \
         patch("burnlens_cloud.email.smtplib.SMTP", return_value=ctx):
        _smtp_send("user@example.com", "Reset your password", "<p>click me</p>")

    msg = server.send_message.call_args.args[0]
    assert msg["From"] == "noreply@burnlens.app"
    assert msg["To"] == "user@example.com"
    assert msg["Subject"] == "Reset your password"
    # A text/plain alternative alongside the HTML — bare-HTML mail scores badly
    # with spam filters, which for password resets means lockouts.
    types = {part.get_content_type() for part in msg.walk()}
    assert "text/html" in types and "text/plain" in types
    html = msg.get_body(preferencelist=("html",)).get_content()
    assert "click me" in html


@pytest.mark.asyncio
async def test_deliver_noops_when_unconfigured():
    """Fail-open: no credential means no send and no exception — but also no
    silent success, so callers can log it."""
    from burnlens_cloud import config as config_mod
    from burnlens_cloud.email import deliver

    with patch.object(config_mod.settings, "smtp_password", ""), \
         patch("burnlens_cloud.email.smtplib.SMTP") as smtp_cls:
        queued = deliver("user@example.com", "s", "<p>b</p>", "test")

    assert queued is False
    smtp_cls.assert_not_called()
