from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.db import session as db_session
from app.db.models import Base
from app.main import create_app
from app.models.snapshot import Snapshot
from app.repositories import SnapshotStore

BASE_TIME = datetime(2026, 8, 12, 11, 15, 27, tzinfo=timezone.utc)

app = create_app()
client = TestClient(app)


@pytest.fixture(autouse=True)
def store():
    db_session.dispose_engine()
    engine = db_session.init_engine("sqlite://")
    Base.metadata.create_all(engine)

    yield SnapshotStore()

    db_session.dispose_engine()


def save(store, host_name="devbox", collected_at=BASE_TIME, cpu_usage=42.5):
    store.save(
        Snapshot.from_payload(
            {
                "collectedAt": collected_at.isoformat(),
                "cpuInfo": {"coreCount": 8, "usagePercent": cpu_usage},
                "memoryInfo": {"totalMB": 16384, "usedMB": 4096},
                "diskInfo": {"totalGB": 512, "freeGB": 120},
                "systemInfo": {"name": "Windows", "version": "11", "hostName": host_name},
            }
        )
    )


def test_empty_history_returns_an_empty_page(store):
    response = client.get("/snapshots")

    assert response.status_code == 200
    assert response.json() == {"items": [], "count": 0}


def test_stored_snapshot_is_returned_in_the_agent_shape(store):
    save(store)

    body = client.get("/snapshots").json()

    assert body["count"] == 1
    item = body["items"][0]
    # Same nested shape as GET /snapshot, so a client needs only one parser.
    assert item["cpuInfo"] == {"coreCount": 8, "usagePercent": 42.5}
    assert item["memoryInfo"] == {"totalMB": 16384, "usedMB": 4096}
    assert item["diskInfo"] == {"totalGB": 512, "freeGB": 120}
    assert item["systemInfo"] == {"name": "Windows", "version": "11", "hostName": "devbox"}
    assert item["collectedAt"] == "2026-08-12T11:15:27Z"


def test_history_is_newest_first(store):
    for minutes in (0, 10, 5):
        save(store, collected_at=BASE_TIME + timedelta(minutes=minutes))

    times = [item["collectedAt"] for item in client.get("/snapshots").json()["items"]]

    assert times == sorted(times, reverse=True)


def test_filters_by_host(store):
    save(store, host_name="devbox")
    save(store, host_name="buildbox")

    body = client.get("/snapshots", params={"host": "buildbox"}).json()

    assert body["count"] == 1
    assert body["items"][0]["systemInfo"]["hostName"] == "buildbox"


def test_filters_by_time_window(store):
    for minutes in (0, 10, 20, 30):
        save(store, collected_at=BASE_TIME + timedelta(minutes=minutes))

    body = client.get(
        "/snapshots",
        params={
            "since": (BASE_TIME + timedelta(minutes=10)).isoformat(),
            "until": (BASE_TIME + timedelta(minutes=20)).isoformat(),
        },
    ).json()

    assert body["count"] == 2


def test_count_is_the_total_not_the_page_size(store):
    for minutes in range(5):
        save(store, collected_at=BASE_TIME + timedelta(minutes=minutes))

    body = client.get("/snapshots", params={"limit": 2}).json()

    # Two returned, but the caller can see there are five to page through.
    assert len(body["items"]) == 2
    assert body["count"] == 5


def test_paging_does_not_repeat_or_skip_rows(store):
    for minutes in range(5):
        save(store, collected_at=BASE_TIME + timedelta(minutes=minutes))

    first = client.get("/snapshots", params={"limit": 2, "offset": 0}).json()["items"]
    second = client.get("/snapshots", params={"limit": 2, "offset": 2}).json()["items"]
    third = client.get("/snapshots", params={"limit": 2, "offset": 4}).json()["items"]

    seen = [item["collectedAt"] for item in first + second + third]

    assert len(seen) == 5
    assert len(set(seen)) == 5


def test_reversed_window_is_rejected(store):
    response = client.get(
        "/snapshots",
        params={
            "since": (BASE_TIME + timedelta(minutes=10)).isoformat(),
            "until": BASE_TIME.isoformat(),
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "since must not be after until"


def test_mixed_aware_and_naive_bounds_are_comparable(store):
    save(store)

    # An aware since against a naive until must not blow up on comparison.
    response = client.get(
        "/snapshots",
        params={
            "since": (BASE_TIME - timedelta(minutes=1)).isoformat(),
            "until": "2026-08-12T11:16:27",
        },
    )

    assert response.status_code == 200
    assert response.json()["count"] == 1


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 1001},
        {"limit": -1},
        {"offset": -1},
        {"since": "not-a-time"},
    ],
)
def test_invalid_paging_and_time_values_are_rejected(store, params):
    assert client.get("/snapshots", params=params).status_code == 422


def test_limit_is_capped_at_the_documented_maximum(store):
    assert client.get("/snapshots", params={"limit": 1000}).status_code == 200
    assert client.get("/snapshots", params={"limit": 1001}).status_code == 422
