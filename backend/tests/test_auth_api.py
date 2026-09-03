import pytest
from fastapi.testclient import TestClient

from app.api.auth import SESSION_COOKIE
from app.auth.password import hash_password
from app.db import session as db_session
from app.db.models import Base
from app.main import create_app
from app.repositories import UserStore

PASSWORD = "correct horse Battery staple"


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setenv("SYSWATCH_SESSION_SECRET", "test-secret")
    monkeypatch.delenv("SYSWATCH_DEV_MODE", raising=False)

    db_session.dispose_engine()
    engine = db_session.init_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield
    db_session.dispose_engine()


@pytest.fixture
def client():
    # Built per test rather than at import, so a monkeypatched setting is in
    # place before create_app() reads it.
    #
    # https, because outside dev_mode the session cookie carries Secure and a
    # browser — or httpx's cookie jar — will not send it back over plain HTTP.
    # Testing over http would quietly exercise a no-cookie path instead.
    return TestClient(create_app(), base_url="https://testserver")


def make_user(username="admin", password=PASSWORD, role="admin", enabled=True):
    return UserStore().create(
        username=username,
        password_hash=hash_password(password),
        role=role,
        enabled=enabled,
    )


def login(client, username="admin", password=PASSWORD):
    return client.post("/auth/login", json={"username": username, "password": password})


# --- login -----------------------------------------------------------------


def test_valid_credentials_return_the_user_and_set_a_cookie(client):
    make_user(role="viewer")

    response = login(client)

    assert response.status_code == 200
    assert response.json() == {"username": "admin", "role": "viewer"}
    assert client.cookies.get(SESSION_COOKIE)


def test_the_login_body_carries_nothing_but_identity(client):
    make_user()

    body = login(client).json()

    # No hash, no id, no settings — CurrentUser has no field they could use.
    assert set(body) == {"username", "role"}


def test_the_session_cookie_is_httponly_secure_and_lax(client):
    make_user()

    header = login(client).headers["set-cookie"]

    assert "HttpOnly" in header
    assert "Secure" in header
    assert "SameSite=lax" in header
    assert "Path=/" in header
    # A Domain attribute would break the development proxy, which rewrites the
    # origin, and would widen the cookie beyond the host that issued it.
    assert "Domain" not in header


def test_the_cookie_drops_its_secure_flag_in_dev_mode(monkeypatch):
    monkeypatch.setenv("SYSWATCH_DEV_MODE", "true")
    client = TestClient(create_app())
    make_user()

    header = login(client).headers["set-cookie"]

    # The dashboard is served over plain HTTP in development; a Secure cookie
    # would never come back.
    assert "Secure" not in header
    assert "HttpOnly" in header


@pytest.mark.parametrize(
    "username, password",
    [
        ("admin", "the wrong password"),
        ("nobody", PASSWORD),
        ("nobody", "the wrong password"),
    ],
)
def test_every_failure_looks_identical(client, username, password):
    make_user()

    response = login(client, username, password)

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password"
    assert SESSION_COOKIE not in response.cookies


def test_a_disabled_account_cannot_log_in(client):
    make_user(enabled=False)

    response = login(client)

    # Same message again: that the account exists is not the caller's business.
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password"


@pytest.mark.parametrize(
    "body",
    [
        {"username": "   ", "password": PASSWORD},
        {"username": "admin"},
        {"password": PASSWORD},
        {"username": "admin", "password": ""},
    ],
)
def test_a_malformed_login_is_422_not_401(client, body):
    assert client.post("/auth/login", json=body).status_code == 422


# --- me --------------------------------------------------------------------


def test_me_is_401_without_a_session(client):
    make_user()

    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


def test_me_reports_the_logged_in_user(client):
    make_user(role="viewer")
    login(client)

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json() == {"username": "admin", "role": "viewer"}


def test_me_rejects_a_forged_cookie(client):
    make_user()
    client.cookies.set(SESSION_COOKIE, "not-a-real-token")

    assert client.get("/auth/me").status_code == 401


# --- logout ----------------------------------------------------------------


def test_logout_ends_the_session_and_clears_the_cookie(client):
    make_user()
    login(client)
    assert client.get("/auth/me").status_code == 200

    response = client.post("/auth/logout")

    assert response.status_code == 204
    assert "syswatch_session=" in response.headers["set-cookie"]
    assert client.get("/auth/me").status_code == 401


def test_logging_out_twice_is_still_204(client):
    make_user()
    login(client)

    assert client.post("/auth/logout").status_code == 204
    # Idempotent: reporting "there was nothing to revoke" would confirm whether
    # a token was live.
    assert client.post("/auth/logout").status_code == 204


def test_logout_without_a_session_is_204(client):
    assert client.post("/auth/logout").status_code == 204


def test_a_revoked_session_cannot_be_replayed(client):
    make_user()
    login(client)
    token = client.cookies.get(SESSION_COOKIE)

    client.post("/auth/logout")

    # The cookie value still exists in the caller's hands; the server must no
    # longer honour it.
    client.cookies.set(SESSION_COOKIE, token)
    assert client.get("/auth/me").status_code == 401


# --- reachability ----------------------------------------------------------


def test_the_auth_routes_do_not_require_a_session_to_reach(client):
    # /auth is where a caller with no session goes to get one, so it must sit
    # outside whatever protects everything else.
    assert client.post("/auth/login", json={"username": "a", "password": "b"}).status_code == 401
    assert client.get("/auth/me").status_code == 401
