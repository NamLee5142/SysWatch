"""Delivery, against servers that did not come out of this repository.

Every other delivery test uses a double, and correctly: a test about what the
engine does when a webhook fails should not wait on a TCP handshake to find
out. But a double only ever confirms that the code does what its author
expected, because the same person wrote both. These run the real transports
against real listeners on loopback and check the bytes that actually left the
process.

They were written after the three claims below were verified by hand, once,
before a release. Verified once is a fact about an afternoon.
"""
import email
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from local_servers import SmtpServer, WebhookServer, free_port, serve

from app.alerts.notifier import OPENED, RESOLVED, build_notifier
from app.alerts.smtp import SmtpNotifier
from app.logging_config import configure_logging
from config import Settings

# Shaped like a path a real service would use. Slack, Discord and Teams all put
# the credential in the path rather than in a header, which is what makes a
# webhook URL a secret and not merely an address.
TOKEN = "B01ABCDEF/XXXXXXXXXXXXXXXXXXXXXXXX"

SECRET = "x" * 40


@pytest.fixture(autouse=True)
def restore_root_logging():
    """configure_logging() reaches into the root logger, which outlives a test."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level

    yield

    for handler in list(root.handlers):
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    for handler in handlers:
        if handler not in root.handlers:
            root.addHandler(handler)
    root.setLevel(level)


@pytest.fixture
def mail():
    server = serve(SmtpServer(free_port()))
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def webhook():
    server = serve(WebhookServer(free_port()))
    yield server
    server.shutdown()
    server.server_close()


def an_alert(**overrides):
    """A row the way AlertStore hands one back."""
    fields = dict(
        id=1,
        rule_id=1,
        rule_name="CPU usage critical",
        metric="cpu",
        operator="gt",
        threshold=90.0,
        severity="critical",
        host_name="devbox",
        state="firing",
        value=97.4,
        triggered_at=datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc),
        resolved_at=None,
        last_seen_at=datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc),
        acknowledged_at=None,
        acknowledged_by=None,
        last_notified_at=None,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def settings_for(mail=None, webhook=None, **overrides):
    values = dict(_env_file=None, session_secret=SECRET)
    if mail is not None:
        values.update(
            smtp_host="127.0.0.1",
            smtp_port=mail.port,
            smtp_from="syswatch@example.com",
            smtp_to="ops@example.com,oncall@example.com",
        )
    if webhook is not None:
        values["webhook_url"] = f"http://127.0.0.1:{webhook.port}/services/{TOKEN}"
    values.update(overrides)
    return Settings(**values)


# --- what actually arrives ---------------------------------------------------


def test_a_real_mail_server_receives_a_well_formed_message(mail):
    """The headers a fake never checks, because a fake never parses them."""
    build_notifier(settings_for(mail=mail)).deliver(OPENED, an_alert())

    assert len(mail.delivered) == 1
    received = mail.delivered[0]

    # Both recipients reached the envelope, so the comma splitting survives
    # contact with SMTP and not just with a list comprehension.
    assert received["recipients"] == ["<ops@example.com>", "<oncall@example.com>"]

    message = email.message_from_bytes(received["data"])
    assert message["Subject"] == "[critical] CPU usage critical on devbox"
    assert message["From"] == "syswatch@example.com"
    assert message["To"] == "ops@example.com, oncall@example.com"

    body = message.get_payload()
    assert "Alert opened: CPU usage critical" in body
    assert "devbox" in body
    assert "97.4" in body


def test_a_real_webhook_receives_the_alert(webhook):
    notifier = build_notifier(settings_for(webhook=webhook))

    notifier.deliver(OPENED, an_alert())
    notifier.deliver(RESOLVED, an_alert(state="ok", value=11.2))

    assert [post["path"] for post in webhook.received] == [
        f"/services/{TOKEN}",
        f"/services/{TOKEN}",
    ]
    assert webhook.received[0]["content_type"] == "application/json"

    opened = json.loads(webhook.received[0]["body"])
    assert opened["change"] == OPENED
    assert opened["alert"]["ruleName"] == "CPU usage critical"
    assert opened["alert"]["hostName"] == "devbox"
    assert json.loads(webhook.received[1]["body"])["change"] == RESOLVED


# --- claim 1: credentials never cross an unencrypted connection --------------


def test_credentials_are_never_sent_to_a_server_that_will_not_encrypt(mail):
    """The refusal in smtp.py, checked from the receiving end.

    Asserting that deliver() raises only proves the code decided not to send.
    The server is what can say whether AUTH arrived, and that is the claim: not
    "we meant not to", but "it never left". The server advertises AUTH for that
    reason - against one that does not, smtplib declines on its own and this
    passes with the refusal deleted.
    """
    notifier = SmtpNotifier(
        host="127.0.0.1",
        port=mail.port,
        username="syswatch@example.com",
        password="hunter2",
        sender="syswatch@example.com",
        recipients=["ops@example.com"],
    )

    with pytest.raises(RuntimeError, match="refusing to send the password in clear"):
        notifier.deliver(OPENED, an_alert())

    assert mail.auth_attempted is False
    assert mail.delivered == []


def test_a_server_offering_starttls_is_not_refused():
    """The other half, so the test above is about STARTTLS and not about auth.

    Only as far as the handshake: this server has no certificate, so wrapping
    the socket fails. What matters is that the failure is a TLS failure and not
    the refusal - the client tried to encrypt rather than declining to.
    """
    server = serve(SmtpServer(free_port(), offer_starttls=True))
    try:
        notifier = SmtpNotifier(
            host="127.0.0.1",
            port=server.port,
            username="syswatch@example.com",
            password="hunter2",
            sender="syswatch@example.com",
            recipients=["ops@example.com"],
        )

        with pytest.raises(Exception) as raised:
            notifier.deliver(OPENED, an_alert())

        assert "refusing to send the password in clear" not in str(raised.value)
        assert server.auth_attempted is False
    finally:
        server.shutdown()
        server.server_close()


# --- claim 2: the webhook token never reaches the log ------------------------


def test_the_webhook_token_never_reaches_the_log_over_a_real_connection(
    webhook, tmp_path, monkeypatch
):
    """At DEBUG, which is the worst an operator can configure.

    There is a sibling test against a mocked transport. This one exists because
    that mock intercepts the request before a socket is opened, so it cannot
    see what the transport would have logged - and the transport is httpcore, a
    different logger from the httpx one logging_config silences. httpcore wrote
    the webhook's host and port at DEBUG until this test was written.
    """
    monkeypatch.setenv("SYSWATCH_LOG_DIR", str(tmp_path))
    settings = settings_for(webhook=webhook, log_dir=str(tmp_path), log_level="DEBUG")
    log_file = configure_logging(settings)

    build_notifier(settings).deliver(OPENED, an_alert())

    assert len(webhook.received) == 1, "the request has to happen for this to mean anything"
    written = log_file.read_text(encoding="utf-8")

    assert TOKEN not in written
    assert "/services/" not in written
    # Neither logger may write at all, which is what makes the two assertions
    # above hold for a reason rather than by luck: httpcore does not log paths
    # today, and that is somebody else's decision to change.
    assert "httpx" not in written
    assert "httpcore" not in written


def test_a_failed_webhook_names_no_url_either(tmp_path, monkeypatch):
    """The failure path formats a message, which is where a URL slips in."""
    monkeypatch.setenv("SYSWATCH_LOG_DIR", str(tmp_path))
    port = free_port()  # nothing is listening here

    settings = Settings(
        _env_file=None,
        session_secret=SECRET,
        log_dir=str(tmp_path),
        log_level="DEBUG",
        webhook_url=f"http://127.0.0.1:{port}/services/{TOKEN}",
    )
    log_file = configure_logging(settings)

    build_notifier(settings).deliver(OPENED, an_alert())

    written = log_file.read_text(encoding="utf-8")
    assert TOKEN not in written
    assert "/services/" not in written
    assert "Could not deliver an alert through" in written


# --- claim 3: one broken transport does not take the other with it -----------


def test_a_dead_mail_server_does_not_stop_the_webhook(webhook, mail):
    """Both configured, one unreachable, and the order is not in the test's gift.

    CompositeNotifier isolates each transport. If it did not, whichever ran
    first would decide whether the second ran at all.
    """
    mail.shutdown()
    mail.server_close()  # configured, and now refusing connections

    settings = settings_for(mail=mail, webhook=webhook)

    # Returns rather than raising: the caller is the poll loop.
    build_notifier(settings).deliver(OPENED, an_alert())

    assert len(webhook.received) == 1
    assert json.loads(webhook.received[0]["body"])["change"] == OPENED
