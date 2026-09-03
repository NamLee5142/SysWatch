from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.db import session as db_session
from app.db.models import Base
from app.main import create_app
from app.models.snapshot import Snapshot
from app.repositories import SnapshotStore

BASE_TIME = datetime(2026, 8, 25, 10, 0, 0, tzinfo=timezone.utc)

app = create_app()
client = TestClient(app, base_url="http://testserver/api")


@pytest.fixture(autouse=True)
def store():
    db_session.dispose_engine()
    engine = db_session.init_engine("sqlite://")
    Base.metadata.create_all(engine)

    yield SnapshotStore()

    db_session.dispose_engine()


def save(store, host_name="devbox", collected_at=BASE_TIME):
    store.save(
        Snapshot.from_payload(
            {
                "collectedAt": collected_at.isoformat(),
                "cpuInfo": {"coreCount": 8, "usagePercent": 42.5},
                "memoryInfo": {"totalMB": 16384, "usedMB": 4096},
                "diskInfo": {"totalGB": 512, "freeGB": 120},
                "systemInfo": {"name": "Windows", "version": "11", "hostName": host_name},
            }
        )
    )


def test_no_hosts_returns_an_empty_list(store):
    response = client.get("/hosts")

    # Not a 404: a fresh database should render an empty selector, not an error.
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_host_is_listed_once_however_many_snapshots_it_has(store):
    for minutes in range(3):
        save(store, collected_at=BASE_TIME + timedelta(minutes=minutes))

    items = client.get("/hosts").json()["items"]

    assert len(items) == 1
    assert items[0]["hostName"] == "devbox"
    assert items[0]["snapshotCount"] == 3


def test_last_collected_at_is_the_newest_snapshot(store):
    save(store, collected_at=BASE_TIME)
    save(store, collected_at=BASE_TIME + timedelta(minutes=30))
    save(store, collected_at=BASE_TIME - timedelta(minutes=30))

    item = client.get("/hosts").json()["items"][0]

    assert item["lastCollectedAt"] == "2026-08-25T10:30:00Z"


def test_hosts_are_ordered_by_most_recent_activity(store):
    save(store, host_name="quiet", collected_at=BASE_TIME - timedelta(days=1))
    save(store, host_name="busy", collected_at=BASE_TIME)
    save(store, host_name="idle", collected_at=BASE_TIME - timedelta(hours=1))

    names = [item["hostName"] for item in client.get("/hosts").json()["items"]]

    assert names == ["busy", "idle", "quiet"]


def test_hosts_sharing_a_last_collection_time_keep_a_stable_order(store):
    save(store, host_name="beta", collected_at=BASE_TIME)
    save(store, host_name="alpha", collected_at=BASE_TIME)

    names = [item["hostName"] for item in client.get("/hosts").json()["items"]]

    # Tie broken by name, so two hosts cannot swap places between requests.
    assert names == ["alpha", "beta"]


def test_counts_are_per_host(store):
    for minutes in range(4):
        save(store, host_name="devbox", collected_at=BASE_TIME + timedelta(minutes=minutes))
    save(store, host_name="buildbox", collected_at=BASE_TIME)

    counts = {item["hostName"]: item["snapshotCount"] for item in client.get("/hosts").json()["items"]}

    assert counts == {"devbox": 4, "buildbox": 1}


def test_last_collected_at_is_utc_tagged(store):
    save(store)

    last_collected_at = client.get("/hosts").json()["items"][0]["lastCollectedAt"]

    # The aggregate bypasses the store's usual hydration, so this is the one
    # place the UTC tag could be dropped and read back as local time.
    assert last_collected_at.endswith("Z")
