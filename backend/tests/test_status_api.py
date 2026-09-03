import asyncio

import pytest
from fastapi.testclient import TestClient

from app.client.errors import AgentConnectionError
from app.db import session as db_session
from app.main import create_app
from app.services.snapshot_poller import SnapshotPoller


class FakeService:
    """Stands in for the agent-facing service, one poll at a time."""

    def __init__(self):
        self.outcome = "ok"

    def get_snapshot(self):
        if self.outcome == "ok":
            return "snapshot"
        if self.outcome == "empty":
            raise LookupError("agent has not collected yet")
        raise AgentConnectionError("connection refused")


@pytest.fixture
def service():
    return FakeService()


@pytest.fixture
def poller(service):
    # A long interval so the loop never ticks on its own: every test drives
    # poll_once() itself and knows exactly which state it is asserting on.
    return SnapshotPoller(service, interval_seconds=3600)


@pytest.fixture
def client(poller):
    app = create_app()
    app.state.poller = poller
    return TestClient(app, base_url="http://testserver/api")


def tick(poller):
    asyncio.run(poller.poll_once())


def test_status_is_unknown_before_the_first_poll(client):
    body = client.get("/status").json()

    # Not "down": nothing has been tried yet, and a red light on a healthy
    # agent is worse than admitting ignorance.
    assert body["agent"] == "unknown"
    assert body["lastPollAt"] is None
    assert body["lastSuccessAt"] is None
    assert body["lastPollError"] is None


def test_status_is_up_after_a_successful_poll(client, poller):
    tick(poller)

    body = client.get("/status").json()

    assert body["agent"] == "up"
    assert body["lastPollError"] is None
    assert body["lastSuccessAt"] is not None


def test_status_is_down_when_the_agent_is_unreachable(client, poller, service):
    service.outcome = "unreachable"
    tick(poller)

    body = client.get("/status").json()

    assert body["agent"] == "down"
    assert "AgentConnectionError" in body["lastPollError"]


def test_failure_keeps_the_last_successful_collection_time(client, poller, service):
    tick(poller)
    collected_at = client.get("/status").json()["lastSuccessAt"]

    service.outcome = "unreachable"
    tick(poller)
    body = client.get("/status").json()

    # The gap between these two is what tells a dashboard how stale it is.
    assert body["lastSuccessAt"] == collected_at
    assert body["lastPollAt"] != collected_at


def test_agent_with_nothing_collected_yet_is_still_up(client, poller, service):
    service.outcome = "empty"
    tick(poller)

    body = client.get("/status").json()

    # The agent answered; it just has no snapshot. That is a reachable agent.
    assert body["agent"] == "up"
    assert body["lastPollError"] is None
    assert body["lastSuccessAt"] is None


def test_status_recovers_when_the_agent_comes_back(client, poller, service):
    service.outcome = "unreachable"
    tick(poller)
    assert client.get("/status").json()["agent"] == "down"

    service.outcome = "ok"
    tick(poller)
    body = client.get("/status").json()

    assert body["agent"] == "up"
    assert body["lastPollError"] is None


def test_status_answers_200_even_when_the_agent_is_down(client, poller, service):
    service.outcome = "unreachable"
    tick(poller)

    response = client.get("/status")

    # A 503 here would leave the dashboard unable to tell "agent unreachable"
    # from "backend unreachable", which need different messages on screen.
    assert response.status_code == 200
    assert response.json()["backend"] == "ok"


def test_status_reports_whether_the_poller_is_running(client, poller):
    assert client.get("/status").json()["pollerRunning"] is False


def test_status_survives_an_app_without_a_poller():
    # Nothing has set app.state.poller, which is the case whenever the lifespan
    # has not run.
    body = TestClient(create_app(), base_url="http://testserver/api").get("/status").json()

    assert body["agent"] == "unknown"
    assert body["pollerRunning"] is False


def test_status_reports_unknown_when_polling_is_disabled(monkeypatch):
    monkeypatch.setenv("SYSWATCH_POLLING_ENABLED", "false")
    monkeypatch.setenv("SYSWATCH_DATABASE_URL", "sqlite://")
    db_session.dispose_engine()

    app = create_app()
    with TestClient(app, base_url="http://testserver/api") as started:
        body = started.get("/status").json()

    db_session.dispose_engine()

    # Nothing is watching the agent, so the backend genuinely does not know.
    assert app.state.poller is None
    assert body["agent"] == "unknown"
    assert body["pollerRunning"] is False
