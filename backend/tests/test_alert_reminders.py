"""Reminders about alerts that are still firing, and what stops them.

Without these, acknowledgement changed nothing: the engine announced an alert
opening and its resolution, and a firing alert was never mentioned again, so
there was nothing an acknowledgement could suppress. An alert that fires at 2am
and is never raised again is also easy to lose.

So a reminder is what acknowledgement silences, and silencing a rule silences
it too. A resolution is not a reminder: the end of an incident is news even
when its start was acknowledged.
"""
from datetime import datetime, timedelta, timezone

import pytest
from alert_doubles import FakeAlertStore, FakeRuleStore, make_snapshot, rule

from app.alerts import AlertEngine
from app.alerts.notifier import OPENED, RESOLVED, Notifier

HOUR = timedelta(hours=1)


class Recorder(Notifier):
    def __init__(self):
        self.delivered = []

    def deliver(self, change, alert):
        self.delivered.append(change)


def engine_with(recorder, repeat_after=HOUR, silenced_until=None, store=None):
    return AlertEngine(
        FakeRuleStore(
            rule(
                id=1,
                metric="cpu",
                operator="gt",
                threshold=80.0,
                silenced_until=silenced_until,
            )
        ),
        store or FakeAlertStore(),
        notifier=recorder,
        repeat_after=repeat_after,
    )


def age(store, alert_id, by):
    """Pretend the last message about this alert went out `by` ago."""
    row = store._by_id(alert_id)
    row.last_notified_at = datetime.now(timezone.utc) - by


# --- reminding --------------------------------------------------------------


def test_a_firing_alert_is_not_mentioned_again_straight_away():
    recorder = Recorder()
    engine = engine_with(recorder)

    for _ in range(5):
        engine.evaluate(make_snapshot(cpu_usage=95))

    assert recorder.delivered == [OPENED]


def test_a_firing_alert_is_mentioned_again_once_the_interval_passes():
    recorder = Recorder()
    store = FakeAlertStore()
    engine = engine_with(recorder, store=store)

    engine.evaluate(make_snapshot(cpu_usage=95))
    age(store, 1, by=HOUR + timedelta(minutes=1))
    engine.evaluate(make_snapshot(cpu_usage=95))

    assert recorder.delivered == [OPENED, OPENED]


def test_a_reminder_does_not_repeat_on_the_next_tick():
    """The stamp moves, so the next reminder is a whole interval away."""
    recorder = Recorder()
    store = FakeAlertStore()
    engine = engine_with(recorder, store=store)

    engine.evaluate(make_snapshot(cpu_usage=95))
    age(store, 1, by=HOUR + timedelta(minutes=1))
    engine.evaluate(make_snapshot(cpu_usage=95))
    engine.evaluate(make_snapshot(cpu_usage=95))

    assert recorder.delivered == [OPENED, OPENED]


def test_reminders_are_off_unless_asked_for():
    """Mailing somebody every four hours is not a default anyone should inherit."""
    recorder = Recorder()
    store = FakeAlertStore()
    engine = engine_with(recorder, repeat_after=None, store=store)

    engine.evaluate(make_snapshot(cpu_usage=95))
    age(store, 1, by=timedelta(days=7))
    engine.evaluate(make_snapshot(cpu_usage=95))

    assert recorder.delivered == [OPENED]


def test_a_reminder_carries_the_current_value_not_a_stale_one():
    """The row the loop holds was read before touch() updated it."""
    seen = []

    class Capturing(Notifier):
        def deliver(self, change, alert):
            seen.append(alert.value)

    store = FakeAlertStore()
    engine = engine_with(Capturing(), store=store)

    engine.evaluate(make_snapshot(cpu_usage=95))
    age(store, 1, by=HOUR + timedelta(minutes=1))
    engine.evaluate(make_snapshot(cpu_usage=99))

    assert seen == [95.0, 99.0]


# --- what stops them --------------------------------------------------------


def test_acknowledging_stops_the_reminders():
    """The point of acknowledgement, which until now changed nothing."""
    recorder = Recorder()
    store = FakeAlertStore()
    engine = engine_with(recorder, store=store)

    engine.evaluate(make_snapshot(cpu_usage=95))
    store.acknowledge(alert_id=1, username="sam", at=datetime.now(timezone.utc))
    age(store, 1, by=timedelta(days=1))
    engine.evaluate(make_snapshot(cpu_usage=95))

    assert recorder.delivered == [OPENED]


def test_an_acknowledged_alert_still_announces_its_resolution():
    """The end of an incident is news even when its start was acknowledged."""
    recorder = Recorder()
    store = FakeAlertStore()
    engine = engine_with(recorder, store=store)

    engine.evaluate(make_snapshot(cpu_usage=95))
    store.acknowledge(alert_id=1, username="sam", at=datetime.now(timezone.utc))
    engine.evaluate(make_snapshot(cpu_usage=5))

    assert recorder.delivered == [OPENED, RESOLVED]


def test_the_resolution_of_an_acknowledged_alert_is_sent_once():
    recorder = Recorder()
    store = FakeAlertStore()
    engine = engine_with(recorder, store=store)

    engine.evaluate(make_snapshot(cpu_usage=95))
    store.acknowledge(alert_id=1, username="sam", at=datetime.now(timezone.utc))
    engine.evaluate(make_snapshot(cpu_usage=5))
    engine.evaluate(make_snapshot(cpu_usage=5))

    assert recorder.delivered.count(RESOLVED) == 1


def test_a_silenced_rule_sends_no_reminders_either():
    recorder = Recorder()
    store = FakeAlertStore()
    engine = engine_with(
        recorder, silenced_until=datetime.now(timezone.utc) + timedelta(days=1),
        store=store,
    )

    engine.evaluate(make_snapshot(cpu_usage=95))
    age(store, 1, by=timedelta(days=1))
    engine.evaluate(make_snapshot(cpu_usage=95))

    assert recorder.delivered == []


# --- bookkeeping ------------------------------------------------------------


def test_the_stamp_moves_even_when_delivery_fails():
    """Otherwise a dead mail server turns a reminder into a retry loop.

    Every ten seconds, against a server that is already down.
    """
    class Broken(Notifier):
        def deliver(self, change, alert):
            raise RuntimeError("down")

    store = FakeAlertStore()
    engine = engine_with(Broken(), store=store)

    engine.evaluate(make_snapshot(cpu_usage=95))

    assert store._by_id(1).last_notified_at is not None


def test_the_summary_counts_reminders_separately():
    store = FakeAlertStore()
    engine = engine_with(Recorder(), store=store)

    engine.evaluate(make_snapshot(cpu_usage=95))
    age(store, 1, by=HOUR + timedelta(minutes=1))
    summary = engine.evaluate(make_snapshot(cpu_usage=95))

    assert summary.reminded == 1
    assert summary.opened == 0
    assert summary.still_firing == 1


def test_an_alert_with_no_stamp_falls_back_to_when_it_opened():
    """Alerts that predate this column have no last_notified_at.

    Counting from triggered_at is the closest honest answer: one opened
    moments ago is not due, and one that has been firing since last week is.
    """
    recorder = Recorder()
    store = FakeAlertStore()
    engine = engine_with(recorder, store=store)

    engine.evaluate(make_snapshot(cpu_usage=95))

    # No record of a message, and opened just now: not due.
    row = store._by_id(1)
    row.last_notified_at = None
    row.triggered_at = datetime.now(timezone.utc)
    engine.evaluate(make_snapshot(cpu_usage=95))
    assert recorder.delivered == [OPENED]

    # No record of a message, and firing since yesterday: due.
    row.last_notified_at = None
    row.triggered_at = datetime.now(timezone.utc) - timedelta(days=1)
    engine.evaluate(make_snapshot(cpu_usage=95))
    assert recorder.delivered == [OPENED, OPENED]


@pytest.mark.parametrize("hours, expected", [(0, None), (4, timedelta(hours=4))])
def test_the_setting_becomes_the_interval(hours, expected):
    from datetime import timedelta as td

    from config import Settings

    settings = Settings(notify_repeat_hours=hours)
    interval = td(hours=settings.notify_repeat_hours) if settings.notify_repeat_hours else None

    assert interval == expected
