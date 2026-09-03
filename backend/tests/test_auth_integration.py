"""The whole authentication path, through the real stack.

The unit and route tests each pin one layer. This walks the journey an operator
actually takes — bootstrap an account with the CLI, log in, use the API, lose
the session — so that a break in the seams between those layers shows up as a
failure here rather than in production.
"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.create_admin import main as create_admin
from app.db import get_session as db_scope
from app.db.models import SessionRecord, UserRecord
from app.main import create_app

PASSWORD = "correct horse Battery staple"
DASHBOARD_ORIGIN = "http://localhost:5173"


def bootstrap(username, role="admin", password=PASSWORD):
    """Create an account the way a real install does: through the command."""
    answers = iter([password, password])
    assert create_admin(["--username", username, "--role", role], prompt=lambda _: next(answers)) == 0


def client(app):
    # https so the Secure session cookie is sent back — see conftest.
    return TestClient(app, base_url="https://testserver/api")


def sign_in(app, username, password=PASSWORD):
    session = client(app)
    response = session.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return session


def expire_every_session():
    with db_scope() as db:
        for record in db.execute(select(SessionRecord)).scalars():
            record.expires_at = datetime(2020, 1, 1)


# --- the operator's journey -------------------------------------------------


def test_an_admin_can_be_bootstrapped_and_then_use_the_api(app):
    anonymous = client(app)
    assert anonymous.get("/alerts").status_code == 401

    bootstrap("root")
    session = sign_in(app, "root")

    # The same request, now allowed.
    assert session.get("/alerts").status_code == 200
    assert session.get("/auth/me").json() == {"username": "root", "role": "admin"}

    created = session.post(
        "/alert-rules",
        json={"name": "CPU critical", "metric": "cpu", "operator": "gt", "threshold": 95},
    )
    assert created.status_code == 201
    rule_id = created.json()["id"]

    assert session.put(f"/alert-rules/{rule_id}", json={"enabled": False}).status_code == 200
    assert session.delete(f"/alert-rules/{rule_id}").status_code == 204

    session.post("/auth/logout")
    assert session.get("/alerts").status_code == 401


def test_a_viewer_can_read_but_not_change_rules(app):
    bootstrap("viv", role="viewer")
    session = sign_in(app, "viv")

    assert session.get("/alerts").status_code == 200
    assert session.get("/alert-rules").status_code == 200

    refused = session.post(
        "/alert-rules",
        json={"name": "Nope", "metric": "cpu", "operator": "gt", "threshold": 95},
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == "Administrator access required"


# --- losing the session -----------------------------------------------------


def test_a_session_that_expires_mid_flow_stops_working(app):
    bootstrap("root")
    session = sign_in(app, "root")
    assert session.get("/snapshots").status_code == 200

    expire_every_session()

    # Not just /auth/me — every protected route has to notice, since any of
    # them may be the request that discovers it.
    for path in ("/snapshots", "/alerts", "/status", "/alert-rules"):
        assert session.get(path).status_code == 401, path


def test_disabling_an_account_stops_the_session_it_already_holds(app):
    bootstrap("root")
    session = sign_in(app, "root")
    assert session.get("/alerts").status_code == 200

    with db_scope() as db:
        db.execute(select(UserRecord).where(UserRecord.username == "root")).scalars().one().enabled = False

    # Without waiting for the session to expire on its own.
    assert session.get("/alerts").status_code == 401


def test_rotating_the_session_secret_logs_everyone_out(app, monkeypatch):
    bootstrap("root")
    session = sign_in(app, "root")
    assert session.get("/alerts").status_code == 200

    monkeypatch.setenv("SYSWATCH_SESSION_SECRET", "a-completely-different-secret-value-here")

    # The stored hash is keyed by the secret, so changing it is the lever to
    # pull after a database leak.
    assert session.get("/alerts").status_code == 401


def test_two_accounts_get_separate_sessions(app):
    bootstrap("root")
    bootstrap("viv", role="viewer")

    admin = sign_in(app, "root")
    viewer = sign_in(app, "viv")

    assert admin.get("/auth/me").json()["role"] == "admin"
    assert viewer.get("/auth/me").json()["role"] == "viewer"

    admin.post("/auth/logout")

    # One logging out must not take the other with it.
    assert admin.get("/alerts").status_code == 401
    assert viewer.get("/alerts").status_code == 200


# --- what a browser needs ---------------------------------------------------


def test_the_dashboard_origin_can_send_credentials(auth_enabled, database, monkeypatch):
    # Only a deployment that serves the dashboard from another origin needs
    # this, so it has to be configured before the app reads it.
    monkeypatch.setenv("SYSWATCH_CORS_ORIGINS", DASHBOARD_ORIGIN)
    app = create_app()

    response = client(app).options(
        "/alerts",
        headers={"Origin": DASHBOARD_ORIGIN, "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == DASHBOARD_ORIGIN
    # Without this the browser drops the session cookie and every request looks
    # anonymous no matter how many times someone logs in.
    assert response.headers["access-control-allow-credentials"] == "true"


def test_an_unknown_origin_cannot(auth_enabled, database, monkeypatch):
    monkeypatch.setenv("SYSWATCH_CORS_ORIGINS", DASHBOARD_ORIGIN)
    app = create_app()

    response = client(app).options(
        "/alerts",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )

    assert "access-control-allow-origin" not in response.headers


def test_health_never_needed_a_session(app):
    assert client(app).get("/health").status_code == 200
