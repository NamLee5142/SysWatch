from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_snapshot_endpoint_returns_model(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "cpuInfo": {"coreCount": 8, "usagePercent": 42.5},
                "memoryInfo": {"totalMB": 16384, "usedMB": 4096},
                "diskInfo": {"totalGB": 512, "freeGB": 120},
                "systemInfo": {"name": "Windows", "version": "11", "hostName": "devbox"},
            }

    class FakeClient:
        def __init__(self, base_url):
            self.base_url = base_url

        def get_snapshot(self):
            return FakeResponse()

    monkeypatch.setattr("app.api.snapshot.AgentClient", FakeClient)

    response = client.get("/snapshot")

    assert response.status_code == 200
    assert response.json()["cpuInfo"]["coreCount"] == 8
    assert response.json()["memoryInfo"]["usedMB"] == 4096
