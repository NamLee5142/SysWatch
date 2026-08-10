import pytest
from pydantic import ValidationError

from app.services.snapshot_service import SnapshotService

VALID_PAYLOAD = {
    "cpuInfo": {"coreCount": 4, "usagePercent": 12.3},
    "memoryInfo": {"totalMB": 8192, "usedMB": 2048},
    "diskInfo": {"totalGB": 256, "freeGB": 64},
    "systemInfo": {"name": "Linux", "version": "22.04", "hostName": "server"},
}


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def service_for(response) -> SnapshotService:
    """A SnapshotService whose agent client always returns the given response."""

    class FakeClient:
        def get_snapshot(self):
            return response

    return SnapshotService(client=FakeClient())


def test_snapshot_service_parses_model():
    service = service_for(FakeResponse(200, VALID_PAYLOAD))

    snapshot = service.get_snapshot()

    assert snapshot.cpuInfo.coreCount == 4
    assert snapshot.systemInfo.hostName == "server"


def test_snapshot_service_raises_for_missing_snapshot():
    service = service_for(FakeResponse(204))

    with pytest.raises(LookupError, match="No snapshot available yet"):
        service.get_snapshot()


def test_snapshot_service_raises_for_unexpected_status():
    service = service_for(FakeResponse(500))

    with pytest.raises(RuntimeError, match="Agent returned status 500"):
        service.get_snapshot()


def test_snapshot_service_raises_for_malformed_payload():
    service = service_for(FakeResponse(200, {"cpuInfo": {"coreCount": "many"}}))

    with pytest.raises(ValidationError) as exc_info:
        service.get_snapshot()

    # the API maps ValueError to 502, so ValidationError must stay a subclass of it
    assert isinstance(exc_info.value, ValueError)
