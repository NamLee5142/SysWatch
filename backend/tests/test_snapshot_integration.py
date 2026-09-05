"""End-to-end tests across the real API -> service -> AgentClient stack.

Only the agent's HTTP transport is stubbed. Every layer in between is the
real implementation, unlike the unit tests which replace SnapshotService
with a fake and so never exercise the wiring between them.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.alerts import AlertEngine
from app.client import AgentClient
from app.db import session as db_session
from app.db.models import Base
from app.main import create_app
from app.repositories import AlertRuleStore, AlertStore, SnapshotStore
from app.services.snapshot_poller import SnapshotPoller
from app.services.snapshot_service import SnapshotService
from config import get_settings

app = create_app()
client = TestClient(app, base_url="http://testserver/api")


@pytest.fixture(autouse=True)
def temp_database(tmp_path):
    """Point the whole stack at a throwaway database.

    /snapshot now writes what it fetches, so without this the suite would
    persist into the real syswatch.db.

    On a file, not in memory, unlike the rest of the suite. These tests run a
    real poller that writes while the test reads, and an in-memory engine gets
    a StaticPool - one DBAPI connection shared by every session, because each
    connection to ":memory:" would otherwise get its own private database. The
    poller committing then invalidates the cursor the reader is fetching from:

        sqlite3.InterfaceError: Cursor needed to be reset because of
        commit/rollback and can no longer be fetched from

    Nothing that ships is arranged that way. A deployed backend is file-backed,
    so every session checks out its own connection and WAL lets a read proceed
    while a write commits. The race belonged to the fixture, not to the code -
    and it only lost often enough to fail on a loaded CI runner, which is a bad
    way to find out.
    """
    db_session.dispose_engine()
    engine = db_session.init_engine(f"sqlite:///{(tmp_path / 'integration.db').as_posix()}")
    Base.metadata.create_all(engine)

    yield

    db_session.dispose_engine()

AGENT_SNAPSHOT_URL = f"{get_settings().agent_base_url}/snapshot"

AGENT_PAYLOAD = {
    "collectedAt": "2026-08-12T11:15:27Z",
    "cpuInfo": {"coreCount": 8, "usagePercent": 42.5},
    "memoryInfo": {"totalMB": 16384, "usedMB": 4096},
    "diskInfo": {"totalGB": 512, "freeGB": 120},
    "systemInfo": {"name": "Windows", "version": "11", "hostName": "devbox"},
}

# What a Sprint 7 agent sends: the same payload plus the process and network
# blocks.
AGENT_PAYLOAD_WITH_PROCESS_AND_NETWORK = {
    **AGENT_PAYLOAD,
    "processInfo": {
        "count": 240,
        "top": [{"pid": 1234, "name": "chrome.exe", "memoryMB": 512}],
    },
    "networkInfo": {
        "interfaces": [
            {
                "name": "Wi-Fi",
                "bytesSent": 1000,
                "bytesRecv": 2000,
                "bytesSentPerSec": 30.0,
                "bytesRecvPerSec": 90.0,
            }
        ],
    },
}


@respx.mock
def test_agent_snapshot_reaches_the_client_unchanged():
    route = respx.get(AGENT_SNAPSHOT_URL).respond(200, json=AGENT_PAYLOAD)

    response = client.get("/snapshot")

    assert route.called
    assert response.status_code == 200
    assert response.json() == AGENT_PAYLOAD


@respx.mock
def test_fetched_snapshot_is_persisted():
    respx.get(AGENT_SNAPSHOT_URL).respond(200, json=AGENT_PAYLOAD)

    assert client.get("/snapshot").status_code == 200

    stored = SnapshotStore().latest()
    assert stored is not None
    assert stored.host_name == "devbox"
    assert stored.cpu_core_count == 8
    assert stored.collected_at.isoformat() == "2026-08-12T11:15:27+00:00"


@respx.mock
def test_repeated_fetches_do_not_duplicate_a_snapshot():
    respx.get(AGENT_SNAPSHOT_URL).respond(200, json=AGENT_PAYLOAD)

    client.get("/snapshot")
    client.get("/snapshot")

    # Same collection time, so the unique constraint collapses the second write.
    assert len(SnapshotStore().query()) == 1


@respx.mock
def test_agent_204_becomes_404():
    respx.get(AGENT_SNAPSHOT_URL).respond(204)

    response = client.get("/snapshot")

    assert response.status_code == 404
    assert response.json()["detail"] == "No snapshot available yet"


@respx.mock
def test_agent_error_status_becomes_502():
    respx.get(AGENT_SNAPSHOT_URL).respond(500)

    response = client.get("/snapshot")

    assert response.status_code == 502
    assert "500" in response.json()["detail"]


@respx.mock
def test_malformed_agent_payload_becomes_502():
    respx.get(AGENT_SNAPSHOT_URL).respond(200, json={"cpuInfo": {"coreCount": "many"}})

    response = client.get("/snapshot")

    assert response.status_code == 502


@respx.mock
def test_non_json_agent_body_becomes_502():
    respx.get(AGENT_SNAPSHOT_URL).respond(200, text="<html>not json</html>")

    response = client.get("/snapshot")

    assert response.status_code == 502


@respx.mock
def test_unreachable_agent_becomes_503():
    respx.get(AGENT_SNAPSHOT_URL).mock(side_effect=httpx.ConnectError("connection refused"))

    response = client.get("/snapshot")

    assert response.status_code == 503
    assert response.json()["detail"] == "Unable to reach agent"


def run_poller_until(store, target_rows, timeout=3.0):
    """Run a real poller against the stubbed agent until enough rows land."""

    async def scenario():
        service = SnapshotService(
            client=AgentClient(get_settings().agent_base_url),
            store=store,
        )
        poller = SnapshotPoller(service, interval_seconds=0.01)
        poller.start()

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while store.count() < target_rows and loop.time() < deadline:
            await asyncio.sleep(0.01)

        await poller.stop()

    asyncio.run(scenario())


@respx.mock
def test_poller_fills_storage_without_anyone_calling_the_api():
    route = respx.get(AGENT_SNAPSHOT_URL).respond(200, json=AGENT_PAYLOAD)
    store = SnapshotStore()

    run_poller_until(store, target_rows=1)

    # The whole point of the sprint: history accumulates because the backend
    # collects, not because a client asked.
    assert route.called
    assert store.count() == 1


@respx.mock
def test_polling_the_same_collection_repeatedly_stores_one_row():
    respx.get(AGENT_SNAPSHOT_URL).respond(200, json=AGENT_PAYLOAD)
    store = SnapshotStore()

    run_poller_until(store, target_rows=1)
    run_poller_until(store, target_rows=2, timeout=0.3)

    # The agent keeps returning the same collection, so the unique constraint
    # collapses every repeat.
    assert store.count() == 1


@respx.mock
def test_process_and_network_data_flows_through_to_the_history_endpoints():
    respx.get(AGENT_SNAPSHOT_URL).respond(200, json=AGENT_PAYLOAD_WITH_PROCESS_AND_NETWORK)
    store = SnapshotStore()

    run_poller_until(store, target_rows=1)

    latest = client.get("/snapshots/latest").json()
    assert latest["processInfo"]["count"] == 240
    assert latest["processInfo"]["top"][0]["name"] == "chrome.exe"
    assert latest["networkInfo"]["interfaces"][0]["bytesRecvPerSec"] == 90.0

    processes = client.get("/snapshots/series", params={"metric": "processes", "bucket": "raw"}).json()
    assert processes["unit"] == "count"
    assert processes["points"][0]["value"] == 240.0

    received = client.get("/snapshots/series", params={"metric": "net_recv", "bucket": "raw"}).json()
    assert received["unit"] == "bytes_per_sec"
    assert received["points"][0]["value"] == 90.0


@respx.mock
def test_a_pre_sprint_7_agent_payload_still_flows_through():
    respx.get(AGENT_SNAPSHOT_URL).respond(200, json=AGENT_PAYLOAD)
    store = SnapshotStore()

    run_poller_until(store, target_rows=1)

    latest = client.get("/snapshots/latest").json()
    # No block invented where the agent reported none.
    assert "processInfo" not in latest
    assert "networkInfo" not in latest


@respx.mock
def test_collected_snapshots_are_served_by_the_history_endpoints():
    counter = {"n": 0}

    def respond(request):
        payload = dict(AGENT_PAYLOAD, collectedAt=f"2026-08-12T11:15:{27 + counter['n']:02d}Z")
        counter["n"] += 1
        return httpx.Response(200, json=payload)

    respx.get(AGENT_SNAPSHOT_URL).mock(side_effect=respond)
    store = SnapshotStore()

    run_poller_until(store, target_rows=3)

    page = client.get("/snapshots").json()
    assert page["count"] >= 3
    times = [item["collectedAt"] for item in page["items"]]
    assert times == sorted(times, reverse=True)

    latest = client.get("/snapshots/latest").json()
    assert latest["collectedAt"] == times[0]
    assert latest["systemInfo"]["hostName"] == "devbox"


BASE_TIME = datetime(2026, 8, 12, 11, 15, 27, tzinfo=timezone.utc)


def run_alert_poller_until(condition, timeout=3.0):
    """Run a real poller with the alert engine wired in, until condition() holds."""

    async def scenario():
        store = SnapshotStore()
        service = SnapshotService(
            client=AgentClient(get_settings().agent_base_url),
            store=store,
        )
        engine = AlertEngine(AlertRuleStore(), AlertStore())
        poller = SnapshotPoller(service, interval_seconds=0.01, engine=engine)
        poller.start()

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not condition() and loop.time() < deadline:
            await asyncio.sleep(0.01)

        await poller.stop()

    asyncio.run(scenario())


@respx.mock
def test_an_alert_fires_and_resolves_through_the_full_poller_stack():
    AlertRuleStore().create(
        SimpleNamespace(
            name="CPU high", metric="cpu", operator="gt", threshold=90,
            severity="critical", enabled=True,
        )
    )

    state = {"cpu": 96.0, "seq": 0}

    def respond(request):
        state["seq"] += 1
        collected_at = (BASE_TIME + timedelta(seconds=state["seq"])).isoformat()
        payload = dict(
            AGENT_PAYLOAD,
            collectedAt=collected_at,
            cpuInfo={"coreCount": 8, "usagePercent": state["cpu"]},
        )
        return httpx.Response(200, json=payload)

    respx.get(AGENT_SNAPSHOT_URL).mock(side_effect=respond)
    alerts = AlertStore()

    # Breaching CPU -> an alert opens, visible on the API.
    run_alert_poller_until(lambda: len(alerts.active()) >= 1)

    active = client.get("/alerts/active").json()["items"]
    assert len(active) == 1
    assert active[0]["ruleName"] == "CPU high"
    assert active[0]["severity"] == "critical"
    assert active[0]["value"] > 90

    # CPU recovers -> the same alert resolves, moving into history.
    state["cpu"] = 8.0
    run_alert_poller_until(lambda: len(alerts.active()) == 0)

    assert client.get("/alerts/active").json()["items"] == []
    history = client.get("/alerts", params={"state": "ok"}).json()
    assert history["count"] == 1
    assert history["items"][0]["resolvedAt"] is not None
