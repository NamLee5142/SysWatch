from app.models.snapshot import Snapshot


def test_snapshot_model_parses_agent_payload():
    payload = {
        "cpuInfo": {"coreCount": 8, "usagePercent": 42.5},
        "memoryInfo": {"totalMB": 16384, "usedMB": 4096},
        "diskInfo": {"totalGB": 512, "freeGB": 120},
        "systemInfo": {"name": "Windows", "version": "11", "hostName": "devbox"},
    }

    snapshot = Snapshot.from_payload(payload)

    assert snapshot.cpuInfo.coreCount == 8
    assert snapshot.memoryInfo.usedMB == 4096
    assert snapshot.diskInfo.freeGB == 120
    assert snapshot.systemInfo.hostName == "devbox"
