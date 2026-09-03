import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

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


@pytest.fixture
def database():
    """A throwaway in-memory database with the full schema.

    Never the real syswatch.db: every test that touches storage goes through
    this or builds its own the same way.
    """
    db_session.dispose_engine()
    engine = db_session.init_engine("sqlite://")
    Base.metadata.create_all(engine)

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
