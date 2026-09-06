import logging

import pytest
from alert_doubles import FakeAlertStore, FakeRuleStore, make_snapshot, rule

from app.alerts import AlertEngine
from app.alerts.notifier import OPENED, RESOLVED
from app.alerts.smtp import SmtpNotifier

PASSWORD = "hunter2-but-longer"


class FakeSmtp:
    """Stands in for smtplib.SMTP, recording what a real server would see."""

    instances = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.starttls_called = False
        self.logged_in_as = None
        self.messages = []
        self.extensions = {"starttls"}
        self.closed = False
        FakeSmtp.instances.append(self)

    # smtplib.SMTP is a context manager and quits on exit.
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False

    def ehlo(self):
        pass

    def has_extn(self, name):
        return name in self.extensions

    def starttls(self):
        self.starttls_called = True

    def login(self, username, password):
        self.logged_in_as = (username, password)

    def send_message(self, message):
        self.messages.append(message)


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSmtp.instances = []
    monkeypatch.setattr("app.alerts.smtp.smtplib.SMTP", FakeSmtp)
    return FakeSmtp


def notifier(**overrides):
    settings = {
        "host": "smtp.example.test",
        "port": 587,
        "username": "syswatch",
        "password": PASSWORD,
        "sender": "syswatch@example.test",
        "recipients": ["ops@example.test", "oncall@example.test"],
    }
    settings.update(overrides)
    return SmtpNotifier(**settings)


def an_alert(store=None, **overrides):
    store = store or FakeAlertStore()
    fields = {"id": 7, "name": "CPU usage high", "metric": "cpu",
              "operator": "gt", "threshold": 80.0, "severity": "warning"}
    fields.update(overrides)
    return store.open_new(
        rule=rule(**fields), host_name="devbox", value=91.5,
        at=make_snapshot().collectedAt,
    )


# --- the message ------------------------------------------------------------


def test_an_opened_alert_is_one_message_to_every_recipient():
    notifier().deliver(OPENED, an_alert())

    sent = FakeSmtp.instances[0].messages
    assert len(sent) == 1
    assert sent[0]["To"] == "ops@example.test, oncall@example.test"
    assert sent[0]["From"] == "syswatch@example.test"


def test_the_subject_leads_with_severity_rule_and_host():
    """A mail client's subject column has to be enough to triage on."""
    notifier().deliver(OPENED, an_alert(severity="critical"))

    assert FakeSmtp.instances[0].messages[0]["Subject"] == (
        "[critical] CPU usage high on devbox"
    )


def test_a_recovery_says_resolved_rather_than_its_old_severity():
    """The severity of an alert that has ended is not the news."""
    store = FakeAlertStore()
    alert = an_alert(store, severity="critical")
    resolved = store.resolve(alert_id=alert.id, value=12.0, at=alert.triggered_at)

    notifier().deliver(RESOLVED, resolved)

    assert FakeSmtp.instances[0].messages[0]["Subject"] == (
        "[resolved] CPU usage high on devbox"
    )


def test_the_body_carries_the_value_the_threshold_and_when_it_started():
    notifier().deliver(OPENED, an_alert())

    body = FakeSmtp.instances[0].messages[0].get_content()
    assert "devbox" in body
    assert "91.5" in body
    assert "gt 80.0" in body
    assert "warning" in body
    assert "2026" in body  # the trigger time, not a placeholder


def test_a_resolution_reports_when_it_ended():
    store = FakeAlertStore()
    alert = an_alert(store)
    resolved = store.resolve(alert_id=alert.id, value=12.0, at=alert.triggered_at)

    notifier().deliver(RESOLVED, resolved)

    assert "Resolved:" in FakeSmtp.instances[0].messages[0].get_content()


# --- the connection ---------------------------------------------------------


def test_the_connection_is_encrypted_before_the_password_is_sent():
    notifier().deliver(OPENED, an_alert())

    server = FakeSmtp.instances[0]
    assert server.starttls_called
    assert server.logged_in_as == ("syswatch", PASSWORD)


def test_a_server_without_starttls_is_refused_when_credentials_are_configured():
    """Better that the alert does not arrive than that the password crosses in clear."""
    FakeSmtp.extensions = set()

    def no_tls(host, port, timeout=None):
        server = FakeSmtp(host, port, timeout)
        server.extensions = set()
        return server

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("app.alerts.smtp.smtplib.SMTP", no_tls)

        with pytest.raises(RuntimeError, match="STARTTLS"):
            notifier().deliver(OPENED, an_alert())

    assert FakeSmtp.instances[-1].logged_in_as is None


def test_an_unauthenticated_relay_without_starttls_is_allowed():
    """A local relay with no credentials has no secret to protect."""
    def no_tls(host, port, timeout=None):
        server = FakeSmtp(host, port, timeout)
        server.extensions = set()
        return server

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("app.alerts.smtp.smtplib.SMTP", no_tls)
        notifier(username="", password="").deliver(OPENED, an_alert())

    assert len(FakeSmtp.instances[-1].messages) == 1


def test_the_connection_is_bounded_by_a_timeout():
    """deliver() runs on the poller's thread; an unbounded wait stalls collection."""
    notifier().deliver(OPENED, an_alert())

    assert FakeSmtp.instances[0].timeout == 10


def test_the_connection_is_closed():
    notifier().deliver(OPENED, an_alert())

    assert FakeSmtp.instances[0].closed


# --- the password -----------------------------------------------------------


def test_the_password_is_not_in_the_repr():
    """A traceback frame, an error message, somebody's REPL."""
    printed = repr(notifier())

    assert PASSWORD not in printed
    assert "smtp.example.test" in printed


def test_a_failed_send_does_not_put_the_password_in_the_log(caplog):
    """The engine logs delivery failures with a traceback. It must stay clean."""
    def explodes(host, port, timeout=None):
        raise OSError("connection refused")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("app.alerts.smtp.smtplib.SMTP", explodes)

        engine = AlertEngine(
            FakeRuleStore(rule(id=1, metric="cpu", operator="gt", threshold=80)),
            FakeAlertStore(),
            notifier=notifier(),
        )

        with caplog.at_level(logging.WARNING):
            summary = engine.evaluate(make_snapshot(cpu_usage=95))

    assert summary.opened == 1  # the alert is still recorded
    assert "Could not deliver" in caplog.text
    assert PASSWORD not in caplog.text


def test_the_smtp_module_has_no_logger():
    """The surest way a secret never reaches a log.

    app/auth/ holds to the same rule: the file that holds the password has
    nothing in it that can write one.
    """
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "app" / "alerts" / "smtp.py"
    ).read_text(encoding="utf-8")

    assert "getLogger" not in source
    assert "logger." not in source


# --- one message per state change, not per evaluation -----------------------


def test_a_still_firing_alert_sends_nothing():
    engine = AlertEngine(
        FakeRuleStore(rule(id=1, metric="cpu", operator="gt", threshold=80)),
        FakeAlertStore(),
        notifier=notifier(),
    )

    for _ in range(5):
        engine.evaluate(make_snapshot(cpu_usage=95))

    assert sum(len(server.messages) for server in FakeSmtp.instances) == 1


# --- assembling the notifier from configuration -----------------------------


def test_no_smtp_host_means_no_mail(monkeypatch):
    from config import Settings

    from app.alerts import build_notifier
    from app.alerts.smtp import SmtpNotifier

    built = build_notifier(Settings())

    assert not any(isinstance(n, SmtpNotifier) for n in built._notifiers)


def test_a_configured_host_adds_the_transport():
    from config import Settings

    from app.alerts import build_notifier
    from app.alerts.smtp import SmtpNotifier

    built = build_notifier(
        Settings(smtp_host="smtp.example.test", smtp_to=["ops@example.test"])
    )

    assert any(isinstance(n, SmtpNotifier) for n in built._notifiers)


def test_the_log_notifier_is_always_there():
    """A machine with no mail server still leaves a record of what fired."""
    from config import Settings

    from app.alerts import build_notifier
    from app.alerts.notifier import LoggingNotifier

    assert any(isinstance(n, LoggingNotifier) for n in build_notifier(Settings())._notifiers)


def test_one_broken_transport_does_not_silence_the_others(caplog):
    """Isolated per notifier, not per delivery.

    Otherwise the first transport to raise silences every one after it, and
    which those are depends on list order.
    """
    from app.alerts.notifier import CompositeNotifier, LoggingNotifier, Notifier

    class Broken(Notifier):
        def deliver(self, change, alert):
            raise RuntimeError("down")

    composite = CompositeNotifier([Broken(), LoggingNotifier()])

    with caplog.at_level(logging.INFO):
        composite.deliver(OPENED, an_alert())

    assert "Could not deliver an alert through Broken" in caplog.text
    assert "CPU usage high" in caplog.text  # the log notifier still ran


def test_the_built_notifier_never_reveals_the_password():
    from config import Settings

    from app.alerts import build_notifier

    built = build_notifier(
        Settings(smtp_host="smtp.example.test", smtp_password=PASSWORD)
    )

    assert PASSWORD not in repr(built)
