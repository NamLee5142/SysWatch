"""Liveness and readiness are different questions.

/api/health stays true while the database is missing, the schema is behind and
no account exists. Restarting the process fixes none of those, so a supervisor
trusting it would restart forever.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import get_session
from app.db import session as db_session
from app.db.models import Base
from app.main import create_app
from app.readiness import expected_revision, readiness


@pytest.fixture
def client(auth_enabled, database, seeded_users):
    # auth_enabled, because conftest turns authentication off for the suite at
    # large and the accounts check has nothing to say when nothing logs in.
    return TestClient(create_app(), base_url="http://testserver/api")


def stamp(revision):
    """Set the recorded schema version, the way a partial upgrade would."""
    with get_session() as session:
        session.execute(text("DELETE FROM alembic_version"))
        session.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": revision}
        )


@pytest.fixture
def migrated(client):
    """A database that also carries a schema version, as a migrated one would.

    Base.metadata.create_all() builds the tables without alembic, so the
    version table has to be created by hand here.
    """
    with get_session() as session:
        session.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32))"))
    stamp(expected_revision())
    return client


# --- liveness ---------------------------------------------------------------


def test_health_is_a_literal(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_health_stays_green_with_nothing_behind_it(database):
    db_session.dispose_engine()
    db_session.init_engine("sqlite://")  # no schema at all

    alive = TestClient(create_app(), base_url="http://testserver/api")

    # It answers "did this process respond", and it did.
    assert alive.get("/health").status_code == 200


# --- readiness --------------------------------------------------------------


def test_a_working_install_is_ready(migrated):
    response = migrated.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "schema": "ok", "accounts": "ok"},
    }


def test_neither_endpoint_needs_a_session(migrated):
    # A supervisor has no session, and a check that needs one cannot be used
    # before anybody has logged in.
    assert migrated.get("/health").status_code == 200
    assert migrated.get("/ready").status_code == 200


def test_an_unmigrated_database_is_not_ready(client):
    # Tables exist (create_all made them) but alembic never ran.
    response = client.get("/ready")

    assert response.status_code == 503
    assert "alembic upgrade head" in response.json()["checks"]["schema"]


def test_a_partial_upgrade_is_not_ready(migrated):
    stamp("c69cb3ded3fd")  # the first revision, five behind

    response = migrated.get("/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["schema"] == (
        "the schema is out of date; run 'alembic upgrade head'"
    )


def test_an_install_with_no_accounts_is_not_ready(database, monkeypatch):
    monkeypatch.setenv("SYSWATCH_AUTH_ENABLED", "true")
    with get_session() as session:
        session.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32))"))
    stamp(expected_revision())

    response = TestClient(create_app(), base_url="http://testserver/api").get("/ready")

    # Migrated but never bootstrapped: the API is up and nobody on earth can
    # log in to it.
    assert response.status_code == 503
    assert "create_admin" in response.json()["checks"]["accounts"]


def test_accounts_do_not_matter_when_nothing_logs_in(migrated, monkeypatch):
    monkeypatch.setenv("SYSWATCH_AUTH_ENABLED", "false")
    with get_session() as session:
        session.execute(text("DELETE FROM users"))

    response = migrated.get("/ready")

    assert response.status_code == 200
    assert response.json()["checks"]["accounts"] == "authentication is disabled"


def test_a_missing_database_is_not_ready(database):
    db_session.dispose_engine()

    # An engine pointed at a directory that cannot hold a database.
    db_session.init_engine("sqlite:///./no-such-directory/syswatch.db")
    response = TestClient(create_app(), base_url="http://testserver/api").get("/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "the database is not reachable"

    db_session.dispose_engine()
    db_session.init_engine("sqlite://")
    Base.metadata.create_all(db_session.get_engine())


def test_every_check_runs_even_after_one_fails(client):
    ready, checks = readiness()

    # One request should report everything that is wrong, not the first thing.
    assert ready is False
    assert [check.name for check in checks] == ["database", "schema", "accounts"]


def test_the_failure_details_are_instructions_not_internals(client):
    body = client.get("/ready").json()

    # Nothing an unauthenticated caller can use, and everything an operator
    # needs to fix it.
    joined = " ".join(body["checks"].values())
    assert "Traceback" not in joined
    assert "sqlite" not in joined.lower()


def test_the_expected_revision_comes_from_the_migrations():
    # Hard-coding it would let the code and the migrations drift apart in
    # exactly the way this check exists to catch.
    assert expected_revision()
    assert len(expected_revision()) >= 8
