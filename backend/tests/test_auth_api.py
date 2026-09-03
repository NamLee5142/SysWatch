import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import auth as auth_api
from app.api.auth import SESSION_COOKIE, login_limiter
from app.auth.password import hash_password
from app.auth.rate_limit import DEFAULT_LIMIT, LoginRateLimiter
from app.db import get_session as db_scope
from app.db import session as db_session
from app.db.models import Base, SessionRecord, UserRecord
from app.main import create_app
from app.repositories import UserStore

PASSWORD = "correct horse Battery staple"


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setenv("SYSWATCH_SESSION_SECRET", "test-secret-long-enough-for-the-startup-check")
    # conftest turns authentication off for the suite at large; this file is
    # entirely about it.
    monkeypatch.setenv("SYSWATCH_AUTH_ENABLED", "true")
    monkeypatch.delenv("SYSWATCH_DEV_MODE", raising=False)

    # The limiter is process-wide, so failed logins would otherwise accumulate
    # across tests until an unrelated one started getting 429s.
    login_limiter.clear()

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


# --- rate limiting ---------------------------------------------------------


def test_repeated_failures_eventually_get_a_429(client):
    make_user()

    for _ in range(DEFAULT_LIMIT):
        assert login(client, password="wrong password").status_code == 401

    response = login(client, password="wrong password")

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    assert "Try again later" in response.json()["detail"]


def test_the_limit_blocks_the_right_password_too(client):
    make_user()

    for _ in range(DEFAULT_LIMIT):
        login(client, password="wrong password")

    # Otherwise an attacker learns they guessed right by the response changing.
    assert login(client).status_code == 429


def test_successful_logins_are_not_counted(client):
    make_user()

    for _ in range(DEFAULT_LIMIT + 5):
        assert login(client).status_code == 200


def test_a_success_clears_earlier_failures(client):
    make_user()

    for _ in range(DEFAULT_LIMIT - 1):
        login(client, password="wrong password")

    assert login(client).status_code == 200

    # The counter reset, so a forgetful user is not still one typo from lockout.
    for _ in range(DEFAULT_LIMIT - 1):
        assert login(client, password="wrong password").status_code == 401


def test_the_limiter_counts_only_failures():
    limiter = LoginRateLimiter(limit=2, window_seconds=60)

    assert limiter.retry_after("k") is None
    limiter.record_failure("k")
    assert limiter.retry_after("k") is None
    limiter.record_failure("k")

    retry_after = limiter.retry_after("k")
    assert retry_after is not None and retry_after > 0


def test_the_limiter_is_per_key():
    limiter = LoginRateLimiter(limit=1, window_seconds=60)

    limiter.record_failure("first")

    assert limiter.retry_after("first") is not None
    assert limiter.retry_after("second") is None


def test_the_window_expires():
    limiter = LoginRateLimiter(limit=1, window_seconds=0.05)

    limiter.record_failure("k")
    assert limiter.retry_after("k") is not None

    time.sleep(0.06)
    assert limiter.retry_after("k") is None


def test_resetting_a_key_forgets_its_failures():
    limiter = LoginRateLimiter(limit=1, window_seconds=60)

    limiter.record_failure("k")
    limiter.reset("k")

    assert limiter.retry_after("k") is None


# --- session lifetime through the API --------------------------------------


def expire_session_of(username):
    """Backdate a live session's expiry, the way waiting out the TTL would."""
    with db_scope() as session:
        user = session.execute(
            select(UserRecord).where(UserRecord.username == username)
        ).scalars().one()
        record = session.execute(
            select(SessionRecord).where(SessionRecord.user_id == user.id)
        ).scalars().one()
        record.expires_at = datetime(2020, 1, 1)


def test_an_expired_session_is_rejected_by_the_api(client):
    make_user()
    login(client)
    assert client.get("/auth/me").status_code == 200

    expire_session_of("admin")

    # The cookie is still in the jar and still well-formed; only the server's
    # record of it has aged out.
    assert client.get("/auth/me").status_code == 401


def test_disabling_a_user_ends_their_live_session(client):
    make_user()
    login(client)
    assert client.get("/auth/me").status_code == 200

    with db_scope() as session:
        session.execute(
            select(UserRecord).where(UserRecord.username == "admin")
        ).scalars().one().enabled = False

    # Not "on their next login" — the session they are already holding stops
    # working, which is the point of checking enabled on every request.
    assert client.get("/auth/me").status_code == 401


def test_deleting_a_user_ends_their_live_session(client):
    make_user()
    login(client)

    with db_scope() as session:
        session.delete(
            session.execute(
                select(UserRecord).where(UserRecord.username == "admin")
            ).scalars().one()
        )

    assert client.get("/auth/me").status_code == 401


def test_the_rate_limit_recovers_after_its_window(monkeypatch, client):
    # Comfortably longer than the two Argon2 verifies it takes to reach the
    # limit — a window under ~100ms expires between the attempts meant to fill
    # it, and nothing is ever limited.
    monkeypatch.setattr(
        auth_api, "login_limiter", LoginRateLimiter(limit=2, window_seconds=0.5)
    )
    make_user()

    for _ in range(2):
        assert login(client, password="wrong password").status_code == 401
    assert login(client, password="wrong password").status_code == 429

    time.sleep(0.55)

    # A lockout that never lifts is an outage, not a defence.
    assert login(client).status_code == 200
