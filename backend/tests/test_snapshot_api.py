from fastapi.testclient import TestClient

from app.client.errors import AgentConnectionError
from app.main import app
from app.models.snapshot import Snapshot

client = TestClient(app)


def test_snapshot_endpoint_returns_model(monkeypatch):
    snapshot = Snapshot(**{
        "cpuInfo": {"coreCount": 8, "usagePercent": 42.5},
        "memoryInfo": {"totalMB": 16384, "usedMB": 4096},
        "diskInfo": {"totalGB": 512, "freeGB": 120},
        "systemInfo": {"name": "Windows", "version": "11", "hostName": "devbox"},
    })

    class FakeService:
        def get_snapshot(self):
            return snapshot

    monkeypatch.setattr("app.api.snapshot.SnapshotService", lambda *args, **kwargs: FakeService())

    response = client.get("/snapshot")

    assert response.status_code == 200
    assert response.json()["cpuInfo"]["coreCount"] == 8
    assert response.json()["memoryInfo"]["usedMB"] == 4096


def test_snapshot_endpoint_returns_503_on_connection_error(monkeypatch):
    class FakeService:
        def get_snapshot(self):
            raise AgentConnectionError("boom")

    monkeypatch.setattr("app.api.snapshot.SnapshotService", lambda *args, **kwargs: FakeService())

    response = client.get("/snapshot")

    assert response.status_code == 503
    assert response.json()["detail"] == "Unable to reach agent"
