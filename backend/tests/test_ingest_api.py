"""Snapshots pushed by a remote agent.

The first write path into `snapshots` that is not the poller, and the first
route in this application whose caller is a machine rather than a browser.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth.agent_token import hash_token, new_token
from app.main import create_app
from app.repositories import AgentTokenStore, SnapshotStore

SECRET = "a-deployment-secret-long-enough-to-be-real"
AT = datetime(2026, 9, 7, 11, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("SYSWATCH_SESSION_SECRET", SECRET)


@pytest.fixture
def client(database):
    return TestClient(create_app(), base_url="http://testserver/api")


def issue(host):
    """A live credential, and the token to present with it."""
    token = new_token()
    AgentTokenStore().create(host_name=host, token_hash=hash_token(token, SECRET))
    return token


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def payload(host="buildbox", at=AT, cpu=12.5):
    return {
        "collectedAt": at.isoformat().replace("+00:00", "Z"),
        "cpuInfo": {"coreCount": 8, "usagePercent": cpu},
        "memoryInfo": {"totalMB": 16384, "usedMB": 4096},
        "diskInfo": {"totalGB": 512, "freeGB": 120},
        "systemInfo": {"name": "Windows", "version": "11", "hostName": host},
    }


def push(client, token, body=None):
    return client.post("/ingest/snapshot", json=body or payload(), headers=auth(token))


# --- accepting -----------------------------------------------------------------


def test_a_pushed_snapshot_is_accepted(client):
    token = issue("buildbox")

    response = push(client, token)

    assert response.status_code == 202
    assert response.json() == {"hostName": "buildbox", "stored": True}


def test_a_pushed_snapshot_is_readable_afterwards(client):
    """The done-when: it arrives through the same API everything else reads."""
    token = issue("buildbox")

    push(client, token)

    stored = SnapshotStore().query(host_name="buildbox")
    assert len(stored) == 1
    assert stored[0].cpu_usage_percent == 12.5


def test_it_appears_as_a_host(client):
    """Which is what the dashboard's host selector will read."""
    push(client, issue("buildbox"))

    assert [host.host_name for host in SnapshotStore().hosts()] == ["buildbox"]


def test_the_whole_payload_survives(client):
    token = issue("buildbox")
    body = payload()
    body["processInfo"] = {"count": 412, "top": [{"pid": 1, "name": "a.exe", "memoryMB": 10}]}

    push(client, token, body)

    stored = SnapshotStore().query(host_name="buildbox")[0]
    assert stored.process_count == 412
    assert stored.mem_used_mb == 4096


def test_a_snapshot_without_the_optional_blocks_is_accepted(client):
    """A pre-Sprint-7 agent. The poll path accepts these; so does this one."""
    assert push(client, issue("buildbox"), payload()).status_code == 202


# --- identity comes from the credential ----------------------------------------


def test_the_host_comes_from_the_token_not_the_payload(client):
    """The security property this endpoint is built around.

    The payload is written by the machine being identified. Believing its
    systemInfo would let anyone holding one credential file rows under any host
    name they cared to type.
    """
    token = issue("buildbox")

    push(client, token, payload(host="devbox"))

    assert [h.host_name for h in SnapshotStore().hosts()] == ["buildbox"]
    assert SnapshotStore().query(host_name="devbox") == []


def test_the_response_names_the_credential_host(client):
    token = issue("buildbox")

    body = push(client, token, payload(host="devbox")).json()

    assert body["hostName"] == "buildbox"


@pytest.fixture(autouse=True)
def forget_mentioned_hostnames():
    """The "said it once" set is module state and outlives a test."""
    from app.api import ingest

    ingest._MENTIONED.clear()
    yield
    ingest._MENTIONED.clear()


def test_a_mismatch_is_mentioned_once(client, caplog):
    """Once, not per push.

    The first version logged on every request. An agent pushing every second
    wrote 86,400 identical lines a day - 93% of the log, measured on the first
    sustained run against a real backend.
    """
    token = issue("buildbox")

    with caplog.at_level("INFO"):
        for _ in range(5):
            push(client, token, payload(host="devbox", at=AT + timedelta(seconds=_)))

    mentions = [r for r in caplog.records if "report the hostname" in r.message]
    assert len(mentions) == 1
    assert "buildbox" in caplog.text
    assert "devbox" in caplog.text


def test_it_is_not_a_warning(client, caplog):
    """A token named for a role on a machine named by Windows is normal.

    Identity comes from the credential precisely so the payload's name need not
    match, and the backend cannot tell a sensible naming choice from a token on
    the wrong machine. It says what it sees and does not editorialise.
    """
    with caplog.at_level("INFO"):
        push(client, issue("buildbox"), payload(host="devbox"))

    mentions = [r for r in caplog.records if "report the hostname" in r.message]
    assert [r.levelname for r in mentions] == ["INFO"]


def test_a_different_reported_name_is_mentioned_again(client, caplog):
    """An agent whose machine was renamed is worth hearing about once more."""
    token = issue("buildbox")

    with caplog.at_level("INFO"):
        push(client, token, payload(host="devbox", at=AT))
        push(client, token, payload(host="otherbox", at=AT + timedelta(seconds=1)))

    mentions = [r for r in caplog.records if "report the hostname" in r.message]
    assert len(mentions) == 2


def test_a_matching_hostname_is_not_logged(client, caplog):
    with caplog.at_level("INFO"):
        push(client, issue("buildbox"), payload(host="buildbox"))

    assert "report the hostname" not in caplog.text


def test_the_log_line_carries_no_token(client, caplog):
    token = issue("buildbox")

    with caplog.at_level("WARNING"):
        push(client, token, payload(host="devbox"))

    assert token not in caplog.text


# --- one host cannot overwrite another ------------------------------------------


def test_another_hosts_token_cannot_overwrite_a_row(client):
    """The second half of the done-when.

    Two agents pushing the same collectedAt produce two rows, one per host,
    because the unique constraint is on the pair. Neither can reach the other's.
    """
    buildbox, devbox = issue("buildbox"), issue("devbox")

    push(client, buildbox, payload(host="buildbox", cpu=11.0))
    push(client, devbox, payload(host="buildbox", cpu=99.0))

    store = SnapshotStore()
    assert store.query(host_name="buildbox")[0].cpu_usage_percent == 11.0
    assert store.query(host_name="devbox")[0].cpu_usage_percent == 99.0


def test_two_hosts_are_two_hosts(client):
    push(client, issue("buildbox"))
    push(client, issue("devbox"))

    assert sorted(h.host_name for h in SnapshotStore().hosts()) == ["buildbox", "devbox"]


# --- retries --------------------------------------------------------------------


def test_a_repeated_push_is_accepted_and_stores_nothing(client):
    """An agent that retried a request whose response it never saw.

    Reporting an error would make it retry again, forever, against a backend
    that already has the reading.
    """
    token = issue("buildbox")
    push(client, token)

    second = push(client, token)

    assert second.status_code == 202
    assert second.json() == {"hostName": "buildbox", "stored": False}
    assert len(SnapshotStore().query(host_name="buildbox")) == 1


def test_a_later_reading_is_a_new_row(client):
    token = issue("buildbox")
    push(client, token, payload(at=AT))

    push(client, token, payload(at=AT + timedelta(seconds=10)))

    assert len(SnapshotStore().query(host_name="buildbox")) == 2


# --- the credential --------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic YWJjOjEyMw=="}],
    ids=["no credential", "unknown token", "wrong scheme"],
)
def test_a_push_without_a_live_credential_is_refused(client, database, headers):
    response = client.post("/ingest/snapshot", json=payload(), headers=headers)

    assert response.status_code == 401
    assert SnapshotStore().query() == []


def test_a_revoked_token_cannot_push(client):
    token = issue("buildbox")
    record = AgentTokenStore().for_host("buildbox")[0]
    AgentTokenStore().set_enabled(record.id, False)

    assert push(client, token).status_code == 401
    assert SnapshotStore().query() == []


def test_pushing_records_that_the_token_was_used(client):
    token = issue("buildbox")

    push(client, token)

    assert AgentTokenStore().for_host("buildbox")[0].last_seen_at is not None


def test_a_session_cookie_is_not_a_way_in(client, database):
    """The route takes a bearer token, and only that.

    A browser holding an admin session must not be able to file snapshots as a
    machine: those are different kinds of caller, and this one names a host.
    """
    response = client.post("/ingest/snapshot", json=payload())

    assert response.status_code == 401


# --- the body --------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"collectedAt": "2026-09-07T11:00:00Z"},
        {**payload(), "cpuInfo": {"coreCount": 8}},
        {**payload(), "collectedAt": "not a time"},
    ],
    ids=["empty", "only a time", "incomplete cpu", "bad timestamp"],
)
def test_a_payload_that_is_not_a_snapshot_is_a_422(client, body):
    token = issue("buildbox")

    assert client.post("/ingest/snapshot", json=body, headers=auth(token)).status_code == 422


def test_a_bad_payload_stores_nothing(client):
    push(client, issue("buildbox"), {"collectedAt": "2026-09-07T11:00:00Z"})

    assert SnapshotStore().query() == []


# --- the poller is unaffected ------------------------------------------------------


def test_the_poller_still_files_under_the_payloads_hostname(database):
    """save() without a host keeps its old behaviour exactly.

    The poller fetched the snapshot from an agent it was configured to reach, so
    there is no third party whose word is being taken.
    """
    from app.models.snapshot import Snapshot

    SnapshotStore().save(Snapshot.from_payload(payload(host="devbox")))

    assert [h.host_name for h in SnapshotStore().hosts()] == ["devbox"]
