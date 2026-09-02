from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.snapshot import Snapshot

PROCESS_BLOCK = {
    "count": 240,
    "top": [
        {"pid": 1234, "name": "chrome.exe", "memoryMB": 512},
        {"pid": 9, "name": "System", "memoryMB": 3},
    ],
}

NETWORK_BLOCK = {
    "interfaces": [
        {
            "name": "Wi-Fi",
            "bytesSent": 1000,
            "bytesRecv": 2000,
            "bytesSentPerSec": 12.5,
            "bytesRecvPerSec": 40.0,
        }
    ],
}

BASE_PAYLOAD = {
    "collectedAt": "2026-08-12T11:15:27Z",
    "cpuInfo": {"coreCount": 8, "usagePercent": 42.5},
    "memoryInfo": {"totalMB": 16384, "usedMB": 4096},
    "diskInfo": {"totalGB": 512, "freeGB": 120},
    "systemInfo": {"name": "Windows", "version": "11", "hostName": "devbox"},
}


def record(**overrides):
    """A stand-in for a SnapshotRecord row. from_record() reads it structurally."""
    fields = {
        "collected_at": datetime(2026, 8, 12, 11, 15, 27, tzinfo=timezone.utc),
        "cpu_core_count": 8,
        "cpu_usage_percent": 42.5,
        "mem_total_mb": 16384,
        "mem_used_mb": 4096,
        "disk_total_gb": 512,
        "disk_free_gb": 120,
        "os_name": "Windows",
        "os_version": "11",
        "host_name": "devbox",
        "process_count": None,
        "process_top": None,
        "net_bytes_sent_per_sec": None,
        "net_bytes_recv_per_sec": None,
        "network_interfaces": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


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


def test_payload_without_process_or_network_still_validates():
    # The one-release compatibility window: an agent built before Sprint 7
    # sends neither block, and its payload must not be rejected.
    snapshot = Snapshot.from_payload(BASE_PAYLOAD)

    assert snapshot.processInfo is None
    assert snapshot.networkInfo is None


def test_full_payload_round_trips_the_process_and_network_blocks():
    snapshot = Snapshot.from_payload(
        {**BASE_PAYLOAD, "processInfo": PROCESS_BLOCK, "networkInfo": NETWORK_BLOCK}
    )

    assert snapshot.processInfo.count == 240
    assert [entry.name for entry in snapshot.processInfo.top] == ["chrome.exe", "System"]
    assert snapshot.networkInfo.interfaces[0].bytesRecvPerSec == 40.0


def test_from_record_rebuilds_the_nested_blocks_from_a_populated_row():
    snapshot = Snapshot.from_record(
        record(
            process_count=240,
            process_top=PROCESS_BLOCK["top"],
            net_bytes_sent_per_sec=12.5,
            net_bytes_recv_per_sec=40.0,
            network_interfaces=NETWORK_BLOCK["interfaces"],
        )
    )

    assert snapshot.processInfo.count == 240
    assert snapshot.processInfo.top[0].pid == 1234
    assert snapshot.networkInfo.interfaces[0].name == "Wi-Fi"


def test_from_record_leaves_the_blocks_none_for_a_legacy_row():
    # Every process/network column is NULL on a row written before Sprint 7.
    snapshot = Snapshot.from_record(record())

    assert snapshot.processInfo is None
    assert snapshot.networkInfo is None
