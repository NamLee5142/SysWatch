from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.alerts.evaluator import evaluate, is_violated, snapshot_metric_value
from app.models.snapshot import Snapshot

BASE_TIME = datetime(2026, 8, 12, 11, 15, 27, tzinfo=timezone.utc)


def make_snapshot(
    cpu_usage=42.5,
    mem_total=16384,
    mem_used=4096,
    disk_total=512,
    disk_free=120,
    process_count=None,
    net_sent=None,
    net_recv=None,
):
    payload = {
        "collectedAt": BASE_TIME.isoformat(),
        "cpuInfo": {"coreCount": 8, "usagePercent": cpu_usage},
        "memoryInfo": {"totalMB": mem_total, "usedMB": mem_used},
        "diskInfo": {"totalGB": disk_total, "freeGB": disk_free},
        "systemInfo": {"name": "Windows", "version": "11", "hostName": "devbox"},
    }

    if process_count is not None:
        payload["processInfo"] = {
            "count": process_count,
            "top": [{"pid": 1, "name": "top.exe", "memoryMB": 10}],
        }

    if net_sent is not None or net_recv is not None:
        # Split across two interfaces so the evaluator's sum is exercised.
        payload["networkInfo"] = {
            "interfaces": [
                {
                    "name": name,
                    "bytesSent": 0,
                    "bytesRecv": 0,
                    "bytesSentPerSec": (net_sent or 0) / 2,
                    "bytesRecvPerSec": (net_recv or 0) / 2,
                }
                for name in ("Ethernet", "Wi-Fi")
            ],
        }

    return Snapshot.from_payload(payload)


def rule(metric="cpu", operator="gt", threshold=0.0):
    return SimpleNamespace(metric=metric, operator=operator, threshold=threshold)


# --- snapshot_metric_value ---------------------------------------------------


def test_cpu_value_is_the_usage_percent():
    assert snapshot_metric_value("cpu", make_snapshot(cpu_usage=73.0)) == 73.0


def test_memory_value_is_a_used_percent():
    # 4096 / 16384 = 25%
    assert snapshot_metric_value("memory", make_snapshot()) == 25.0


def test_disk_value_is_a_used_percent():
    # (512 - 120) / 512 = 76.5625%
    assert snapshot_metric_value("disk", make_snapshot()) == pytest.approx(76.5625)


def test_processes_value_is_the_count():
    assert snapshot_metric_value("processes", make_snapshot(process_count=431)) == 431.0


def test_network_values_are_summed_across_interfaces():
    snapshot = make_snapshot(net_sent=2000.0, net_recv=8000.0)

    assert snapshot_metric_value("net_sent", snapshot) == 2000.0
    assert snapshot_metric_value("net_recv", snapshot) == 8000.0


@pytest.mark.parametrize("metric", ["processes", "net_sent", "net_recv"])
def test_metric_is_none_when_the_agent_sent_no_such_block(metric):
    assert snapshot_metric_value(metric, make_snapshot()) is None


def test_no_traffic_is_zero_not_absent():
    snapshot = make_snapshot(net_sent=0.0)

    assert snapshot_metric_value("net_sent", snapshot) == 0.0


@pytest.mark.parametrize("metric", ["memory", "disk"])
def test_a_zero_total_yields_none_rather_than_dividing(metric):
    snapshot = make_snapshot(mem_total=0, disk_total=0)

    assert snapshot_metric_value(metric, snapshot) is None


def test_unknown_metric_raises():
    with pytest.raises(ValueError, match="Unknown metric"):
        snapshot_metric_value("gpu", make_snapshot())


# --- is_violated ------------------------------------------------------------


@pytest.mark.parametrize(
    "operator, threshold, expected",
    [
        ("gt", 40, True),
        ("gt", 50, False),
        ("gt", 60, False),
        ("gte", 50, True),
        ("gte", 51, False),
        ("lt", 60, True),
        ("lt", 50, False),
        ("lt", 40, False),
        ("lte", 50, True),
        ("lte", 49, False),
    ],
)
def test_every_operator(operator, threshold, expected):
    assert is_violated(rule(operator=operator, threshold=threshold), 50.0) is expected


def test_absent_value_is_not_a_violation():
    assert is_violated(rule(operator="gt", threshold=0), None) is False
    assert is_violated(rule(operator="lt", threshold=100), None) is False


def test_unknown_operator_raises():
    with pytest.raises(ValueError, match="Unknown operator"):
        is_violated(rule(operator="ne", threshold=1), 5.0)


# --- evaluate --------------------------------------------------------------


def test_evaluate_returns_value_and_outcome():
    value, violated = evaluate(rule("cpu", "gt", 40), make_snapshot(cpu_usage=91.0))

    assert value == 91.0
    assert violated is True


def test_evaluate_of_an_absent_metric_is_none_and_not_violated():
    value, violated = evaluate(rule("processes", "gt", 1), make_snapshot())

    assert value is None
    assert violated is False
