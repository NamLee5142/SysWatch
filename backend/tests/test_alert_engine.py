from datetime import timedelta
from types import SimpleNamespace

from app.alerts.engine import AlertEngine
from alert_doubles import (
    BASE_TIME,
    FakeAlertStore,
    FakeRuleStore,
    make_snapshot,
    rule,
)


def engine_with(rules, alert_store=None):
    return AlertEngine(FakeRuleStore(*rules), alert_store or FakeAlertStore())


# --- the sequence the engine exists to protect ------------------------------


def test_five_tick_lifecycle():
    alerts = FakeAlertStore()
    engine = AlertEngine(FakeRuleStore(rule(1, "cpu", "gt", 90)), alerts)

    def tick(cpu, minutes):
        engine.evaluate(make_snapshot(cpu_usage=cpu, collected_at=BASE_TIME + timedelta(minutes=minutes)))

    tick(95, 0)
    assert len(alerts.rows) == 1
    assert alerts.rows[0].state == "firing"
    assert alerts.rows[0].value == 95

    tick(96, 1)
    assert len(alerts.rows) == 1  # same alert, not a new row
    assert alerts.rows[0].value == 96

    tick(92, 2)
    assert len(alerts.rows) == 1
    assert alerts.rows[0].value == 92
    assert alerts.rows[0].state == "firing"

    tick(80, 3)
    assert len(alerts.rows) == 1
    assert alerts.rows[0].state == "ok"
    assert alerts.rows[0].resolved_at == BASE_TIME + timedelta(minutes=3)

    tick(97, 4)
    assert len(alerts.rows) == 2  # a fresh alert, not a reopen
    assert alerts.rows[1].state == "firing"


def test_a_long_firing_stretch_is_one_row():
    alerts = FakeAlertStore()
    engine = AlertEngine(FakeRuleStore(rule(1, "cpu", "gt", 90)), alerts)

    for i in range(10):
        engine.evaluate(make_snapshot(cpu_usage=95, collected_at=BASE_TIME + timedelta(seconds=10 * i)))

    assert len(alerts.rows) == 1
    assert alerts.rows[0].last_seen_at == BASE_TIME + timedelta(seconds=90)


def test_resolved_at_is_not_moved_by_a_later_quiet_tick():
    alerts = FakeAlertStore()
    engine = AlertEngine(FakeRuleStore(rule(1, "cpu", "gt", 90)), alerts)

    engine.evaluate(make_snapshot(cpu_usage=95, collected_at=BASE_TIME))
    engine.evaluate(make_snapshot(cpu_usage=10, collected_at=BASE_TIME + timedelta(minutes=1)))
    resolved_at = alerts.rows[0].resolved_at

    engine.evaluate(make_snapshot(cpu_usage=10, collected_at=BASE_TIME + timedelta(minutes=2)))

    assert alerts.rows[0].resolved_at == resolved_at
    assert len(alerts.rows) == 1


# --- multiple rules --------------------------------------------------------


def test_each_violated_rule_gets_its_own_alert():
    alerts = FakeAlertStore()
    engine = AlertEngine(
        FakeRuleStore(rule(1, "cpu", "gt", 90), rule(2, "memory", "gt", 20)),
        alerts,
    )

    engine.evaluate(make_snapshot(cpu_usage=95, mem_used=8192))  # memory = 50%

    assert {r.rule_id for r in alerts.rows} == {1, 2}
    assert all(r.state == "firing" for r in alerts.rows)


def test_severity_is_copied_from_the_rule():
    alerts = FakeAlertStore()
    engine = AlertEngine(
        FakeRuleStore(
            rule(1, "cpu", "gt", 90, severity="warning"),
            rule(2, "cpu", "gt", 95, severity="critical"),
        ),
        alerts,
    )

    engine.evaluate(make_snapshot(cpu_usage=96))

    assert {r.rule_id: r.severity for r in alerts.rows} == {1: "warning", 2: "critical"}


def test_a_non_violated_rule_creates_nothing():
    alerts = FakeAlertStore()
    engine = AlertEngine(FakeRuleStore(rule(1, "cpu", "gt", 90)), alerts)

    engine.evaluate(make_snapshot(cpu_usage=12))

    assert alerts.rows == []


# --- disabled / deleted rules -------------------------------------------------


def test_disabling_a_rule_resolves_its_open_alert():
    alerts = FakeAlertStore()
    r = rule(1, "cpu", "gt", 90)
    rules = FakeRuleStore(r)
    engine = AlertEngine(rules, alerts)

    engine.evaluate(make_snapshot(cpu_usage=95, collected_at=BASE_TIME))
    assert alerts.rows[0].state == "firing"

    r.enabled = False
    engine.evaluate(make_snapshot(cpu_usage=95, collected_at=BASE_TIME + timedelta(minutes=1)))

    assert alerts.rows[0].state == "ok"
    assert alerts.rows[0].resolved_at == BASE_TIME + timedelta(minutes=1)


def test_a_deleted_rules_alert_is_resolved():
    alerts = FakeAlertStore()
    # An alert left firing by a rule that no longer exists (rule_id set null).
    alerts.rows.append(
        SimpleNamespace(
            id=1, rule_id=None, rule_name="gone", metric="cpu", operator="gt",
            threshold=90, severity="warning", host_name="devbox", state="firing",
            value=99, triggered_at=BASE_TIME, resolved_at=None, last_seen_at=BASE_TIME,
        )
    )
    alerts._next_id = 2
    engine = AlertEngine(FakeRuleStore(), alerts)

    engine.evaluate(make_snapshot(cpu_usage=99, collected_at=BASE_TIME + timedelta(minutes=1)))

    assert alerts.rows[0].state == "ok"


# --- absent metric --------------------------------------------------------


def test_absent_metric_neither_opens_nor_resolves():
    alerts = FakeAlertStore()
    engine = AlertEngine(FakeRuleStore(rule(1, "processes", "gt", 100)), alerts)

    engine.evaluate(make_snapshot())  # no processInfo on the snapshot

    assert alerts.rows == []


def test_absent_metric_leaves_an_open_alert_alone():
    alerts = FakeAlertStore()
    alerts.rows.append(
        SimpleNamespace(
            id=1, rule_id=1, rule_name="procs", metric="processes", operator="gt",
            threshold=100, severity="info", host_name="devbox", state="firing",
            value=250, triggered_at=BASE_TIME, resolved_at=None, last_seen_at=BASE_TIME,
        )
    )
    alerts._next_id = 2
    engine = AlertEngine(FakeRuleStore(rule(1, "processes", "gt", 100)), alerts)

    engine.evaluate(make_snapshot())  # processes metric absent

    assert alerts.rows[0].state == "firing"
    assert alerts.rows[0].resolved_at is None


# --- host isolation ------------------------------------------------------


def test_alerts_are_scoped_to_the_snapshot_host():
    alerts = FakeAlertStore()
    engine = AlertEngine(FakeRuleStore(rule(1, "cpu", "gt", 90)), alerts)

    engine.evaluate(make_snapshot(cpu_usage=95, host_name="box-a"))
    engine.evaluate(make_snapshot(cpu_usage=95, host_name="box-b"))

    assert {r.host_name for r in alerts.rows} == {"box-a", "box-b"}
    assert len(alerts.rows) == 2


# --- summary --------------------------------------------------------------


def test_summary_counts_transitions():
    alerts = FakeAlertStore()
    engine = AlertEngine(
        FakeRuleStore(rule(1, "cpu", "gt", 90), rule(2, "memory", "gt", 20)),
        alerts,
    )

    opened = engine.evaluate(make_snapshot(cpu_usage=95, mem_used=8192))
    assert (opened.opened, opened.resolved) == (2, 0)
    assert opened.changed

    steady = engine.evaluate(make_snapshot(cpu_usage=95, mem_used=8192))
    assert (steady.opened, steady.resolved, steady.still_firing) == (0, 0, 2)
    assert not steady.changed

    cleared = engine.evaluate(make_snapshot(cpu_usage=5, mem_used=1024))
    assert (cleared.opened, cleared.resolved) == (0, 2)
