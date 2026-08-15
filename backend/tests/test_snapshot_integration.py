"""End-to-end tests across the real API -> service -> AgentClient stack.

Only the agent's HTTP transport is stubbed. Every layer in between is the
real implementation, unlike the unit tests which replace SnapshotService
with a fake and so never exercise the wiring between them.
"""
import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.db import session as db_session
from app.db.models import Base
from app.main import create_app
from app.repositories import SnapshotStore
from config import get_settings

app = create_app()
client = TestClient(app)


@pytest.fixture(autouse=True)
def temp_database():
    """Point the whole stack at a throwaway database.

    /snapshot now writes what it fetches, so without this the suite would
    persist into the real syswatch.db.
    """
    db_session.dispose_engine()
    engine = db_session.init_engine("sqlite://")
    Base.metadata.create_all(engine)

    yield

    db_session.dispose_engine()

AGENT_SNAPSHOT_URL = f"{get_settings().agent_base_url}/snapshot"

AGENT_PAYLOAD = {
    "collectedAt": "2026-08-12T11:15:27Z",
    "cpuInfo": {"coreCount": 8, "usagePercent": 42.5},
    "memoryInfo": {"totalMB": 16384, "usedMB": 4096},
    "diskInfo": {"totalGB": 512, "freeGB": 120},
    "systemInfo": {"name": "Windows", "version": "11", "hostName": "devbox"},
}


@respx.mock
def test_agent_snapshot_reaches_the_client_unchanged():
    route = respx.get(AGENT_SNAPSHOT_URL).respond(200, json=AGENT_PAYLOAD)

    response = client.get("/snapshot")

    assert route.called
    assert response.status_code == 200
    assert response.json() == AGENT_PAYLOAD


@respx.mock
def test_fetched_snapshot_is_persisted():
    respx.get(AGENT_SNAPSHOT_URL).respond(200, json=AGENT_PAYLOAD)

    assert client.get("/snapshot").status_code == 200

    stored = SnapshotStore().latest()
    assert stored is not None
    assert stored.host_name == "devbox"
    assert stored.cpu_core_count == 8
    assert stored.collected_at.isoformat() == "2026-08-12T11:15:27+00:00"


@respx.mock
def test_repeated_fetches_do_not_duplicate_a_snapshot():
    respx.get(AGENT_SNAPSHOT_URL).respond(200, json=AGENT_PAYLOAD)

    client.get("/snapshot")
    client.get("/snapshot")

    # Same collection time, so the unique constraint collapses the second write.
    assert len(SnapshotStore().query()) == 1


@respx.mock
def test_agent_204_becomes_404():
    respx.get(AGENT_SNAPSHOT_URL).respond(204)

    response = client.get("/snapshot")

    assert response.status_code == 404
    assert response.json()["detail"] == "No snapshot available yet"


@respx.mock
def test_agent_error_status_becomes_502():
    respx.get(AGENT_SNAPSHOT_URL).respond(500)

    response = client.get("/snapshot")

    assert response.status_code == 502
    assert "500" in response.json()["detail"]


@respx.mock
def test_malformed_agent_payload_becomes_502():
    respx.get(AGENT_SNAPSHOT_URL).respond(200, json={"cpuInfo": {"coreCount": "many"}})

    response = client.get("/snapshot")

    assert response.status_code == 502


@respx.mock
def test_non_json_agent_body_becomes_502():
    respx.get(AGENT_SNAPSHOT_URL).respond(200, text="<html>not json</html>")

    response = client.get("/snapshot")

    assert response.status_code == 502


@respx.mock
def test_unreachable_agent_becomes_503():
    respx.get(AGENT_SNAPSHOT_URL).mock(side_effect=httpx.ConnectError("connection refused"))

    response = client.get("/snapshot")

    assert response.status_code == 503
    assert response.json()["detail"] == "Unable to reach agent"
