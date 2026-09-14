"""Turning an agent's bearer token into the host it speaks for.

The first credential in this project that is not a session cookie, so the
things taken for granted elsewhere - the header shape, what a failure reveals,
whether the development switch applies - are all decided here and tested here.
"""
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth.agent_service import AgentAuthService
from app.auth.agent_token import hash_token, new_token
from app.auth.dependencies import bearer_token, require_agent
from app.models.auth import CurrentAgent
from app.repositories import AgentTokenStore

SECRET = "a-deployment-secret-long-enough-to-be-real"

MODULE = Path(__file__).resolve().parents[1] / "app" / "auth" / "agent_service.py"


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("SYSWATCH_SESSION_SECRET", SECRET)


@pytest.fixture
def issued(database):
    """A live credential for 'buildbox'."""
    token = new_token()
    record = AgentTokenStore().create(
        host_name="buildbox", token_hash=hash_token(token, SECRET)
    )
    return token, record


@pytest.fixture
def client(database):
    """A minimal app whose only route is behind require_agent."""
    app = FastAPI()

    @app.get("/who")
    def who(agent: CurrentAgent = Depends(require_agent)):
        return {"hostName": agent.host_name, "tokenId": agent.token_id}

    return TestClient(app)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# --- the header ---------------------------------------------------------------


@pytest.mark.parametrize(
    "header, expected",
    [
        ("Bearer abc123", "abc123"),
        ("bearer abc123", "abc123"),  # RFC 9110: the scheme is case-insensitive
        ("BEARER abc123", "abc123"),
        ("Bearer   abc123  ", "abc123"),
        ("abc123", None),  # no scheme
        ("Basic YWJjOjEyMw==", None),  # another scheme's payload is not a token
        ("Bearer", None),
        ("Bearer    ", None),
        ("", None),
    ],
)
def test_reading_the_header(header, expected):
    class Request:
        headers = {}

    request = Request()
    if header:
        request.headers = {"Authorization": header}

    assert bearer_token(request) == expected


def test_no_header_at_all():
    class Request:
        headers = {}

    assert bearer_token(Request()) is None


# --- resolution ---------------------------------------------------------------


def test_a_valid_token_resolves_to_its_host(issued):
    token, record = issued

    agent = AgentAuthService(secret=SECRET).resolve(token)

    assert agent.host_name == "buildbox"
    assert agent.token_id == record.id


def test_an_unknown_token_resolves_to_nothing(database):
    assert AgentAuthService(secret=SECRET).resolve(new_token()) is None


def test_an_empty_token_resolves_to_nothing(database):
    service = AgentAuthService(secret=SECRET)

    assert service.resolve("") is None
    assert service.resolve(None) is None


def test_a_revoked_token_resolves_to_nothing(issued):
    """Revocation takes effect on the next request, not on the next restart."""
    token, record = issued
    AgentTokenStore().set_enabled(record.id, False)

    assert AgentAuthService(secret=SECRET).resolve(token) is None


def test_a_restored_token_works_again(issued):
    token, record = issued
    store = AgentTokenStore()
    store.set_enabled(record.id, False)
    store.set_enabled(record.id, True)

    assert AgentAuthService(secret=SECRET).resolve(token) is not None


def test_a_token_from_another_deployment_resolves_to_nothing(issued):
    """Rotating the deployment secret revokes every agent at once."""
    token, _ = issued

    assert AgentAuthService(secret="a rotated secret").resolve(token) is None


def test_a_deployment_with_no_secret_admits_nobody(database):
    """Fail closed when misconfigured, rather than into an empty-key namespace.

    Stored deliberately under the empty key, which is the only case that
    distinguishes the guard from doing nothing: without it, HMAC("", token) is
    computed, matches this row, and a backend running with no secret
    authenticates agents under a key everybody knows.

    Asserting only that a *properly* issued token fails here would pass with the
    guard deleted, because a hash made under a real secret never matches one
    made without it.
    """
    token = new_token()
    AgentTokenStore().create(host_name="buildbox", token_hash=hash_token(token, ""))

    assert AgentAuthService(secret="").resolve(token) is None


def test_resolving_records_that_the_token_was_used(issued):
    """What "this host has gone quiet" will later be computed from."""
    token, record = issued
    assert AgentTokenStore().get(record.id).last_seen_at is None

    AgentAuthService(secret=SECRET).resolve(token)

    assert AgentTokenStore().get(record.id).last_seen_at is not None


def test_a_failed_resolution_records_nothing(issued):
    token, record = issued

    AgentAuthService(secret=SECRET).resolve(new_token())

    assert AgentTokenStore().get(record.id).last_seen_at is None


# --- through HTTP -------------------------------------------------------------


def test_a_valid_token_reaches_the_route(client, issued):
    token, record = issued

    response = client.get("/who", headers=auth(token))

    assert response.status_code == 200
    assert response.json() == {"hostName": "buildbox", "tokenId": record.id}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": ""},
        {"Authorization": "Bearer"},
        {"Authorization": "Basic YWJjOjEyMw=="},
        {"Authorization": "Bearer not-a-real-token"},
    ],
    ids=["absent", "empty", "no value", "wrong scheme", "unknown token"],
)
def test_everything_that_is_not_a_live_token_is_a_401(client, issued, headers):
    assert client.get("/who", headers=headers).status_code == 401


def test_a_revoked_token_is_a_401(client, issued):
    token, record = issued
    AgentTokenStore().set_enabled(record.id, False)

    assert client.get("/who", headers=auth(token)).status_code == 401


def test_every_failure_looks_the_same(client, issued):
    """A caller able to tell "revoked" from "never existed" can enumerate.

    Same status, same body, for a token that was never issued and one that was
    issued and withdrawn.
    """
    token, record = issued
    AgentTokenStore().set_enabled(record.id, False)

    revoked = client.get("/who", headers=auth(token))
    unknown = client.get("/who", headers=auth(new_token()))

    assert revoked.status_code == unknown.status_code
    assert revoked.json() == unknown.json()


def test_the_401_names_the_scheme(client, database):
    """RFC 9110. The agent has no browser to work it out for it."""
    response = client.get("/who")

    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_the_response_never_carries_the_token(client, issued):
    token, record = issued
    AgentTokenStore().set_enabled(record.id, False)

    response = client.get("/who", headers=auth(token))

    assert token not in response.text
    assert AgentTokenStore().get(record.id).token_hash not in response.text


# --- the development switch does not apply ------------------------------------


def test_disabling_authentication_does_not_admit_an_agent(client, database, monkeypatch):
    """SYSWATCH_AUTH_ENABLED=false opens every *user* endpoint. Not this one.

    That switch works elsewhere because those routes only need to know whether
    the caller may act, and it answers "yes, as an administrator". This route
    needs to know which machine is speaking, and there is no anonymous answer to
    that. Falling back to the payload's hostName would put a forgeable identity
    on the write path, in the configuration nobody tests against.
    """
    monkeypatch.setenv("SYSWATCH_AUTH_ENABLED", "false")

    assert client.get("/who").status_code == 401


def test_disabling_authentication_still_lets_a_real_token_through(client, issued, monkeypatch):
    monkeypatch.setenv("SYSWATCH_AUTH_ENABLED", "false")
    token, _ = issued

    assert client.get("/who", headers=auth(token)).status_code == 200


# --- an agent is not a user ---------------------------------------------------


def test_an_agent_carries_no_role():
    """Deliberately not a CurrentUser.

    Modelling an agent as a user with a role would put both on the same
    authorization ladder, and the first role check to accept "agent" would
    widen what a machine credential can reach.
    """
    agent = CurrentAgent(host_name="buildbox", token_id=1)

    assert not hasattr(agent, "role")
    assert not hasattr(agent, "username")


def test_the_service_has_no_logger():
    code = chr(10).join(
        line for line in MODULE.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("#")
    )
    body = code.split('"""')[-1]

    assert "import logging" not in code
    assert "getLogger" not in code
    assert "logger" not in body
