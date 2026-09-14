"""Alerts from a snapshot that was pushed rather than polled.

Without this, a remote host is monitored and never alerts - which is worse than
not monitoring it, because the dashboard would show it as fine.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.alerts import AlertEngine
from app.alerts.notifier import Notifier
from app.auth.agent_token import hash_token, new_token
from app.main import create_app
from app.models.alert import AlertRuleCreate
from app.repositories import AgentTokenStore, AlertRuleStore, AlertStore

SECRET = "a-deployment-secret-long-enough-to-be-real"
AT = datetime(2026, 9, 7, 11, 0, tzinfo=timezone.utc)


class Recorder(Notifier):
    def __init__(self):
        self.delivered = []

    def deliver(self, change, alert):
        self.delivered.append((change, alert.host_name))


class Broken(Notifier):
    def deliver(self, change, alert):
        raise RuntimeError("the mail server is down")


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("SYSWATCH_SESSION_SECRET", SECRET)


@pytest.fixture
def rule(database):
    return AlertRuleStore().create(
        AlertRuleCreate(
            name="CPU usage critical",
            metric="cpu",
            operator="gt",
            threshold=90.0,
            severity="critical",
        )
    )


def app_with(notifier):
    """The real app, with the engine the lifespan would have built.

    Built here rather than started through the lifespan so a test can hold the
    notifier. Everything else - the route, the dependency, the store - is the
    shipped object.
    """
    app = create_app()
    app.state.alert_engine = AlertEngine(
        AlertRuleStore(), AlertStore(), notifier=notifier
    )
    return TestClient(app, base_url="http://testserver/api")


def issue(host):
    token = new_token()
    AgentTokenStore().create(host_name=host, token_hash=hash_token(token, SECRET))
    return token


def payload(host="buildbox", at=AT, cpu=97.4):
    return {
        "collectedAt": at.isoformat().replace("+00:00", "Z"),
        "cpuInfo": {"coreCount": 8, "usagePercent": cpu},
        "memoryInfo": {"totalMB": 16384, "usedMB": 4096},
        "diskInfo": {"totalGB": 512, "freeGB": 120},
        "systemInfo": {"name": "Windows", "version": "11", "hostName": host},
    }


def push(client, token, body=None):
    return client.post(
        "/ingest/snapshot", json=body or payload(), headers={"Authorization": f"Bearer {token}"}
    )


# --- a pushed snapshot alerts ---------------------------------------------------


def test_a_rule_fires_from_a_pushed_snapshot(rule):
    """The done-when."""
    recorder = Recorder()
    client = app_with(recorder)

    response = push(client, issue("buildbox"))

    assert response.status_code == 202
    assert recorder.delivered == [("opened", "buildbox")]


def test_the_alert_is_recorded_against_the_host(rule):
    client = app_with(Recorder())

    push(client, issue("buildbox"))

    alerts = AlertStore().active("buildbox")
    assert len(alerts) == 1
    assert alerts[0].rule_name == "CPU usage critical"
    assert alerts[0].value == 97.4


def test_a_snapshot_below_the_threshold_opens_nothing(rule):
    recorder = Recorder()
    client = app_with(recorder)

    push(client, issue("buildbox"), payload(cpu=11.0))

    assert recorder.delivered == []
    assert AlertStore().active("buildbox") == []


def test_a_recovery_resolves_the_alert(rule):
    recorder = Recorder()
    client = app_with(recorder)
    token = issue("buildbox")

    push(client, token, payload(at=AT, cpu=97.4))
    push(client, token, payload(at=AT + timedelta(seconds=10), cpu=11.0))

    assert recorder.delivered == [("opened", "buildbox"), ("resolved", "buildbox")]
    assert AlertStore().active("buildbox") == []


# --- the alert belongs to the credential's host ----------------------------------


def test_the_alert_is_filed_under_the_credential_not_the_payload(rule):
    """The same forgery the row is protected from, one layer up.

    Without it a pushed snapshot is *stored* under the credential's host and
    *alerted* under whatever hostname it claimed - so one agent could open and
    resolve another machine's alerts while its own rows went elsewhere. That is
    a stranger failure than either half alone, and harder to notice.
    """
    recorder = Recorder()
    client = app_with(recorder)

    push(client, issue("buildbox"), payload(host="devbox"))

    assert recorder.delivered == [("opened", "buildbox")]
    assert AlertStore().active("buildbox") != []
    assert AlertStore().active("devbox") == []


def test_one_agent_cannot_resolve_another_hosts_alert(rule):
    """The other half: an alert opened by one host stays open.

    An agent that could clear another machine's alerts is an agent that can
    silence a real incident from a machine nobody is watching.
    """
    client = app_with(Recorder())
    buildbox, devbox = issue("buildbox"), issue("devbox")

    push(client, buildbox, payload(host="buildbox", cpu=97.4))
    # devbox reports healthy, claiming to be buildbox.
    push(client, devbox, payload(host="buildbox", cpu=5.0))

    assert AlertStore().active("buildbox") != []


# --- delivery must not reach the agent -------------------------------------------


def test_a_failed_notification_still_returns_202(rule):
    """The done-when.

    An agent that retried because delivery failed would push the same reading
    forever, and every retry would try to deliver again.
    """
    client = app_with(Broken())

    response = push(client, issue("buildbox"))

    assert response.status_code == 202
    assert AlertStore().active("buildbox") != []


def test_an_engine_that_raises_still_returns_202(rule, caplog):
    """Not just the notifier: anything the engine does."""
    client = app_with(Recorder())

    class Exploding:
        def evaluate(self, snapshot, host_name=None):
            raise RuntimeError("the database went away")

    client.app.state.alert_engine = Exploding()

    with caplog.at_level("WARNING"):
        response = push(client, issue("buildbox"))

    assert response.status_code == 202
    assert "Alert evaluation failed" in caplog.text


def test_the_snapshot_is_stored_even_when_alerting_fails(rule):
    """Storage first, alerting second. The row is the durable thing."""
    from app.repositories import SnapshotStore

    client = app_with(Broken())

    push(client, issue("buildbox"))

    assert len(SnapshotStore().query(host_name="buildbox")) == 1


# --- alerts switched off -----------------------------------------------------------


def test_no_engine_means_no_evaluation_and_no_error(rule):
    """SYSWATCH_ALERTS_ENABLED=false. Ingestion still works."""
    client = TestClient(create_app(), base_url="http://testserver/api")
    client.app.state.alert_engine = None

    assert push(client, issue("buildbox")).status_code == 202
    assert AlertStore().active("buildbox") == []


# --- retries must not re-evaluate ---------------------------------------------------


def test_a_duplicate_push_is_not_evaluated_twice(rule):
    """Work avoided, not a wrong answer prevented.

    A retried push carries the same collectedAt and the same values, so
    evaluating it again would reach the same conclusions - which is why this is
    asserted by counting calls rather than by looking for a difference in the
    result. There is no difference to look for. What it saves is a pass over
    every rule and a touch() per open alert, per retry, at the moment an agent
    is retrying because the backend is already struggling.
    """
    client = app_with(Recorder())
    token = issue("buildbox")

    class Counting:
        def __init__(self):
            self.calls = 0

        def evaluate(self, snapshot, host_name=None):
            self.calls += 1

    counting = Counting()
    client.app.state.alert_engine = counting

    push(client, token)
    push(client, token)  # the same collectedAt

    assert counting.calls == 1


# --- the poller is unaffected ---------------------------------------------------------


def test_the_poller_still_uses_the_payloads_hostname(rule):
    """evaluate() without a host keeps its old behaviour exactly."""
    from app.models.snapshot import Snapshot

    recorder = Recorder()
    engine = AlertEngine(AlertRuleStore(), AlertStore(), notifier=recorder)

    engine.evaluate(Snapshot.from_payload(payload(host="devbox")))

    assert recorder.delivered == [("opened", "devbox")]
