"""An alert that does not close the instant the metric dips under the line.

Found on the first sustained run of a real agent against a real backend: a rule
at 90% and a machine whose memory sat at 90.2 then 89.9 then 90.4 opened and
resolved the same alert five times in three minutes. With mail configured that
is ten messages about one condition that never really changed, and the tenth is
the one nobody reads.

So a resolution waits until the metric has been clear for a while. Opening is
unchanged and immediate: a delay there would be a delay in hearing about a real
incident, which is a different and worse trade.
"""
from datetime import datetime, timedelta, timezone

import pytest
from alert_doubles import FakeAlertStore, FakeRuleStore, make_snapshot, rule

from app.alerts import AlertEngine
from app.alerts.notifier import OPENED, RESOLVED, Notifier

BASE = datetime(2026, 9, 8, 11, 0, tzinfo=timezone.utc)
SETTLE = timedelta(minutes=2)


class Recorder(Notifier):
    def __init__(self):
        self.delivered = []

    def deliver(self, change, alert):
        self.delivered.append(change)


def engine_with(recorder, resolve_after=SETTLE, store=None):
    return AlertEngine(
        FakeRuleStore(rule(id=1, metric="memory", operator="gt", threshold=90.0)),
        store or FakeAlertStore(),
        notifier=recorder,
        resolve_after=resolve_after,
    )


def reading(percent, seconds):
    """A snapshot whose memory is `percent` of 16 GB, at BASE + seconds."""
    return make_snapshot(
        mem_used=int(16384 * percent / 100), collected_at=BASE + timedelta(seconds=seconds)
    )


# --- the flap ----------------------------------------------------------------


def test_a_metric_oscillating_at_the_threshold_alerts_once():
    """The observed failure, as a test.

    Six readings either side of 90%, thirty seconds apart. Before this the
    engine announced four state changes; now it announces one.
    """
    recorder = Recorder()
    engine = engine_with(recorder)

    for index, percent in enumerate([91.0, 89.8, 90.4, 89.7, 90.6, 89.9]):
        engine.evaluate(reading(percent, index * 30))

    assert recorder.delivered == [OPENED]


def test_a_dip_under_the_line_does_not_resolve_it():
    recorder = Recorder()
    store = FakeAlertStore()
    engine = engine_with(recorder, store=store)

    engine.evaluate(reading(91.0, 0))
    engine.evaluate(reading(89.0, 30))

    assert recorder.delivered == [OPENED]
    assert len(store.active("devbox")) == 1


def test_a_dip_that_lasts_does_resolve_it():
    """The point is to delay a resolution, not to prevent one."""
    recorder = Recorder()
    engine = engine_with(recorder)

    engine.evaluate(reading(91.0, 0))
    engine.evaluate(reading(89.0, 30))
    engine.evaluate(reading(89.0, 30 + int(SETTLE.total_seconds())))

    assert recorder.delivered == [OPENED, RESOLVED]


def test_the_clock_starts_at_the_first_clear_reading_not_the_last():
    """Otherwise a metric reporting clear on every tick restarts its own
    countdown forever and the alert never closes."""
    recorder = Recorder()
    engine = engine_with(recorder)

    engine.evaluate(reading(91.0, 0))
    for second in range(30, 30 + int(SETTLE.total_seconds()) + 10, 10):
        engine.evaluate(reading(88.0, second))

    assert recorder.delivered == [OPENED, RESOLVED]


def test_a_breach_inside_the_window_cancels_the_countdown():
    recorder = Recorder()
    store = FakeAlertStore()
    engine = engine_with(recorder, store=store)

    engine.evaluate(reading(91.0, 0))
    engine.evaluate(reading(89.0, 30))  # clearing starts
    engine.evaluate(reading(91.0, 60))  # back over: cancelled

    assert store._by_id(1).clearing_since is None

    # A clear reading now starts a fresh window rather than inheriting the old.
    engine.evaluate(reading(89.0, 90))
    assert recorder.delivered == [OPENED]


def test_the_countdown_is_measured_from_the_snapshot_not_the_wall_clock():
    """The engine has to reach the same conclusion replaying readings as live."""
    recorder = Recorder()
    engine = engine_with(recorder)

    # Two readings a year apart in snapshot time, evaluated milliseconds apart.
    engine.evaluate(reading(91.0, 0))
    engine.evaluate(reading(89.0, 30))
    engine.evaluate(reading(89.0, 60 * 60 * 24 * 365))

    assert recorder.delivered == [OPENED, RESOLVED]


# --- what it must not change --------------------------------------------------


def test_opening_is_still_immediate():
    """A delay here would delay hearing about a real incident."""
    recorder = Recorder()

    engine_with(recorder).evaluate(reading(95.0, 0))

    assert recorder.delivered == [OPENED]


def test_zero_restores_the_old_behaviour():
    """A deployment that wants resolve-on-first-clear can have it back."""
    recorder = Recorder()
    engine = engine_with(recorder, resolve_after=None)

    engine.evaluate(reading(91.0, 0))
    engine.evaluate(reading(89.0, 30))

    assert recorder.delivered == [OPENED, RESOLVED]


def test_a_still_clearing_alert_counts_as_firing_in_the_summary():
    """It is still open, so the summary must not call it resolved.

    The poller logs this line, and a summary that said "1 resolved" while the
    row stayed open would make the log disagree with the dashboard.
    """
    engine = engine_with(Recorder())

    engine.evaluate(reading(91.0, 0))
    summary = engine.evaluate(reading(89.0, 30))

    assert summary.resolved == 0
    assert summary.still_firing == 1


def test_a_missing_metric_is_not_a_recovery():
    """Unchanged: absent data is not the same as data that says fine."""
    recorder = Recorder()
    store = FakeAlertStore()
    engine = engine_with(recorder, store=store)

    engine.evaluate(reading(91.0, 0))
    engine.evaluate(make_snapshot(mem_used=0, collected_at=BASE + timedelta(seconds=30)))

    assert len(store.active("devbox")) == 1


def test_a_silenced_rule_still_says_nothing_when_it_finally_resolves():
    recorder = Recorder()
    engine = AlertEngine(
        FakeRuleStore(
            rule(
                id=1,
                metric="memory",
                operator="gt",
                threshold=90.0,
                silenced_until=datetime.now(timezone.utc) + timedelta(days=1),
            )
        ),
        FakeAlertStore(),
        notifier=recorder,
        resolve_after=SETTLE,
    )

    engine.evaluate(reading(91.0, 0))
    engine.evaluate(reading(89.0, 30))
    engine.evaluate(reading(89.0, 30 + int(SETTLE.total_seconds())))

    assert recorder.delivered == []


# --- the store ----------------------------------------------------------------


@pytest.fixture
def firing(database):
    from app.models.alert import AlertRuleCreate
    from app.repositories import AlertRuleStore, AlertStore

    made = AlertRuleStore().create(
        AlertRuleCreate(name="Memory high", metric="memory", operator="gt", threshold=90.0)
    )
    return AlertStore().open_new(rule=made, host_name="devbox", value=91.0, at=BASE)


def test_a_new_alert_is_not_clearing(firing):
    assert firing.clearing_since is None


def test_marking_clearing_records_when(firing):
    from app.repositories import AlertStore

    marked = AlertStore().mark_clearing(alert_id=firing.id, at=BASE)

    assert marked.clearing_since == BASE


def test_marking_clearing_twice_keeps_the_first_time(firing):
    """The WHERE clause, and the reason for it: a countdown that restarts on
    every clear reading never reaches its end."""
    from app.repositories import AlertStore

    store = AlertStore()
    store.mark_clearing(alert_id=firing.id, at=BASE)

    later = store.mark_clearing(alert_id=firing.id, at=BASE + timedelta(minutes=5))

    assert later.clearing_since == BASE


def test_marking_breaching_clears_it(firing):
    from app.repositories import AlertStore

    store = AlertStore()
    store.mark_clearing(alert_id=firing.id, at=BASE)

    store.mark_breaching(alert_id=firing.id)

    assert store.get(firing.id).clearing_since is None


def test_the_timestamp_comes_back_utc_aware(firing):
    from app.repositories import AlertStore

    store = AlertStore()
    store.mark_clearing(alert_id=firing.id, at=BASE)

    assert store.get(firing.id).clearing_since.tzinfo is not None
