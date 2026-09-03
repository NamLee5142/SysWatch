import statistics
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.auth.password import hash_password
from app.auth.service import AuthService
from app.auth.session import hash_token, new_token
from app.db import get_session as db_scope
from app.db import session as db_session
from app.db.models import Base, SessionRecord
from app.repositories import SessionStore, UserStore

SECRET = "test-secret-not-a-real-one"
PASSWORD = "correct horse Battery staple"


@pytest.fixture
def auth():
    db_session.dispose_engine()
    engine = db_session.init_engine("sqlite://")
    Base.metadata.create_all(engine)

    yield AuthService(secret=SECRET, ttl_seconds=3600)

    db_session.dispose_engine()


def make_user(username="admin", password=PASSWORD, role="admin", enabled=True):
    return UserStore().create(
        username=username,
        password_hash=hash_password(password),
        role=role,
        enabled=enabled,
    )


def stored_token_hashes():
    with db_scope() as session:
        return session.execute(select(SessionRecord.token_hash)).scalars().all()


# --- token primitives ------------------------------------------------------


def test_tokens_are_unique():
    assert len({new_token() for _ in range(100)}) == 100


def test_hashing_a_token_is_deterministic_and_keyed():
    token = new_token()

    assert hash_token(token, SECRET) == hash_token(token, SECRET)
    assert hash_token(token, SECRET) != hash_token(token, "another-secret")
    assert hash_token(token, SECRET) != hash_token(new_token(), SECRET)


def test_the_hash_does_not_contain_the_token():
    token = new_token()
    digest = hash_token(token, SECRET)

    assert len(digest) == 64
    assert token not in digest


# --- authenticate ----------------------------------------------------------


def test_the_right_credentials_authenticate(auth):
    make_user()

    assert auth.authenticate("admin", PASSWORD).username == "admin"


def test_the_wrong_password_does_not(auth):
    make_user()

    assert auth.authenticate("admin", "wrong password 1") is None


def test_an_unknown_username_does_not(auth):
    make_user()

    assert auth.authenticate("nobody", PASSWORD) is None


def test_a_disabled_account_cannot_authenticate(auth):
    make_user(enabled=False)

    assert auth.authenticate("admin", PASSWORD) is None


def test_an_unknown_username_costs_what_a_wrong_password_costs(auth):
    make_user()

    def median_seconds(username, password):
        timings = []
        for _ in range(5):
            start = time.perf_counter()
            auth.authenticate(username, password)
            timings.append(time.perf_counter() - start)
        return statistics.median(timings)

    known = median_seconds("admin", "wrong password 1")
    unknown = median_seconds("nobody", "wrong password 1")

    # Without the dummy verify, an unknown username returns in microseconds and
    # a known one in ~40ms, which answers "does this account exist?" through the
    # clock. Wide band: this guards an order of magnitude, not parity.
    assert unknown > known * 0.5


# --- sessions --------------------------------------------------------------


def test_the_raw_token_is_never_stored(auth):
    token = auth.create_session(make_user())

    stored = stored_token_hashes()
    assert len(stored) == 1
    assert token not in stored
    assert stored[0] == hash_token(token, SECRET)


def test_a_session_resolves_to_its_user(auth):
    token = auth.create_session(make_user(role="viewer"))

    current = auth.resolve_session(token)
    assert current.username == "admin"
    assert current.role == "viewer"


@pytest.mark.parametrize("token", ["", None, "not-a-token"])
def test_a_token_that_identifies_nobody_resolves_to_none(auth, token):
    make_user()

    assert auth.resolve_session(token) is None


def test_an_expired_session_does_not_resolve(auth):
    expired = AuthService(secret=SECRET, ttl_seconds=-1)
    token = expired.create_session(make_user())

    assert auth.resolve_session(token) is None


def test_a_session_minted_under_a_different_secret_does_not_resolve(auth):
    token = auth.create_session(make_user())

    rotated = AuthService(secret="rotated-secret", ttl_seconds=3600)

    # Rotating SYSWATCH_SESSION_SECRET is the mass-logout lever.
    assert rotated.resolve_session(token) is None


def test_disabling_a_user_ends_the_session_they_already_hold(auth):
    user = make_user()
    token = auth.create_session(user)
    assert auth.resolve_session(token) is not None

    with db_scope() as session:
        from app.db.models import UserRecord

        session.get(UserRecord, user.id).enabled = False

    assert auth.resolve_session(token) is None


def test_deleting_a_user_ends_their_session(auth):
    user = make_user()
    token = auth.create_session(user)

    with db_scope() as session:
        from app.db.models import UserRecord

        session.delete(session.get(UserRecord, user.id))

    # The CASCADE takes the row; resolve must not fall over on the way.
    assert auth.resolve_session(token) is None


def test_resolving_records_activity_without_extending_expiry(auth):
    token = auth.create_session(make_user())
    before = SessionStore().by_token_hash(hash_token(token, SECRET))

    time.sleep(0.01)
    auth.resolve_session(token)
    after = SessionStore().by_token_hash(hash_token(token, SECRET))

    assert after.last_seen_at >= before.last_seen_at
    # Absolute expiry: activity must not buy more time.
    assert after.expires_at == before.expires_at


def test_revoking_a_session_ends_it(auth):
    token = auth.create_session(make_user())

    assert auth.revoke(token) is True
    assert auth.resolve_session(token) is None
    assert stored_token_hashes() == []


def test_revoking_an_unknown_session_is_false_not_an_error(auth):
    assert auth.revoke("not-a-token") is False
    assert auth.revoke("") is False


def test_pruning_removes_only_expired_sessions(auth):
    user = make_user()
    live = auth.create_session(user)
    AuthService(secret=SECRET, ttl_seconds=-1).create_session(user)

    assert auth.prune_expired() == 1
    assert stored_token_hashes() == [hash_token(live, SECRET)]


def test_pruning_uses_an_explicit_cutoff_when_given():
    db_session.dispose_engine()
    engine = db_session.init_engine("sqlite://")
    Base.metadata.create_all(engine)

    user = make_user()
    SessionStore().create(
        token_hash="abc",
        user_id=user.id,
        expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert SessionStore().prune_expired(now=datetime(2025, 1, 1, tzinfo=timezone.utc)) == 0
    assert SessionStore().prune_expired(now=datetime(2027, 1, 1, tzinfo=timezone.utc)) == 1

    db_session.dispose_engine()


# --- stores ----------------------------------------------------------------


def test_users_round_trip_with_utc_timestamps(auth):
    created = make_user()

    fetched = UserStore().by_username("admin")
    assert fetched.id == created.id
    assert fetched.role == "admin"
    assert fetched.created_at.tzinfo is not None
    assert fetched.created_at.utcoffset() == timedelta(0)


def test_an_unknown_username_is_none(auth):
    assert UserStore().by_username("nobody") is None
