from app.services.snapshot_service import SnapshotService


def test_snapshot_service_parses_model():
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "cpuInfo": {"coreCount": 4, "usagePercent": 12.3},
                "memoryInfo": {"totalMB": 8192, "usedMB": 2048},
                "diskInfo": {"totalGB": 256, "freeGB": 64},
                "systemInfo": {"name": "Linux", "version": "22.04", "hostName": "server"},
            }

    class FakeClient:
        def get_snapshot(self):
            return FakeResponse()

    service = SnapshotService(client=FakeClient())
    snapshot = service.get_snapshot()

    assert snapshot.cpuInfo.coreCount == 4
    assert snapshot.systemInfo.hostName == "server"
