"""Credentials an agent holds.

The first credential in this project that is neither a password nor a session
cookie, which is why the hashing choice gets its own section below rather than
being taken as read.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.auth.agent_token import hash_token, new_token, tokens_match
from app.auth.session import hash_token as hash_session_token
from app.repositories import AgentTokenStore

SECRET = "a-deployment-secret-long-enough-to-be-real"
AT = datetime(2026, 9, 7, 11, 0, tzinfo=timezone.utc)

MODULE = Path(__file__).resolve().parents[1] / "app" / "auth" / "agent_token.py"


@pytest.fixture
def store(database):
    return AgentTokenStore()


@pytest.fixture
def issued(store):
    """A credential, the way an operator would get one."""
    token = new_token()
    record = store.create(
        host_name="devbox", token_hash=hash_token(token, SECRET), at=AT
    )
    return token, record


# --- the token itself --------------------------------------------------------


def test_a_token_is_long_and_unguessable():
    token = new_token()

    # 32 bytes, base64url encoded, so 43 characters without padding.
    assert len(token) >= 43
    assert len({new_token() for _ in range(100)}) == 100


def test_the_same_token_hashes_the_same_way():
    token = new_token()

    assert hash_token(token, SECRET) == hash_token(token, SECRET)


def test_a_different_secret_gives_a_different_hash():
    """A table lifted from one deployment is inert against another."""
    token = new_token()

    assert hash_token(token, SECRET) != hash_token(token, "another deployment")


def test_the_hash_is_not_the_token():
    token = new_token()

    hashed = hash_token(token, SECRET)

    assert token not in hashed
    assert len(hashed) == 64  # sha256 hex


def test_an_agent_token_and_a_session_token_hash_differently():
    """Domain separation, and it is not decoration.

    Both are HMAC-SHA256 under the same deployment secret. Without a distinct
    prefix the same random string would produce the same hash in both tables,
    and a value that authenticated as one could be presented as the other.
    """
    token = new_token()

    assert hash_token(token, SECRET) != hash_session_token(token, SECRET)


def test_comparison_is_constant_time():
    token = new_token()
    hashed = hash_token(token, SECRET)

    assert tokens_match(hashed, hashed)
    assert not tokens_match(hashed, hash_token(new_token(), SECRET))


# --- why this is not Argon2 --------------------------------------------------


def test_the_module_does_not_reach_for_argon2():
    """Deliberate, and the reasoning is in the module docstring.

    A password is low-entropy and verified once at login, so it is worth 40ms
    and 64 MiB to store. An agent token is 256 random bits verified on every
    push, and an unauthenticated caller posting garbage to the ingestion
    endpoint would otherwise force that work per request - a denial-of-service
    amplifier reachable before authentication.
    """
    code = chr(10).join(
        line for line in MODULE.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("#")
    )
    body = code.split('"""')[-1]  # past the module docstring

    assert "argon2" not in body.lower()
    assert "hmac" in body


def test_the_module_has_no_logger():
    """The file that handles a plaintext credential contains nothing that logs.

    The same rule as password.py, session.py and alerts/smtp.py. Checked on the
    imports and the code rather than on the word "logger", because the
    docstring explains at length why there is no logger.
    """
    code = chr(10).join(
        line for line in MODULE.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("#")
    )
    body = code.split('"""')[-1]

    assert "import logging" not in code
    assert "getLogger" not in code
    assert "logger" not in body


# --- the store ---------------------------------------------------------------


def test_creating_records_the_host_and_the_hash(store):
    token = new_token()

    record = store.create(host_name="devbox", token_hash=hash_token(token, SECRET))

    assert record.host_name == "devbox"
    assert record.token_hash == hash_token(token, SECRET)
    assert record.enabled is True
    assert record.last_seen_at is None


def test_the_plaintext_appears_in_no_column(store):
    """The claim in the roadmap's done-when, checked against every column."""
    token = new_token()
    store.create(host_name="devbox", token_hash=hash_token(token, SECRET), description=token[:4])

    from sqlalchemy import select

    from app.db import get_session
    from app.db.models import AgentTokenRecord

    with get_session() as session:
        row = session.execute(select(AgentTokenRecord)).scalars().one()
        values = [str(getattr(row, column.name)) for column in row.__table__.columns]

    assert token not in " ".join(values)


def test_a_token_resolves_to_its_host(issued, store):
    token, record = issued

    found = store.by_token_hash(hash_token(token, SECRET))

    assert found is not None
    assert found.id == record.id
    assert found.host_name == "devbox"


def test_an_unknown_token_resolves_to_nothing(store):
    assert store.by_token_hash(hash_token(new_token(), SECRET)) is None


def test_a_token_from_another_deployment_resolves_to_nothing(issued, store):
    """Rotating the deployment secret invalidates every agent at once."""
    token, _ = issued

    assert store.by_token_hash(hash_token(token, "a rotated secret")) is None


def test_disabling_keeps_the_row(issued, store):
    """Revoking is not deleting: an audit of a decommissioned machine needs it."""
    _, record = issued

    disabled = store.set_enabled(record.id, False)

    assert disabled.enabled is False
    assert store.get(record.id) is not None


def test_a_disabled_token_still_resolves(issued, store):
    """Whose decision it is to refuse one.

    by_token_hash returns the row so the caller can tell "revoked" from "never
    existed". Refusing is the dependency's job, in a later commit, and it is
    tested there.
    """
    token, record = issued
    store.set_enabled(record.id, False)

    found = store.by_token_hash(hash_token(token, SECRET))

    assert found is not None
    assert found.enabled is False


def test_disabling_can_be_undone(issued, store):
    _, record = issued
    store.set_enabled(record.id, False)

    assert store.set_enabled(record.id, True).enabled is True


def test_disabling_a_token_that_does_not_exist(store):
    assert store.set_enabled(999, False) is None


def test_touch_records_use(issued, store):
    _, record = issued

    store.touch(record.id, at=AT + timedelta(hours=1))

    assert store.get(record.id).last_seen_at == AT + timedelta(hours=1)


def test_timestamps_come_back_utc_aware(issued, store):
    """Every other timestamp in this application is aware; so is this one."""
    _, record = issued
    store.touch(record.id, at=AT)

    found = store.get(record.id)

    assert found.created_at.tzinfo is not None
    assert found.last_seen_at.tzinfo is not None


def test_a_host_can_hold_more_than_one_token(store):
    """Rotation: issue the new one, deploy it, then disable the old.

    A unique constraint on host_name would forbid the overlap and leave
    "delete and hope the deploy lands first" as the only route.
    """
    for _ in range(2):
        store.create(host_name="devbox", token_hash=hash_token(new_token(), SECRET))

    assert len(store.for_host("devbox")) == 2


def test_two_hosts_are_separate(store):
    store.create(host_name="devbox", token_hash=hash_token(new_token(), SECRET))
    store.create(host_name="buildbox", token_hash=hash_token(new_token(), SECRET))

    assert [t.host_name for t in store.for_host("devbox")] == ["devbox"]
    assert len(store.all()) == 2


def test_the_same_hash_cannot_be_stored_twice(store):
    """The unique index, which is also what makes the lookup a single row."""
    from sqlalchemy.exc import IntegrityError

    hashed = hash_token(new_token(), SECRET)
    store.create(host_name="devbox", token_hash=hashed)

    with pytest.raises(IntegrityError):
        store.create(host_name="buildbox", token_hash=hashed)


def test_the_repr_does_not_carry_the_hash(issued):
    """It is not the token, but it is still the lookup key."""
    _, record = issued

    assert record.token_hash not in repr(record)
    assert "devbox" in repr(record)
