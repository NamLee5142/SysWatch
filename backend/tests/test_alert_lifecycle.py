"""The alert state machine end to end: real engine, real stores, real SQLite.

test_alert_engine.py pins the engine's logic with fakes; this pins the wiring
between the engine, AlertRuleStore, AlertStore and the database — the FK, the
timestamp hydration, the "one open alert per (rule, host)" invariant in SQL.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.alerts.engine import AlertEngine
from app.db import session as db_session
from app.db.models import Base
from app.models.snapshot import Snapshot
from app.repositories import AlertRuleStore, AlertStore

BASE_TIME = datetime(2026, 8, 12, 11, 15, 27, tzinfo=timezone.utc)


@pytest.fixture
def context():
    db_session.dispose_engine()
    engine = db_session.init_engine("sqlite://")
    Base.metadata.create_all(engine)

    rules = AlertRuleStore()
    alerts = AlertStore()
    yield SimpleNamespace(
        rules=rules,
        alerts=alerts,
        engine=AlertEngine(rules, alerts),
    )

    db_session.dispose_engine()


def new_rule(name="CPU high", metric="cpu", operator="gt", threshold=90.0,
             severity="warning", enabled=True):
    return SimpleNamespace(
        name=name, metric=metric, operator=operator, threshold=threshold,
        severity=severity, enabled=enabled,
    )


def snapshot(cpu=10.0, mem_used=4096, host="devbox", minutes=0, processes=None):
    payload = {
        "collectedAt": (BASE_TIME + timedelta(minutes=minutes)).isoformat(),
        "cpuInfo": {"coreCount": 8, "usagePercent": cpu},
        "memoryInfo": {"totalMB": 16384, "usedMB": mem_used},
        "diskInfo": {"totalGB": 512, "freeGB": 120},
        "systemInfo": {"name": "Windows", "version": "11", "hostName": host},
    }
    if processes is not None:
        payload["processInfo"] = {"count": processes, "top": []}
    return Snapshot.from_payload(payload)


def test_five_tick_lifecycle(context):
    context.rules.create(new_rule(operator="gt", threshold=90))

    context.engine.evaluate(snapshot(cpu=95, minutes=0))
    firing = context.alerts.active(host_name="devbox")
    assert len(firing) == 1
    assert firing[0].value == 95
    assert firing[0].state == "firing"

    context.engine.evaluate(snapshot(cpu=96, minutes=1))
    context.engine.evaluate(snapshot(cpu=92, minutes=2))
    assert context.alerts.count() == 1  # still one row
    assert context.alerts.active("devbox")[0].value == 92

    context.engine.evaluate(snapshot(cpu=80, minutes=3))
    assert context.alerts.active("devbox") == []
    resolved = context.alerts.query(state="ok")
    assert len(resolved) == 1
    assert resolved[0].resolved_at == BASE_TIME + timedelta(minutes=3)

    context.engine.evaluate(snapshot(cpu=97, minutes=4))
    assert context.alerts.count() == 2
    assert len(context.alerts.active("devbox")) == 1


def test_a_long_firing_stretch_is_one_row(context):
    context.rules.create(new_rule(threshold=90))

    for i in range(12):
        context.engine.evaluate(snapshot(cpu=95, minutes=i))

    assert context.alerts.count() == 1
    assert context.alerts.active("devbox")[0].last_seen_at == BASE_TIME + timedelta(minutes=11)


def test_resolved_at_is_frozen_by_later_quiet_ticks(context):
    context.rules.create(new_rule(threshold=90))

    context.engine.evaluate(snapshot(cpu=95, minutes=0))
    context.engine.evaluate(snapshot(cpu=10, minutes=1))
    resolved_at = context.alerts.query(state="ok")[0].resolved_at

    context.engine.evaluate(snapshot(cpu=10, minutes=2))
    context.engine.evaluate(snapshot(cpu=10, minutes=3))

    assert context.alerts.count() == 1
    assert context.alerts.query(state="ok")[0].resolved_at == resolved_at


def test_multiple_rules_and_severities_on_one_snapshot(context):
    context.rules.create(new_rule(name="warn", metric="cpu", threshold=90, severity="warning"))
    context.rules.create(new_rule(name="crit", metric="cpu", threshold=95, severity="critical"))
    context.rules.create(new_rule(name="mem", metric="memory", threshold=20, severity="warning"))

    context.engine.evaluate(snapshot(cpu=96, mem_used=8192))  # memory = 50%

    firing = {a.rule_name: a for a in context.alerts.active("devbox")}
    assert set(firing) == {"warn", "crit", "mem"}
    assert firing["crit"].severity == "critical"
    assert firing["mem"].metric == "memory"


def test_disabling_a_rule_resolves_its_alert(context):
    created = context.rules.create(new_rule(threshold=90))

    context.engine.evaluate(snapshot(cpu=95, minutes=0))
    assert len(context.alerts.active("devbox")) == 1

    context.rules.update(created.id, {"enabled": False})
    context.engine.evaluate(snapshot(cpu=95, minutes=1))

    assert context.alerts.active("devbox") == []
    assert context.alerts.query(state="ok")[0].resolved_at == BASE_TIME + timedelta(minutes=1)


def test_deleting_a_rule_resolves_its_alert_and_nulls_the_link(context):
    created = context.rules.create(new_rule(threshold=90))
    context.engine.evaluate(snapshot(cpu=95, minutes=0))

    context.rules.delete(created.id)
    context.engine.evaluate(snapshot(cpu=95, minutes=1))

    remaining = context.alerts.query()
    assert len(remaining) == 1
    assert remaining[0].state == "ok"
    assert remaining[0].rule_id is None
    assert remaining[0].rule_name == "CPU high"  # copy survives the delete


def test_absent_metric_never_opens_an_alert(context):
    context.rules.create(new_rule(metric="processes", operator="gt", threshold=100))

    context.engine.evaluate(snapshot())  # no processInfo

    assert context.alerts.count() == 0


def test_absent_metric_leaves_an_open_alert_untouched(context):
    context.rules.create(new_rule(metric="processes", operator="gt", threshold=100))

    context.engine.evaluate(snapshot(minutes=0, processes=250))  # opens
    assert len(context.alerts.active("devbox")) == 1

    context.engine.evaluate(snapshot(minutes=1))  # processes now absent
    still = context.alerts.active("devbox")
    assert len(still) == 1
    assert still[0].resolved_at is None


def test_alerts_are_isolated_per_host(context):
    context.rules.create(new_rule(threshold=90))

    context.engine.evaluate(snapshot(cpu=95, host="box-a"))
    context.engine.evaluate(snapshot(cpu=95, host="box-b"))
    context.engine.evaluate(snapshot(cpu=10, host="box-a"))  # only box-a recovers

    assert [a.host_name for a in context.alerts.active()] == ["box-b"]
    assert context.alerts.count() == 2


def test_summary_reports_what_the_pass_did(context):
    context.rules.create(new_rule(threshold=90))

    assert context.engine.evaluate(snapshot(cpu=95)).opened == 1
    assert context.engine.evaluate(snapshot(cpu=95)).still_firing == 1
    assert context.engine.evaluate(snapshot(cpu=10)).resolved == 1
