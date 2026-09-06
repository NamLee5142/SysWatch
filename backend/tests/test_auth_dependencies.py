"""The dependencies in isolation, on a throwaway app.

Guarding the real routes is the next commit; this pins the gate itself, so a
failure there points at the policy rather than at wiring.
"""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import require_admin, require_authenticated_user
from app.auth.password import hash_password
from app.auth.service import AuthService
from app.auth.session import SESSION_COOKIE
from app.models.auth import CurrentUser
from app.repositories import UserStore

PASSWORD = "correct horse Battery staple"


@pytest.fixture(autouse=True)
def environment(monkeypatch, database):
    monkeypatch.setenv("SYSWATCH_SESSION_SECRET", "test-secret-long-enough-for-the-startup-check")
    monkeypatch.setenv("SYSWATCH_AUTH_ENABLED", "true")


@pytest.fixture
def client():
    app = FastAPI()

    @app.get("/needs-login")
    def needs_login(current: CurrentUser = Depends(require_authenticated_user)):
        return {"username": current.username, "role": current.role}

    @app.get("/needs-admin")
    def needs_admin(current: CurrentUser = Depends(require_admin)):
        return {"username": current.username, "role": current.role}

    return TestClient(app)


def session_for(role="admin", enabled=True, username="user"):
    """Create a user and return a live session token for them."""
    user = UserStore().create(
        username=username,
        password_hash=hash_password(PASSWORD),
        role=role,
        enabled=enabled,
    )
    return AuthService().create_session(user)


# --- require_authenticated_user --------------------------------------------


def test_no_cookie_is_401(client):
    assert client.get("/needs-login").status_code == 401


@pytest.mark.parametrize("token", ["", "not-a-real-token"])
def test_a_token_that_identifies_nobody_is_401(client, token):
    session_for()
    client.cookies.set(SESSION_COOKIE, token)

    assert client.get("/needs-login").status_code == 401


def test_a_valid_session_passes_through_with_its_identity(client):
    client.cookies.set(SESSION_COOKIE, session_for(role="viewer", username="viv"))

    response = client.get("/needs-login")

    assert response.status_code == 200
    assert response.json() == {"username": "viv", "role": "viewer"}


def test_every_failure_reports_the_same_thing(client):
    client.cookies.set(SESSION_COOKIE, "forged")

    body = client.get("/needs-login").json()

    # Absent, forged, expired, disabled, deleted — one 401, one message. Which
    # it was is not the caller's business.
    assert body["detail"] == "Not authenticated"


# --- require_admin ----------------------------------------------------------


def test_an_admin_reaches_an_admin_route(client):
    client.cookies.set(SESSION_COOKIE, session_for(role="admin"))

    assert client.get("/needs-admin").status_code == 200


def test_a_viewer_is_403_not_404_on_an_admin_route(client):
    client.cookies.set(SESSION_COOKIE, session_for(role="viewer"))

    response = client.get("/needs-admin")

    # 403, because the caller is authenticated and the route exists — a 404
    # here would read as a bug to someone who can GET the same resource.
    assert response.status_code == 403
    assert response.json()["detail"] == "Administrator access required"


def test_an_anonymous_caller_on_an_admin_route_is_401_not_403(client):
    # The chain runs authentication first: "who are you" before "may you".
    assert client.get("/needs-admin").status_code == 401


def test_a_viewer_still_reaches_an_authenticated_route(client):
    client.cookies.set(SESSION_COOKIE, session_for(role="viewer"))

    assert client.get("/needs-login").status_code == 200


# --- the auth_enabled bypass ------------------------------------------------


def test_disabling_auth_lets_an_anonymous_caller_through(monkeypatch, client):
    monkeypatch.setenv("SYSWATCH_AUTH_ENABLED", "false")

    response = client.get("/needs-login")

    assert response.status_code == 200
    assert response.json() == {"username": "anonymous", "role": "admin"}


def test_disabling_auth_also_opens_admin_routes(monkeypatch, client):
    monkeypatch.setenv("SYSWATCH_AUTH_ENABLED", "false")

    # Worth stating outright: this setting is not "logged in as a viewer", it
    # is "no authorization at all". It exists for local development.
    assert client.get("/needs-admin").status_code == 200


def test_the_bypass_is_off_by_default(monkeypatch, client):
    monkeypatch.delenv("SYSWATCH_AUTH_ENABLED", raising=False)

    assert client.get("/needs-login").status_code == 401
