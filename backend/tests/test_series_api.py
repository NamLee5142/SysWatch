from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from app.api.snapshots import MAX_POINTS
from app.db import session as db_session
from app.db.models import Base, SnapshotRecord
from app.main import create_app
from app.models.snapshot import Snapshot
from app.repositories import SnapshotStore

BASE_TIME = datetime(2026, 8, 25, 10, 0, 0, tzinfo=timezone.utc)

app = create_app()
client = TestClient(app)


@pytest.fixture(autouse=True)
def store():
    db_session.dispose_engine()
    engine = db_session.init_engine("sqlite://")
    Base.metadata.create_all(engine)

    yield SnapshotStore()

    db_session.dispose_engine()


def save(
    store,
    minutes=0,
    cpu=50.0,
    host_name="devbox",
    used_mb=4096,
    total_mb=16384,
    free_gb=112,
    total_gb=512,
    process_count=None,
    net_recv=None,
):
    payload = {
        "collectedAt": (BASE_TIME + timedelta(minutes=minutes)).isoformat(),
        "cpuInfo": {"coreCount": 8, "usagePercent": cpu},
        "memoryInfo": {"totalMB": total_mb, "usedMB": used_mb},
        "diskInfo": {"totalGB": total_gb, "freeGB": free_gb},
        "systemInfo": {"name": "Windows", "version": "11", "hostName": host_name},
    }

    if process_count is not None:
        payload["processInfo"] = {"count": process_count, "top": []}

    if net_recv is not None:
        payload["networkInfo"] = {
            "interfaces": [
                {
                    "name": "Wi-Fi",
                    "bytesSent": 0,
                    "bytesRecv": 0,
                    "bytesSentPerSec": 0.0,
                    "bytesRecvPerSec": net_recv,
                }
            ],
        }

    store.save(Snapshot.from_payload(payload))


def series(**params):
    params.setdefault("metric", "cpu")
    return client.get("/snapshots/series", params=params)


def values(**params):
    return [point["value"] for point in series(**params).json()["points"]]


def test_no_data_returns_an_empty_series(store):
    body = series(bucket="hour").json()

    assert body == {"metric": "cpu", "bucket": "hour", "unit": "percent", "points": []}


def test_raw_bucket_returns_every_sample(store):
    for minutes, cpu in ((0, 10.0), (20, 20.0), (40, 30.0)):
        save(store, minutes=minutes, cpu=cpu)

    assert values(bucket="raw") == [10.0, 20.0, 30.0]


def test_hour_bucket_averages_within_the_hour(store):
    for minutes, cpu in ((0, 10.0), (20, 20.0), (40, 30.0)):
        save(store, minutes=minutes, cpu=cpu)
    for minutes, cpu in ((60, 60.0), (80, 80.0)):
        save(store, minutes=minutes, cpu=cpu)

    body = series(bucket="hour").json()

    assert [point["value"] for point in body["points"]] == [20.0, 70.0]
    # The bucket label is the start of the window, not the first sample in it.
    assert [point["t"] for point in body["points"]] == [
        "2026-08-25T10:00:00Z",
        "2026-08-25T11:00:00Z",
    ]


def test_day_bucket_collapses_everything_into_one_point(store):
    for minutes, cpu in ((0, 10.0), (60, 30.0), (600, 50.0)):
        save(store, minutes=minutes, cpu=cpu)

    body = series(bucket="day").json()

    assert len(body["points"]) == 1
    assert body["points"][0]["value"] == 30.0
    assert body["points"][0]["t"] == "2026-08-25T00:00:00Z"


def test_series_is_oldest_first(store):
    for minutes in (40, 0, 20):
        save(store, minutes=minutes)

    times = [point["t"] for point in series(bucket="raw").json()["points"]]

    assert times == sorted(times)


def test_series_runs_opposite_to_the_history_page(store):
    for minutes in range(3):
        save(store, minutes=minutes)

    chart = [point["t"] for point in series(bucket="raw").json()["points"]]
    page = [item["collectedAt"] for item in client.get("/snapshots").json()["items"]]

    # A chart reads left to right; a page of history reads newest first.
    # Getting these the same way round is what silently flips an axis.
    assert chart == list(reversed(page))


def test_process_series_reports_a_count_unit(store):
    save(store, minutes=0, process_count=100)
    save(store, minutes=20, process_count=140)

    body = series(metric="processes", bucket="hour").json()

    assert body["unit"] == "count"
    assert [point["value"] for point in body["points"]] == [120.0]


def test_network_series_reports_a_bytes_per_sec_unit(store):
    save(store, minutes=0, net_recv=2048.0)

    body = series(metric="net_recv", bucket="raw").json()

    assert body["unit"] == "bytes_per_sec"
    assert [point["value"] for point in body["points"]] == [2048.0]


def test_a_percentage_metric_still_reports_a_percent_unit(store):
    save(store)

    assert series(metric="cpu", bucket="raw").json()["unit"] == "percent"


def test_memory_is_reported_as_a_percentage(store):
    save(store, used_mb=4096, total_mb=16384)

    assert values(metric="memory", bucket="raw") == [25.0]


def test_disk_is_reported_as_used_percentage(store):
    # The agent sends free, not used, so the endpoint has to derive it.
    save(store, total_gb=512, free_gb=112)

    assert values(metric="disk", bucket="raw") == [78.125]


def test_zero_totals_are_dropped_rather_than_plotted_as_zero(store):
    save(store, minutes=0, total_gb=512, free_gb=112)
    save(store, minutes=10, total_gb=0, free_gb=0)

    # A zero total means the collector had nothing to report. Plotting 0% would
    # read as an empty disk.
    assert values(metric="disk", bucket="raw") == [78.125]


def test_filters_by_host(store):
    save(store, host_name="devbox", cpu=10.0)
    save(store, host_name="buildbox", cpu=90.0)

    assert values(bucket="raw", host="buildbox") == [90.0]


def test_unknown_host_is_an_empty_series_not_an_error(store):
    save(store)

    response = series(bucket="raw", host="nosuchbox")

    assert response.status_code == 200
    assert response.json()["points"] == []


def test_filters_by_time_window(store):
    for minutes, cpu in ((0, 10.0), (10, 20.0), (20, 30.0), (30, 40.0)):
        save(store, minutes=minutes, cpu=cpu)

    plotted = values(
        bucket="raw",
        since=(BASE_TIME + timedelta(minutes=10)).isoformat(),
        until=(BASE_TIME + timedelta(minutes=20)).isoformat(),
    )

    assert plotted == [20.0, 30.0]


def test_reversed_window_is_rejected(store):
    response = series(
        since=(BASE_TIME + timedelta(minutes=10)).isoformat(),
        until=BASE_TIME.isoformat(),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "since must not be after until"


def test_bucket_defaults_to_hour(store):
    save(store)

    assert series().json()["bucket"] == "hour"


@pytest.mark.parametrize(
    "params",
    [
        {"metric": "gpu"},
        {"metric": "cpu", "bucket": "fortnight"},
        {"metric": "cpu", "since": "not-a-time"},
        {},
    ],
)
def test_invalid_parameters_are_rejected(store, params):
    assert client.get("/snapshots/series", params=params).status_code == 422


def test_too_many_points_is_refused_rather_than_truncated(store):
    engine = db_session.get_engine()
    naive_base = BASE_TIME.replace(tzinfo=None)
    rows = [
        {
            "host_name": "devbox",
            "collected_at": naive_base + timedelta(seconds=10 * index),
            "cpu_core_count": 8,
            "cpu_usage_percent": 50.0,
            "mem_total_mb": 16384,
            "mem_used_mb": 4096,
            "disk_total_gb": 512,
            "disk_free_gb": 112,
            "os_name": "Windows",
            "os_version": "11",
        }
        for index in range(MAX_POINTS + 1)
    ]
    with engine.begin() as connection:
        connection.execute(insert(SnapshotRecord), rows)

    response = series(bucket="raw")

    # Truncating would draw a chart labelled with a range it does not cover.
    assert response.status_code == 422
    assert str(MAX_POINTS) in response.json()["detail"]


def test_a_coarser_bucket_brings_the_same_window_back_under_the_cap(store):
    engine = db_session.get_engine()
    naive_base = BASE_TIME.replace(tzinfo=None)
    rows = [
        {
            "host_name": "devbox",
            "collected_at": naive_base + timedelta(seconds=10 * index),
            "cpu_core_count": 8,
            "cpu_usage_percent": 50.0,
            "mem_total_mb": 16384,
            "mem_used_mb": 4096,
            "disk_total_gb": 512,
            "disk_free_gb": 112,
            "os_name": "Windows",
            "os_version": "11",
        }
        for index in range(MAX_POINTS + 1)
    ]
    with engine.begin() as connection:
        connection.execute(insert(SnapshotRecord), rows)

    response = series(bucket="hour")

    # Which is exactly what the 422 above tells the caller to do.
    assert response.status_code == 200
    assert 0 < len(response.json()["points"]) <= MAX_POINTS
