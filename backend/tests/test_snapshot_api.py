import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.client.errors import AgentConnectionError
from app.main import create_app
from app.models.snapshot import Snapshot

app = create_app()
client = TestClient(app)

VALID_PAYLOAD = {
    "collectedAt": "2026-08-12T11:15:27Z",
    "cpuInfo": {"coreCount": 8, "usagePercent": 42.5},
    "memoryInfo": {"totalMB": 16384, "usedMB": 4096},
    "diskInfo": {"totalGB": 512, "freeGB": 120},
    "systemInfo": {"name": "Windows", "version": "11", "hostName": "devbox"},
}


def patch_service(monkeypatch, result=None, error=None):
    """Swap SnapshotService for a stub that returns result or raises error."""

    class FakeService:
        def get_snapshot(self):
            if error is not None:
                raise error
            return result

    monkeypatch.setattr("app.api.snapshot.SnapshotService", lambda *args, **kwargs: FakeService())


def validation_error() -> ValidationError:
    """A real ValidationError, as the service raises for a malformed payload."""
    try:
        Snapshot.from_payload({"cpuInfo": {}})
    except ValidationError as exc:
        return exc
    raise AssertionError("expected Snapshot to reject the payload")


def test_snapshot_endpoint_returns_model(monkeypatch):
    patch_service(monkeypatch, result=Snapshot(**VALID_PAYLOAD))

    response = client.get("/snapshot")

    assert response.status_code == 200
    assert response.json()["cpuInfo"]["coreCount"] == 8
    assert response.json()["memoryInfo"]["usedMB"] == 4096


def test_snapshot_endpoint_returns_404_when_agent_has_no_snapshot(monkeypatch):
    patch_service(monkeypatch, error=LookupError("No snapshot available yet"))

    response = client.get("/snapshot")

    assert response.status_code == 404
    assert response.json()["detail"] == "No snapshot available yet"


def test_snapshot_endpoint_returns_502_on_unexpected_agent_status(monkeypatch):
    patch_service(monkeypatch, error=RuntimeError("Agent returned status 500"))

    response = client.get("/snapshot")

    assert response.status_code == 502
    assert response.json()["detail"] == "Agent returned status 500"


def test_snapshot_endpoint_returns_502_on_malformed_payload(monkeypatch):
    patch_service(monkeypatch, error=validation_error())

    response = client.get("/snapshot")

    assert response.status_code == 502


def test_snapshot_endpoint_returns_503_on_connection_error(monkeypatch):
    patch_service(monkeypatch, error=AgentConnectionError("boom"))

    response = client.get("/snapshot")

    assert response.status_code == 503
    assert response.json()["detail"] == "Unable to reach agent"


def test_snapshot_endpoint_returns_503_on_http_error(monkeypatch):
    patch_service(monkeypatch, error=httpx.ReadTimeout("read timed out"))

    response = client.get("/snapshot")

    assert response.status_code == 503
    assert response.json()["detail"] == "Unable to reach agent"
