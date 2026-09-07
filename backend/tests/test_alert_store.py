from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.repositories import AlertRuleStore, AlertStore

BASE_TIME = datetime(2026, 8, 12, 11, 15, 27, tzinfo=timezone.utc)


@pytest.fixture
def stores(database):
    return AlertRuleStore(), AlertStore()


@pytest.fixture
def rules(stores):
    return stores[0]


@pytest.fixture
def alerts(stores):
    return stores[1]


def new_rule(name="CPU high", metric="cpu", operator="gt", threshold=90.0,
             severity="warning", enabled=True):
    return SimpleNamespace(
        name=name, metric=metric, operator=operator, threshold=threshold,
        severity=severity, enabled=enabled,
    )


# --- AlertRuleStore --------------------------------------------------------


def test_create_and_get_round_trip(rules):
    created = rules.create(new_rule())

    fetched = rules.get(created.id)
    assert fetched.name == "CPU high"
    assert fetched.metric == "cpu"
    assert fetched.threshold == 90.0
    assert fetched.enabled is True


def test_timestamps_come_back_utc_aware(rules):
    created = rules.create(new_rule())

    assert created.created_at.tzinfo is not None
    assert created.created_at.utcoffset().total_seconds() == 0
    assert created.updated_at == created.created_at


def test_list_is_newest_first(rules):
    rules.create(new_rule(name="first"))
    rules.create(new_rule(name="second"))

    assert [r.name for r in rules.list()] == ["second", "first"]


def test_enabled_rules_skips_disabled(rules):
    rules.create(new_rule(name="on"))
    rules.create(new_rule(name="off", enabled=False))

    assert [r.name for r in rules.enabled_rules()] == ["on"]


def test_update_changes_fields_and_bumps_updated_at(rules):
    created = rules.create(new_rule())
    original_updated = created.updated_at

    updated = rules.update(created.id, {"threshold": 80.0, "enabled": False})

    assert updated.threshold == 80.0
    assert updated.enabled is False
    assert updated.updated_at >= original_updated
    assert updated.created_at == created.created_at


def test_update_of_a_missing_rule_returns_none(rules):
    assert rules.update(999, {"threshold": 1.0}) is None


def test_delete_reports_whether_a_row_went(rules):
    created = rules.create(new_rule())

    assert rules.delete(created.id) is True
    assert rules.delete(created.id) is False
    assert rules.get(created.id) is None


# --- AlertStore -----------------------------------------------------------


def test_open_new_copies_the_rule_identity(rules, alerts):
    rule = rules.create(new_rule(severity="critical"))

    alert = alerts.open_new(rule=rule, host_name="devbox", value=97.0, at=BASE_TIME)

    assert alert.rule_id == rule.id
    assert alert.rule_name == "CPU high"
    assert alert.metric == "cpu"
    assert alert.operator == "gt"
    assert alert.threshold == 90.0
    assert alert.severity == "critical"
    assert alert.state == "firing"
    assert alert.value == 97.0
    assert alert.triggered_at == BASE_TIME
    assert alert.resolved_at is None
    assert alert.last_seen_at == BASE_TIME


def test_open_alert_finds_the_firing_row_and_nothing_once_resolved(rules, alerts):
    rule = rules.create(new_rule())
    opened = alerts.open_new(rule=rule, host_name="devbox", value=95.0, at=BASE_TIME)

    assert alerts.open_alert(rule.id, "devbox").id == opened.id
    assert alerts.open_alert(rule.id, "other-host") is None

    alerts.resolve(alert_id=opened.id, value=50.0, at=BASE_TIME + timedelta(minutes=5))
    assert alerts.open_alert(rule.id, "devbox") is None


def test_open_alert_returns_the_newest_when_history_exists(rules, alerts):
    rule = rules.create(new_rule())
    first = alerts.open_new(rule=rule, host_name="devbox", value=95.0, at=BASE_TIME)
    alerts.resolve(alert_id=first.id, value=10.0, at=BASE_TIME + timedelta(minutes=1))
    second = alerts.open_new(
        rule=rule, host_name="devbox", value=96.0, at=BASE_TIME + timedelta(minutes=2)
    )

    assert alerts.open_alert(rule.id, "devbox").id == second.id


def test_touch_moves_only_value_and_last_seen(rules, alerts):
    rule = rules.create(new_rule())
    opened = alerts.open_new(rule=rule, host_name="devbox", value=95.0, at=BASE_TIME)

    alerts.touch(alert_id=opened.id, value=96.0, at=BASE_TIME + timedelta(minutes=1))

    row = alerts.get(opened.id)
    assert row.value == 96.0
    assert row.last_seen_at == BASE_TIME + timedelta(minutes=1)
    assert row.state == "firing"
    assert row.triggered_at == BASE_TIME
    assert row.resolved_at is None


def test_resolve_sets_state_and_resolved_at(rules, alerts):
    rule = rules.create(new_rule())
    opened = alerts.open_new(rule=rule, host_name="devbox", value=95.0, at=BASE_TIME)

    alerts.resolve(alert_id=opened.id, value=42.0, at=BASE_TIME + timedelta(minutes=3))

    row = alerts.get(opened.id)
    assert row.state == "ok"
    assert row.value == 42.0
    assert row.resolved_at == BASE_TIME + timedelta(minutes=3)


def test_active_filters_by_state_and_host(rules, alerts):
    rule = rules.create(new_rule())
    box_a = alerts.open_new(rule=rule, host_name="box-a", value=95.0, at=BASE_TIME)
    alerts.open_new(rule=rule, host_name="box-b", value=95.0, at=BASE_TIME)
    resolved = alerts.open_new(
        rule=rule, host_name="box-a", value=95.0, at=BASE_TIME - timedelta(hours=1)
    )
    alerts.resolve(alert_id=resolved.id, value=1.0, at=BASE_TIME)

    # Resolved rows are excluded; both hosts' firing rows are returned.
    assert {r.host_name for r in alerts.active()} == {"box-a", "box-b"}
    assert [r.id for r in alerts.active(host_name="box-a")] == [box_a.id]


def test_query_and_count_share_filters(rules, alerts):
    rule = rules.create(new_rule())
    for i in range(5):
        opened = alerts.open_new(
            rule=rule, host_name="devbox", value=95.0,
            at=BASE_TIME + timedelta(minutes=i),
        )
        if i % 2 == 0:
            alerts.resolve(alert_id=opened.id, value=1.0, at=BASE_TIME + timedelta(hours=1))

    assert alerts.count() == 5
    assert alerts.count(state="ok") == 3
    assert alerts.count(state="firing") == 2

    page = alerts.query(state="ok", limit=2)
    assert len(page) == 2
    # Newest first.
    assert page[0].triggered_at > page[1].triggered_at


def test_deleting_a_rule_nulls_its_alerts(rules, alerts):
    rule = rules.create(new_rule())
    opened = alerts.open_new(rule=rule, host_name="devbox", value=95.0, at=BASE_TIME)

    assert rules.delete(rule.id) is True

    orphan = alerts.get(opened.id)
    assert orphan is not None
    assert orphan.rule_id is None
    # The copied identity still describes what fired.
    assert orphan.rule_name == "CPU high"
    assert orphan.threshold == 90.0
