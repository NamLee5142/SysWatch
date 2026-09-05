from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db import session as db_session
from app.db.models import Base
from app.main import create_app
from app.repositories import AlertRuleStore, AlertStore

BASE_TIME = datetime(2026, 8, 25, 10, 0, 0, tzinfo=timezone.utc)

app = create_app()
client = TestClient(app, base_url="http://testserver/api")


@pytest.fixture(autouse=True)
def stores():
    db_session.dispose_engine()
    engine = db_session.init_engine("sqlite://")
    Base.metadata.create_all(engine)

    yield AlertRuleStore(), AlertStore()

    db_session.dispose_engine()


def make_rule(stores, name="CPU high", metric="cpu", operator="gt", threshold=90.0, severity="warning"):
    return stores[0].create(
        SimpleNamespace(
            name=name, metric=metric, operator=operator, threshold=threshold,
            severity=severity, enabled=True,
        )
    )


def open_alert(stores, rule, host="devbox", minutes=0, value=95.0, resolved=False):
    at = BASE_TIME + timedelta(minutes=minutes)
    alert = stores[1].open_new(rule=rule, host_name=host, value=value, at=at)
    if resolved:
        stores[1].resolve(alert_id=alert.id, value=10.0, at=at + timedelta(minutes=1))
    return alert


def test_no_alerts_is_an_empty_page(stores):
    response = client.get("/alerts")

    assert response.status_code == 200
    assert response.json() == {"items": [], "count": 0}


def test_active_lists_only_firing_alerts(stores):
    rule = make_rule(stores)
    open_alert(stores, rule, minutes=0)
    open_alert(stores, rule, host="other", minutes=1, resolved=True)

    body = client.get("/alerts/active").json()

    assert len(body["items"]) == 1
    assert body["items"][0]["state"] == "firing"
    assert body["items"][0]["ruleName"] == "CPU high"


def test_active_can_filter_by_host(stores):
    rule = make_rule(stores)
    open_alert(stores, rule, host="box-a")
    open_alert(stores, rule, host="box-b")

    items = client.get("/alerts/active", params={"host": "box-a"}).json()["items"]

    assert [a["hostName"] for a in items] == ["box-a"]


def test_alerts_history_includes_resolved_and_reports_count(stores):
    rule = make_rule(stores)
    for i in range(3):
        open_alert(stores, rule, minutes=i, resolved=True)
    open_alert(stores, rule, minutes=10)

    body = client.get("/alerts", params={"limit": 2}).json()

    assert body["count"] == 4
    assert len(body["items"]) == 2
    # Newest first.
    assert body["items"][0]["triggeredAt"] > body["items"][1]["triggeredAt"]


def test_alerts_filter_by_state(stores):
    rule = make_rule(stores)
    open_alert(stores, rule, minutes=0)
    open_alert(stores, rule, minutes=1, resolved=True)

    assert client.get("/alerts", params={"state": "firing"}).json()["count"] == 1
    assert client.get("/alerts", params={"state": "ok"}).json()["count"] == 1


def test_alerts_reject_an_unknown_state(stores):
    assert client.get("/alerts", params={"state": "exploded"}).status_code == 422


def test_alerts_filter_by_rule_id(stores):
    cpu = make_rule(stores, name="cpu")
    mem = make_rule(stores, name="mem", metric="memory")
    open_alert(stores, cpu)
    open_alert(stores, mem)

    body = client.get("/alerts", params={"rule_id": cpu.id}).json()

    assert [a["ruleName"] for a in body["items"]] == ["cpu"]


def test_alerts_reject_an_inverted_window(stores):
    response = client.get(
        "/alerts",
        params={"since": "2026-08-26T00:00:00Z", "until": "2026-08-25T00:00:00Z"},
    )

    assert response.status_code == 422
    assert "since must not be after until" in response.json()["detail"]


def test_get_one_alert(stores):
    rule = make_rule(stores)
    alert = open_alert(stores, rule)

    body = client.get(f"/alerts/{alert.id}").json()

    assert body["id"] == alert.id
    assert body["threshold"] == 90.0
    assert body["resolvedAt"] is None


def test_get_a_missing_alert_is_404(stores):
    response = client.get("/alerts/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "No alert with that id"


def test_active_route_is_not_shadowed_by_the_id_route(stores):
    # /alerts/active must resolve to the list, not be parsed as id="active".
    assert client.get("/alerts/active").status_code == 200


def test_timestamps_are_utc_tagged(stores):
    rule = make_rule(stores)
    open_alert(stores, rule)

    triggered_at = client.get("/alerts/active").json()["items"][0]["triggeredAt"]

    assert triggered_at.endswith("Z")
