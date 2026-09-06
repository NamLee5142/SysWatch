import logging

import pytest
from alert_doubles import FakeAlertStore, make_snapshot, rule

from app.alerts.notifier import (
    OPENED,
    RESOLVED,
    LoggingNotifier,
    NotificationMisconfigured,
    Notifier,
    SeverityFilter,
    build_notifier,
    verify_notification_configuration,
)
from app.alerts.smtp import SmtpNotifier
from app.alerts.webhook import WebhookNotifier
from config import Settings

MAIL = {
    "smtp_host": "smtp.example.test",
    "smtp_from": "syswatch@example.test",
    "smtp_to": ["ops@example.test"],
}


def an_alert(severity="warning", store=None):
    store = store or FakeAlertStore()
    return store.open_new(
        rule=rule(id=1, name="CPU usage high", metric="cpu", operator="gt",
                  threshold=80.0, severity=severity),
        host_name="devbox",
        value=91.5,
        at=make_snapshot().collectedAt,
    )


class Recorder(Notifier):
    def __init__(self):
        self.delivered = []

    def deliver(self, change, alert):
        self.delivered.append((change, alert.severity))


# --- refusing what cannot deliver -------------------------------------------


@pytest.mark.parametrize(
    "settings, missing",
    [
        (Settings(smtp_host="smtp.example.test"), "SYSWATCH_SMTP_TO"),
        (Settings(smtp_to=["ops@example.test"]), "SYSWATCH_SMTP_HOST"),
        (Settings(smtp_host="h", smtp_to=["t@x.test"]), "SYSWATCH_SMTP_FROM"),
    ],
    ids=["host only", "recipients only", "no sender"],
)
def test_half_configured_mail_is_refused(settings, missing):
    """Found at startup, not when the first alert fails to arrive."""
    with pytest.raises(NotificationMisconfigured) as raised:
        verify_notification_configuration(settings)

    assert missing in str(raised.value)


def test_fully_configured_mail_is_accepted():
    verify_notification_configuration(Settings(**MAIL))


@pytest.mark.parametrize(
    "credentials",
    [{"smtp_username": "bob"}, {"smtp_password": "secret"}],
    ids=["username only", "password only"],
)
def test_half_configured_credentials_are_refused(credentials):
    """A username with no password authenticates as nobody.

    A password with no username is a secret sitting in a file for no reason.
    """
    with pytest.raises(NotificationMisconfigured, match="together"):
        verify_notification_configuration(Settings(**MAIL, **credentials))


def test_both_credentials_or_neither_is_accepted():
    verify_notification_configuration(Settings(**MAIL))
    verify_notification_configuration(
        Settings(**MAIL, smtp_username="bob", smtp_password="secret")
    )


@pytest.mark.parametrize(
    "url", ["hooks.example.test/abc", "ftp://hooks.example.test", "not a url"]
)
def test_a_webhook_that_is_not_a_url_is_refused(url):
    with pytest.raises(NotificationMisconfigured, match="http"):
        verify_notification_configuration(Settings(webhook_url=url))


def test_the_refusal_does_not_quote_the_webhook_url():
    """This message reaches the log, and the URL is usually a credential."""
    secret = "https:/hooks.example.test/T0/B0/S3CR3T"  # one slash: not a URL

    with pytest.raises(NotificationMisconfigured) as raised:
        verify_notification_configuration(Settings(webhook_url=secret))

    assert "S3CR3T" not in str(raised.value)


# --- warnings rather than refusals ------------------------------------------


def test_no_transport_at_all_is_a_warning_not_a_refusal():
    """A machine with nowhere to send is a normal, working install."""
    warnings = verify_notification_configuration(Settings())

    assert any("nobody is told" in warning for warning in warnings)


def test_a_plain_http_webhook_warns():
    warnings = verify_notification_configuration(
        Settings(webhook_url="http://hooks.example.test/abc")
    )

    assert any("in clear" in warning for warning in warnings)


def test_an_https_webhook_does_not_warn():
    assert verify_notification_configuration(
        Settings(webhook_url="https://hooks.example.test/abc")
    ) == []


# --- the severity filter ----------------------------------------------------


@pytest.mark.parametrize(
    "minimum, severity, delivered",
    [
        ("info", "info", True),
        ("info", "critical", True),
        ("warning", "info", False),
        ("warning", "warning", True),
        ("warning", "critical", True),
        ("critical", "warning", False),
        ("critical", "critical", True),
    ],
)
def test_only_alerts_at_or_above_the_minimum_are_sent(minimum, severity, delivered):
    recorder = Recorder()

    SeverityFilter(recorder, minimum).deliver(OPENED, an_alert(severity))

    assert bool(recorder.delivered) is delivered


def test_a_resolution_is_filtered_on_the_same_severity_as_its_opening():
    """Otherwise a reader is told an incident ended that they never heard start."""
    recorder = Recorder()
    filtered = SeverityFilter(recorder, "critical")

    filtered.deliver(OPENED, an_alert("warning"))
    filtered.deliver(RESOLVED, an_alert("warning"))

    assert recorder.delivered == []


def test_the_log_is_not_filtered(caplog):
    """An operator who does not want mail about warnings still wants the record."""
    built = build_notifier(Settings(**MAIL, notify_min_severity="critical"))

    with caplog.at_level(logging.INFO, logger="app.alerts.notifier"):
        # Reach past the SMTP transport, which would need a server.
        for notifier in built._notifiers:
            if isinstance(notifier, LoggingNotifier):
                notifier.deliver(OPENED, an_alert("info"))

    assert "CPU usage high" in caplog.text


def test_the_transports_are_wrapped_in_the_filter():
    built = build_notifier(
        Settings(**MAIL, webhook_url="https://hooks.example.test/abc")
    )

    wrapped = [n for n in built._notifiers if isinstance(n, SeverityFilter)]
    assert len(wrapped) == 2
    assert any(isinstance(n._notifier, SmtpNotifier) for n in wrapped)
    assert any(isinstance(n._notifier, WebhookNotifier) for n in wrapped)


def test_the_filter_does_not_reveal_what_it_wraps():
    built = build_notifier(
        Settings(**MAIL, smtp_password="s3cret", webhook_url="https://x.test/T0K3N")
    )

    printed = repr(built)
    assert "s3cret" not in printed
    assert "T0K3N" not in printed
