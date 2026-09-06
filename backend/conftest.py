import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Before importing anything that reads settings.
#
# The installer sets SYSWATCH_CONFIG_FILE for the machine, and points it at a
# file readable by Administrators and SYSTEM only. Any test module that builds
# an app at import - several do - would then read it, and on a developer
# machine with SysWatch installed the whole suite died with PermissionError
# during collection. The autouse fixture below says the same thing, but a
# fixture cannot run before the module it protects is imported.
os.environ["SYSWATCH_CONFIG_FILE"] = str(ROOT / "no-such-config.env")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.auth.password import hash_password  # noqa: E402
from app.auth.session import SESSION_COOKIE  # noqa: E402
from app.db import session as db_session  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.main import create_app  # noqa: E402
from app.repositories import UserStore  # noqa: E402

TEST_PASSWORD = "correct horse Battery staple"
ADMIN_USERNAME = "test-admin"
VIEWER_USERNAME = "test-viewer"

# Any test asking for one of these is exercising authentication or
# authorization, so the autouse fixture below leaves the setting alone for it.
AUTHENTICATED_FIXTURES = {"anon_client", "viewer_client", "admin_client", "auth_enabled"}


@pytest.fixture(autouse=True)
def no_local_config_file(monkeypatch, tmp_path):
    """Keep a developer's own syswatch.env out of the suite.

    Settings read a config file now. One sitting in backend/ would quietly
    change what the tests are testing, and only on that machine.
    """
    monkeypatch.setenv("SYSWATCH_CONFIG_FILE", str(tmp_path / "no-such-config.env"))


@pytest.fixture(autouse=True)
def default_auth_disabled(request, monkeypatch):
    """Run the suite with authentication off unless a test asks otherwise.

    Sprint 9 puts every operational route behind a session. The several hundred
    tests written before it are about snapshots, alerts and the poller, not
    about who is logged in, and threading a cookie through all of them would
    add noise to each without testing anything the dedicated authorization
    tests do not cover directly.

    Turning it off here rather than editing those tests keeps them about their
    own subject, and the routes still run their real dependency chain — it just
    resolves to the anonymous admin. Tests that take `auth_enabled`, or any of
    the client fixtures below, get the real thing.
    """
    if AUTHENTICATED_FIXTURES & set(request.fixturenames):
        return

    monkeypatch.setenv("SYSWATCH_AUTH_ENABLED", "false")


@pytest.fixture
def auth_enabled(monkeypatch):
    """Opt back in to real authentication, with a secret to sign sessions."""
    monkeypatch.setenv("SYSWATCH_AUTH_ENABLED", "true")
    monkeypatch.setenv("SYSWATCH_SESSION_SECRET", "test-secret-long-enough-for-the-startup-check")
    monkeypatch.delenv("SYSWATCH_DEV_MODE", raising=False)


# What the suite runs against. SQLite unless told otherwise, because SQLite is
# what ships and what every developer already has.
#
# The other value this takes is a PostgreSQL URL, set by one CI job. Sprint 10
# claimed the repository layer keeps PostgreSQL a configuration change; that
# claim had never been executed. It is a test target, not a supported
# deployment - see docs/deployment.md, which documents SQLite and only SQLite.
TEST_DATABASE_URL = os.environ.get("SYSWATCH_TEST_DATABASE_URL", "sqlite://")


_schema_built = False


def start_test_database():
    """A throwaway database with the full schema. Returns the engine.

    Never the real syswatch.db: every test that touches storage comes through
    here.

    Emptying it is free on SQLite and is not free anywhere else. An in-memory
    SQLite database ceases to exist when its engine is disposed, so each test
    starts clean by construction. A server keeps whatever the last test left -
    including the sequences behind the ids that assertions spell out as 1 and
    2 - so it has to be emptied explicitly, and doing that with DDL per test
    costs more than the tests do: a full drop and rebuild of every table ran
    the suite roughly six times slower than one TRUNCATE ... RESTART IDENTITY.
    """
    global _schema_built

    db_session.dispose_engine()
    engine = db_session.init_engine(TEST_DATABASE_URL)

    if TEST_DATABASE_URL.startswith("sqlite"):
        Base.metadata.create_all(engine)
        return engine

    if not _schema_built:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        _schema_built = True

    _truncate_everything(engine)
    return engine


def _truncate_everything(engine):
    """Empty every table and reset every sequence, in one statement.

    CASCADE because the tables reference each other; RESTART IDENTITY because
    a test that asserts an id is 1 is asserting about a fresh database, which
    is what it would get on SQLite.

    alembic_version is dropped rather than truncated because it is not in
    Base.metadata at all - alembic owns it, and test_readiness.py creates it by
    hand to describe a migrated database. On SQLite it disappears with the
    in-memory database it was made in. Left standing on a server it makes the
    next test's readiness check report a schema version nobody stamped, which
    is how "an unmigrated database is not ready" came back 200.
    """
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def database():
    engine = start_test_database()

    yield engine

    db_session.dispose_engine()


@pytest.fixture
def seeded_users(database):
    """One admin and one viewer, both with TEST_PASSWORD."""
    store = UserStore()
    return {
        "admin": store.create(
            username=ADMIN_USERNAME,
            password_hash=hash_password(TEST_PASSWORD),
            role="admin",
        ),
        "viewer": store.create(
            username=VIEWER_USERNAME,
            password_hash=hash_password(TEST_PASSWORD),
            role="viewer",
        ),
    }


@pytest.fixture
def app(auth_enabled, database):
    # Built per test rather than at import, so a monkeypatched setting is in
    # place before create_app() reads it.
    return create_app()


def _client(app):
    # https, because outside dev_mode the session cookie carries Secure and
    # neither a browser nor httpx's jar will send it back over plain HTTP.
    # Testing over http would quietly exercise a no-cookie path instead.
    return TestClient(app, base_url="https://testserver/api")


def _logged_in(app, username):
    client = _client(app)
    response = client.post(
        "/auth/login", json={"username": username, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, f"fixture login failed: {response.text}"
    assert client.cookies.get(SESSION_COOKIE)
    return client


@pytest.fixture
def anon_client(app, seeded_users):
    """Authentication is on and this caller has no session."""
    return _client(app)


@pytest.fixture
def admin_client(app, seeded_users):
    return _logged_in(app, ADMIN_USERNAME)


@pytest.fixture
def viewer_client(app, seeded_users):
    return _logged_in(app, VIEWER_USERNAME)
