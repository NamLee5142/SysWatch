"""End-to-end tests across the real API -> service -> AgentClient stack.

Only the agent's HTTP transport is stubbed. Every layer in between is the
real implementation, unlike the unit tests which replace SnapshotService
with a fake and so never exercise the wiring between them.
"""
import httpx
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from config import get_settings

app = create_app()
client = TestClient(app)

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
