"""Everything that can fail on the way out, failing at once.

Delivery is the newest thing on the poll path and the only part of it that
depends on a machine nobody here controls. A mail server goes down, a webhook
endpoint is redeployed, a certificate expires over a weekend - none of which
are reasons to stop monitoring.

The rule these tests hold to: the database row is the durable thing and the
message is a courtesy on top of it. Sending fails, the record does not.

Unit tests elsewhere check this against fakes. These run the real poller,
service, engine and stores against a real database, because the failure mode
worth guarding against is not "the engine catches an exception" - it is a
notifier raising somewhere that unwinds the poll loop, or a blocking transport
that never returns.
"""
import asyncio
import logging

import httpx
import pytest
import respx

from app.alerts import AlertEngine
from app.alerts.notifier import Notifier, build_notifier
from app.client import AgentClient
from app.db import session as db_session
from app.db.models import Base
from app.repositories import AlertRuleStore, AlertStore, SnapshotStore
from app.services.snapshot_poller import SnapshotPoller
from app.services.snapshot_service import SnapshotService
from config import Settings, get_settings

AGENT_SNAPSHOT_URL = f"{get_settings().agent_base_url}/snapshot"

WEBHOOK_URL = "https://hooks.example.test/T0/B0/S3CR3T"

# Nothing listens here. A real connection attempt, not a stub, so the SMTP
# transport takes the same code path an operator's dead mail server would.
DEAD_SMTP_PORT = 59_999


def payload(cpu, minute):
    # A distinct collectedAt per reading. snapshots is unique on
    # (host_name, collected_at), so two readings sharing an instant collapse
    # into one row - correctly, and confusingly if a test did not mean it.
    return {
        "collectedAt": f"2026-09-06T11:{minute:02d}:00Z",
        "cpuInfo": {"coreCount": 8, "usagePercent": cpu},
        "memoryInfo": {"totalMB": 16384, "usedMB": 4096},
        "diskInfo": {"totalGB": 512, "freeGB": 120},
        "systemInfo": {"name": "Windows", "version": "11", "hostName": "devbox"},
    }


@pytest.fixture(autouse=True)
def temp_database(tmp_path):
    """File-backed, like test_snapshot_integration.py and for the same reason.

    An in-memory engine shares one connection across every session, so a poller
    committing while the test reads invalidates the reader's cursor. That race
    does not exist in anything that ships.
    """
    db_session.dispose_engine()
    engine = db_session.init_engine(
        f"sqlite:///{(tmp_path / 'delivery.db').as_posix()}"
    )
    Base.metadata.create_all(engine)

    yield

    db_session.dispose_engine()


@pytest.fixture
def seeded_rules():
    """Two rules a high CPU reading breaches, and a low one clears.

    Two, not one, deliberately. The engine announces a state change from inside
    its per-rule loop, so a notifier that raises would abort the rules after it
    - and with a single rule there is nothing after it to lose. The second rule
    is what makes "delivery failed" distinguishable from "evaluation stopped".
    """
    from app.models.alert import AlertRuleCreate

    store = AlertRuleStore()
    return [
        store.create(
            AlertRuleCreate(
                name=name,
                metric="cpu",
                operator="gt",
                threshold=threshold,
                severity="critical",
            )
        )
        for name, threshold in (("CPU usage high", 80.0), ("CPU usage critical", 90.0))
    ]


class Exploding(Notifier):
    """A notifier that fails the way a badly written one would."""

    def deliver(self, change, alert):
        raise RuntimeError("everything is on fire")


def run_poller(notifier, ticks=3, cpu_values=(95.0, 95.0, 5.0), until=None):
    """Drive the real poller through a sequence of agent readings.

    `until` is the condition to stop on. Snapshot count alone is a proxy, and a
    misleading one: the poller stores a snapshot and then evaluates alerts on a
    worker thread, so the row lands before the evaluation it triggers has
    finished. A test that waits for rows and then asserts on alerts is racing
    its own subject - which this one did, and lost about half the time.
    """
    store = SnapshotStore()
    engine = AlertEngine(AlertRuleStore(), AlertStore(), notifier=notifier)

    async def scenario():
        service = SnapshotService(
            client=AgentClient(get_settings().agent_base_url), store=store
        )
        poller = SnapshotPoller(
            service, interval_seconds=0.01, store=store, engine=engine
        )
        poller.start()

        done = until or (lambda: store.count() >= ticks)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + 10.0
        while not done() and loop.time() < deadline:
            await asyncio.sleep(0.01)

        await poller.stop()

    # The last reading repeats once the sequence runs out: the poller ticks
    # faster than the readings are consumed, and a still-firing (or still-clear)
    # repeat is what a real agent would return anyway.
    readings = list(cpu_values) + [cpu_values[-1]] * 40

    with respx.mock:
        route = respx.get(AGENT_SNAPSHOT_URL)
        route.side_effect = [
            httpx.Response(200, json=payload(cpu, minute))
            for minute, cpu in enumerate(readings)
        ]
        asyncio.run(scenario())

    return store


# --- each transport, failing on its own -------------------------------------


def test_a_dead_mail_server_does_not_stop_collection(seeded_rules, caplog):
    notifier = build_notifier(
        Settings(
            smtp_host="127.0.0.1",
            smtp_port=DEAD_SMTP_PORT,
            smtp_from="syswatch@example.test",
            smtp_to=["ops@example.test"],
            notify_min_severity="info",
        )
    )

    with caplog.at_level(logging.WARNING):
        store = run_poller(notifier)

    assert store.count() >= 3
    assert "Could not deliver" in caplog.text


@respx.mock
def test_a_webhook_that_times_out_does_not_stop_collection(seeded_rules, caplog):
    respx.post(WEBHOOK_URL).mock(side_effect=httpx.ReadTimeout("too slow"))
    notifier = build_notifier(
        Settings(webhook_url=WEBHOOK_URL, notify_min_severity="info")
    )

    with caplog.at_level(logging.WARNING):
        store = run_poller(notifier)

    assert store.count() >= 3
    assert "Could not deliver" in caplog.text


def test_a_notifier_that_raises_does_not_stop_collection(seeded_rules):
    store = run_poller(Exploding())

    assert store.count() >= 3


# --- everything failing at once ---------------------------------------------


@respx.mock
def test_alerts_still_open_and_resolve_with_every_transport_broken(seeded_rules):
    """The plan's acceptance condition.

    Mail refused, webhook timing out, and a notifier raising outright - and the
    alert lifecycle in the database is unchanged.
    """
    respx.post(WEBHOOK_URL).mock(side_effect=httpx.ConnectError("refused"))

    from app.alerts.notifier import CompositeNotifier

    notifier = CompositeNotifier(
        [
            Exploding(),
            *build_notifier(
                Settings(
                    smtp_host="127.0.0.1",
                    smtp_port=DEAD_SMTP_PORT,
                    smtp_from="syswatch@example.test",
                    smtp_to=["ops@example.test"],
                    webhook_url=WEBHOOK_URL,
                    notify_min_severity="info",
                )
            )._notifiers,
        ]
    )

    def both_rules_have_opened_and_closed():
        history = AlertStore().query(host_name="devbox")
        return len(history) == 2 and all(alert.state == "ok" for alert in history)

    store = run_poller(
        notifier,
        cpu_values=(95.0, 95.0, 5.0),
        until=both_rules_have_opened_and_closed,
    )

    assert store.count() >= 3

    alerts = AlertStore()
    history = alerts.query(host_name="devbox")

    # Both rules opened and both closed. One row each - not a new row per tick
    # - and none left marked firing.
    #
    # Two matters here: the engine announces from inside its per-rule loop, so a
    # notifier that raised without being caught would abort the loop and the
    # second rule would never evaluate at all.
    assert len(history) == 2
    assert {alert.rule_name for alert in history} == {
        "CPU usage high",
        "CPU usage critical",
    }
    assert all(alert.state == "ok" for alert in history)
    assert all(alert.resolved_at is not None for alert in history)
    assert alerts.active("devbox") == []


@respx.mock
def test_the_webhook_token_never_reaches_the_log_when_everything_fails(
    seeded_rules, tmp_path
):
    """The failure path is where a URL is most likely to be printed."""
    import logging as std_logging

    from app.logging_config import configure_logging

    respx.post(WEBHOOK_URL).mock(side_effect=httpx.ConnectError("refused"))
    path = configure_logging(
        Settings(log_dir=str(tmp_path), log_level="DEBUG", dev_mode=True)
    )

    run_poller(
        build_notifier(Settings(webhook_url=WEBHOOK_URL, notify_min_severity="info"))
    )

    std_logging.shutdown()
    assert "S3CR3T" not in path.read_text(encoding="utf-8", errors="replace")
