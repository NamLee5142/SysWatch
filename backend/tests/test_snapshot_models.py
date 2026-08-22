from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.snapshot import Snapshot


def test_snapshot_model_parses_agent_payload():
    payload = {
        "collectedAt": "2026-08-12T11:15:27Z",
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


def test_collected_at_parses_as_utc():
    payload = {
        "collectedAt": "2026-08-12T11:15:27Z",
        "cpuInfo": {"coreCount": 8, "usagePercent": 42.5},
        "memoryInfo": {"totalMB": 16384, "usedMB": 4096},
        "diskInfo": {"totalGB": 512, "freeGB": 120},
        "systemInfo": {"name": "Windows", "version": "11", "hostName": "devbox"},
    }

    snapshot = Snapshot.from_payload(payload)

    # The agent's trailing Z must survive as a real UTC offset, not be dropped
    # and silently reinterpreted as local time.
    assert snapshot.collectedAt == datetime(2026, 8, 12, 11, 15, 27, tzinfo=timezone.utc)
    assert snapshot.collectedAt.utcoffset().total_seconds() == 0


def test_payload_without_collected_at_is_rejected():
    payload = {
        "cpuInfo": {"coreCount": 8, "usagePercent": 42.5},
        "memoryInfo": {"totalMB": 16384, "usedMB": 4096},
        "diskInfo": {"totalGB": 512, "freeGB": 120},
        "systemInfo": {"name": "Windows", "version": "11", "hostName": "devbox"},
    }

    with pytest.raises(ValidationError):
        Snapshot.from_payload(payload)


def test_malformed_collected_at_is_rejected():
    payload = {
        "collectedAt": "not-a-timestamp",
        "cpuInfo": {"coreCount": 8, "usagePercent": 42.5},
        "memoryInfo": {"totalMB": 16384, "usedMB": 4096},
        "diskInfo": {"totalGB": 512, "freeGB": 120},
        "systemInfo": {"name": "Windows", "version": "11", "hostName": "devbox"},
    }

    with pytest.raises(ValidationError):
        Snapshot.from_payload(payload)
