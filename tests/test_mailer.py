"""Outbound email transport and its use in the password reset flow.

The properties worth pinning are mostly about what must *not* happen: the
token must not reach the logs, delivery failure must not change the response
(that would reintroduce account enumeration), and an unconfigured deployment
must degrade to administrator-assisted recovery rather than pretending to
have sent something.
"""

import logging
import re

import pytest

from app.config import Settings
from app.services import mailer


def _settings(**over):
    return Settings(_env_file=None, **over)


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------

def test_unconfigured_by_default(monkeypatch):
    monkeypatch.setattr(mailer, "get_settings", lambda: _settings())
    assert mailer.is_configured() is False


def test_configured_once_a_host_is_set(monkeypatch):
    monkeypatch.setattr(mailer, "get_settings", lambda: _settings(smtp_host="smtp.example.com"))
    assert mailer.is_configured() is True


def test_send_without_a_host_raises_rather_than_silently_succeeding(monkeypatch):
    monkeypatch.setattr(mailer, "get_settings", lambda: _settings())
    with pytest.raises(mailer.EmailNotConfiguredError):
        mailer.send_email(to="a@example.com", subject="x", body="y")


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------

class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port
        self.started_tls = False
        self.logged_in_as = None
        self.sent = []
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in_as = user

    def send_message(self, msg):
        self.sent.append(msg)


@pytest.fixture()
def fake_smtp(monkeypatch):
    _FakeSMTP.instances = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", _FakeSMTP)
    return _FakeSMTP


def test_starttls_path_upgrades_and_authenticates(monkeypatch, fake_smtp):
    monkeypatch.setattr(
        mailer,
        "get_settings",
        lambda: _settings(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="mailer",
            smtp_password="secret",  # nosec B106
            smtp_from="monitor@example.com",
        ),
    )
    mailer.send_email(to="user@example.com", subject="Subject", body="Body")

    sent = fake_smtp.instances[0]
    assert sent.started_tls is True, "credentials must not cross the wire before TLS"
    assert sent.logged_in_as == "mailer"
    assert sent.sent[0]["To"] == "user@example.com"
    assert sent.sent[0]["From"] == "monitor@example.com"


def test_implicit_ssl_path_does_not_call_starttls(monkeypatch, fake_smtp):
    monkeypatch.setattr(
        mailer,
        "get_settings",
        lambda: _settings(smtp_host="smtp.example.com", smtp_port=465, smtp_use_ssl=True),
    )
    mailer.send_email(to="user@example.com", subject="S", body="B")
    assert fake_smtp.instances[0].started_tls is False


def test_anonymous_relay_skips_login(monkeypatch, fake_smtp):
    monkeypatch.setattr(mailer, "get_settings", lambda: _settings(smtp_host="relay.internal"))
    mailer.send_email(to="user@example.com", subject="S", body="B")
    assert fake_smtp.instances[0].logged_in_as is None


# ---------------------------------------------------------------------------
# the reset message itself
# ---------------------------------------------------------------------------

def test_reset_email_contains_a_usable_link(monkeypatch, fake_smtp):
    monkeypatch.setattr(
        mailer,
        "get_settings",
        lambda: _settings(smtp_host="smtp.example.com", public_base_url="https://monitor.example.com/"),
    )
    mailer.send_password_reset(to="user@example.com", username="alice", token="TOKEN123")
    body = fake_smtp.instances[0].sent[0].get_content()
    assert "https://monitor.example.com/reset-password?token=TOKEN123" in body
    assert "alice" in body
    assert "expires" in body


def test_reset_email_falls_back_to_the_bare_token_without_a_base_url(monkeypatch, fake_smtp):
    monkeypatch.setattr(mailer, "get_settings", lambda: _settings(smtp_host="smtp.example.com"))
    mailer.send_password_reset(to="user@example.com", username="alice", token="TOKEN123")
    assert "TOKEN123" in fake_smtp.instances[0].sent[0].get_content()


def test_reset_token_never_reaches_the_logs_when_mail_is_sent(monkeypatch, fake_smtp, caplog):
    monkeypatch.setattr(mailer, "get_settings", lambda: _settings(smtp_host="smtp.example.com"))
    with caplog.at_level(logging.DEBUG):
        mailer.send_password_reset(to="user@example.com", username="alice", token="TOKENabcdef123456")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "TOKENabcdef123456" not in text
    assert not re.search(r"[A-Za-z0-9_-]{40,}", text)
