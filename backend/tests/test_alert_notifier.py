import logging

import pytest
from alert_doubles import FakeAlertStore, FakeRuleStore, make_snapshot, rule

from app.alerts import AlertEngine
from app.alerts.notifier import OPENED, RESOLVED, LoggingNotifier, Notifier


def an_alert(store=None):
    """One opened alert, built the way the engine builds them."""
    store = store or FakeAlertStore()
    return store.open_new(
        rule=rule(id=7, name="CPU usage high", metric="cpu", operator="gt", threshold=80.0),
        host_name="devbox",
        value=91.5,
        at=make_snapshot().collectedAt,
    )


class RecordingNotifier(Notifier):
    def __init__(self):
        self.delivered = []

    def deliver(self, change, alert):
        self.delivered.append((change, alert))


class BrokenNotifier(Notifier):
    def deliver(self, change, alert):
        raise RuntimeError("the mail server is on fire")


def engine_with(notifier, alert_store=None, threshold=80.0):
    return AlertEngine(
        FakeRuleStore(rule(id=1, metric="cpu", operator="gt", threshold=threshold)),
        alert_store or FakeAlertStore(),
        notifier=notifier,
    )


# --- the interface ----------------------------------------------------------


def test_the_base_notifier_refuses_to_pretend_it_delivered():
    """A subclass that forgets to implement deliver must not silently succeed."""
    with pytest.raises(NotImplementedError):
        Notifier().deliver(OPENED, an_alert())


# --- the logging implementation ---------------------------------------------


def test_an_opened_alert_names_the_rule_the_host_and_the_value(caplog):
    with caplog.at_level(logging.INFO, logger="app.alerts.notifier"):
        LoggingNotifier().deliver(OPENED, an_alert())

    written = caplog.text
    assert "opened" in written
    assert "CPU usage high" in written
    assert "devbox" in written
    assert "91.5" in written
    assert "80.0" in written
    assert "warning" in written


def test_a_resolved_alert_says_so(caplog):
    store = FakeAlertStore()
    alert = an_alert(store)
    resolved = store.resolve(alert_id=alert.id, value=42.0, at=alert.triggered_at)

    with caplog.at_level(logging.INFO, logger="app.alerts.notifier"):
        LoggingNotifier().deliver(RESOLVED, resolved)

    assert "resolved" in caplog.text
    assert "42.0" in caplog.text


def test_an_opening_is_a_warning_and_a_recovery_is_not(caplog):
    """An operator grepping for what went wrong wants the openings.

    Both stay at or above the default level, so neither is lost - a recovery
    that vanished would leave a log showing an incident that never ended.
    """
    with caplog.at_level(logging.INFO, logger="app.alerts.notifier"):
        LoggingNotifier().deliver(OPENED, an_alert())
        LoggingNotifier().deliver(RESOLVED, an_alert())

    assert [record.levelno for record in caplog.records] == [
        logging.WARNING,
        logging.INFO,
    ]


# --- what the engine announces ----------------------------------------------


def test_opening_an_alert_is_announced():
    notifier = RecordingNotifier()

    engine_with(notifier).evaluate(make_snapshot(cpu_usage=95))

    assert [change for change, _ in notifier.delivered] == [OPENED]
    _, alert = notifier.delivered[0]
    assert alert.value == 95
    assert alert.host_name == "devbox"


def test_a_still_firing_alert_is_announced_once_not_every_tick():
    """The reason a notifier takes state changes rather than evaluations.

    A rule breached for six hours at a ten-second interval would otherwise be
    2,160 messages about one problem.
    """
    notifier = RecordingNotifier()
    engine = engine_with(notifier)

    for _ in range(5):
        engine.evaluate(make_snapshot(cpu_usage=95))

    assert [change for change, _ in notifier.delivered] == [OPENED]


def test_a_recovery_is_announced_with_the_resolved_alert():
    notifier = RecordingNotifier()
    engine = engine_with(notifier)

    engine.evaluate(make_snapshot(cpu_usage=95))
    engine.evaluate(make_snapshot(cpu_usage=10))

    assert [change for change, _ in notifier.delivered] == [OPENED, RESOLVED]

    # The resolved row, not the copy the engine was holding, which still said
    # the alert was firing.
    _, alert = notifier.delivered[1]
    assert alert.state == "ok"
    assert alert.resolved_at is not None


def test_a_rule_that_stops_existing_still_announces_its_resolution():
    """The engine closes alerts whose rule was disabled or deleted.

    That path resolves outside the per-rule loop, and would be an easy one to
    leave un-announced - the alert would vanish from the dashboard with no
    message ever sent about it.
    """
    notifier = RecordingNotifier()
    rules = FakeRuleStore(rule(id=1, metric="cpu", operator="gt", threshold=80))
    engine = AlertEngine(rules, FakeAlertStore(), notifier=notifier)

    engine.evaluate(make_snapshot(cpu_usage=95))
    rules.rules[0].enabled = False
    engine.evaluate(make_snapshot(cpu_usage=95))

    assert [change for change, _ in notifier.delivered] == [OPENED, RESOLVED]


def test_an_engine_with_no_notifier_still_works():
    engine = AlertEngine(
        FakeRuleStore(rule(id=1, metric="cpu", operator="gt", threshold=80)),
        FakeAlertStore(),
    )

    assert engine.evaluate(make_snapshot(cpu_usage=95)).opened == 1


def test_a_broken_notifier_does_not_stop_an_alert_being_recorded():
    """The row is the durable thing; the message is a courtesy on top of it."""
    store = FakeAlertStore()

    summary = engine_with(BrokenNotifier(), store).evaluate(make_snapshot(cpu_usage=95))

    assert summary.opened == 1
    assert len(store.active("devbox")) == 1


def test_a_broken_notifier_is_reported_not_swallowed_silently(caplog):
    engine = engine_with(BrokenNotifier())

    with caplog.at_level(logging.WARNING, logger="app.alerts.engine"):
        engine.evaluate(make_snapshot(cpu_usage=95))

    assert "Could not deliver" in caplog.text
    assert "the mail server is on fire" in caplog.text
