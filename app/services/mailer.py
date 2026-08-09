"""Outbound email.

Only one message is sent today — the password reset link — but that one is
enough to matter: without a transport, a user who forgets their password has
no way back into their account, and the reset token has nowhere safe to go.
(It must never be logged; application logs are routinely shipped to a log
aggregator, which is a far wider audience than the account owner.)

Configuration is entirely optional. With ``SMTP_HOST`` unset the mailer
reports itself unconfigured and callers fall back to whatever they did
before, so local development and the test suite need no mail server. That
also means a misconfigured production deploy fails visibly at the point of
sending rather than silently swallowing mail.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import get_settings

log = logging.getLogger(__name__)


class EmailNotConfiguredError(RuntimeError):
    """No SMTP transport is configured."""


def is_configured() -> bool:
    return bool(get_settings().smtp_host)


def send_email(*, to: str, subject: str, body: str) -> None:
    """Send a plain-text message. Raises rather than returning a status, so a
    caller can't accidentally treat a failed send as a success."""
    settings = get_settings()
    if not settings.smtp_host:
        raise EmailNotConfiguredError("SMTP_HOST is not set")

    message = EmailMessage()
    message["From"] = settings.smtp_from or settings.smtp_username or "no-reply@localhost"
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    # implicit TLS (465) connects wrapped; STARTTLS (587) upgrades after
    # greeting. Choosing on the flag rather than the port keeps unusual
    # deployments (a relay on 2525, say) working.
    context = ssl.create_default_context()
    if settings.smtp_use_ssl:
        with smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds, context=context
        ) as client:
            _authenticate_and_send(client, message, settings)
    else:
        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
        ) as client:
            if settings.smtp_use_starttls:
                client.starttls(context=context)
            _authenticate_and_send(client, message, settings)


def _authenticate_and_send(client, message: EmailMessage, settings) -> None:
    if settings.smtp_username and settings.smtp_password:
        client.login(settings.smtp_username, settings.smtp_password)
    client.send_message(message)


def send_password_reset(*, to: str, username: str, token: str) -> None:
    """Deliver a reset link. The token appears only here, in the message body —
    never in a log line or an API response."""
    settings = get_settings()
    base = (settings.public_base_url or "").rstrip("/")
    link = f"{base}/reset-password?token={token}" if base else f"Reset token: {token}"
    minutes = settings.password_reset_token_expire_minutes

    send_email(
        to=to,
        subject="Reset your API Security Monitor password",
        body=(
            f"Hello {username},\n\n"
            "Someone requested a password reset for your API Security Monitor account.\n\n"
            f"{link}\n\n"
            f"This link expires in {minutes} minutes and can be used once.\n\n"
            "If you didn't request this, you can ignore this message — your password "
            "has not been changed.\n"
        ),
    )
