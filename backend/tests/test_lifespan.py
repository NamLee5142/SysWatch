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

    dev_mode, because these enter the lifespan with authentication disabled and
    that is now fatal anywhere else.
    """
    monkeypatch.setenv("SYSWATCH_ALERTS_ENABLED", "false")
    monkeypatch.setenv("SYSWATCH_DEV_MODE", "true")

    class FakeService:
        def __init__(self):
            self.calls = 0

        def get_snapshot(self):
            self.calls += 1
            return "snapshot"

    service = FakeService()
    monkeypatch.setattr("app.main.SnapshotService", lambda *args, **kwargs: service)
    return service


def test_the_alert_engine_exists_only_when_alerts_are_enabled():
    from app.alerts import AlertEngine
    from app.main import create_alert_engine
    from config import Settings

    assert isinstance(create_alert_engine(Settings(alerts_enabled=True)), AlertEngine)
    assert create_alert_engine(Settings(alerts_enabled=False)) is None


def test_create_poller_uses_the_engine_it_is_given(monkeypatch):
    """Construction moved out of create_poller when ingestion needed one too."""
    from app.main import create_poller
    from config import Settings

    monkeypatch.setattr("app.main.AgentClient", lambda *a, **k: object())
    engine = object()

    assert create_poller(Settings(), engine=engine)._engine is engine
    assert create_poller(Settings())._engine is None


def test_the_poller_and_the_ingestion_endpoint_share_one_engine(monkeypatch, quiet_poller):
    """One engine for the process, not one per path.

    Two would mean two sets of notifiers, so the reminder interval would be
    tracked separately and an alert could be announced once per path - by the
    poller for the local agent and again by ingestion for a pushed one.
    """
    # quiet_poller switches alerts off for the lifecycle tests. This one is
    # about the wiring, and building an engine touches no schema.
    monkeypatch.setenv("SYSWATCH_ALERTS_ENABLED", "true")
    app = create_app()

    with TestClient(app):
        assert app.state.alert_engine is not None
        assert app.state.poller._engine is app.state.alert_engine


def test_no_engine_reaches_either_path_when_alerts_are_disabled(monkeypatch, quiet_poller):
    monkeypatch.setenv("SYSWATCH_ALERTS_ENABLED", "false")
    app = create_app()

    with TestClient(app):
        assert app.state.alert_engine is None
        assert app.state.poller._engine is None


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
