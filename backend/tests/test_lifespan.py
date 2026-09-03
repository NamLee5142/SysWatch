import warnings

import pytest
from fastapi.testclient import TestClient

from app.db import session as db_session
from app.main import create_app


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch):
    monkeypatch.setenv("SYSWATCH_DATABASE_URL", "sqlite://")
    db_session.dispose_engine()
    yield
    db_session.dispose_engine()


@pytest.fixture
def quiet_poller(monkeypatch):
    """Replace the agent-facing service so the poller never opens a socket.

    Alerts are switched off here: these tests exercise the poller lifecycle,
    not the engine, and the lifespan database has no schema for it to write to.
    """
    monkeypatch.setenv("SYSWATCH_ALERTS_ENABLED", "false")

    class FakeService:
        def __init__(self):
            self.calls = 0

        def get_snapshot(self):
            self.calls += 1
            return "snapshot"

    service = FakeService()
    monkeypatch.setattr("app.main.SnapshotService", lambda *args, **kwargs: service)
    return service


def test_create_poller_wires_an_engine_when_alerts_are_enabled(monkeypatch):
    from app.alerts import AlertEngine
    from app.main import create_poller
    from config import Settings

    monkeypatch.setattr("app.main.AgentClient", lambda *a, **k: object())

    assert isinstance(create_poller(Settings(alerts_enabled=True))._engine, AlertEngine)
    assert create_poller(Settings(alerts_enabled=False))._engine is None


def test_engine_is_created_on_startup(monkeypatch, quiet_poller):
    monkeypatch.setenv("SYSWATCH_POLLING_ENABLED", "false")

    with TestClient(create_app()):
        assert db_session.get_engine() is not None


def test_poller_runs_for_the_lifetime_of_the_app(quiet_poller):
    app = create_app()

    with TestClient(app):
        assert app.state.poller is not None
        assert app.state.poller.running

    # Shutdown must actually stop it; a surviving task would keep polling and
    # hold the process open.
    assert not app.state.poller.running


def test_polling_can_be_disabled(monkeypatch, quiet_poller):
    monkeypatch.setenv("SYSWATCH_POLLING_ENABLED", "false")
    app = create_app()

    with TestClient(app):
        assert app.state.poller is None


def test_poller_collects_while_the_app_runs(monkeypatch, quiet_poller):
    monkeypatch.setenv("SYSWATCH_POLL_INTERVAL_SECONDS", "0.01")
    app = create_app()

    with TestClient(app) as client:
        # Any request gives the loop a chance to tick.
        for _ in range(5):
            client.get("/api/health")

    assert quiet_poller.calls >= 1


def test_requests_still_work_during_lifespan(quiet_poller):
    with TestClient(create_app()) as client:
        assert client.get("/api/health").status_code == 200


def test_app_does_not_use_deprecated_event_handlers(quiet_poller):
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)

        # create_app() raised a DeprecationWarning for on_event before the
        # switch to lifespan; as an error it would fail here.
        create_app()
