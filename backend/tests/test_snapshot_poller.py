import asyncio

import pytest

from app.client.errors import AgentConnectionError
from app.services.snapshot_poller import SnapshotPoller


class FakeService:
    """Stands in for SnapshotService, counting calls and raising on demand."""

    def __init__(self, errors=()):
        self.calls = 0
        self.errors = list(errors)

    def get_snapshot(self):
        self.calls += 1
        if self.errors:
            error = self.errors.pop(0)
            if error is not None:
                raise error
        return "snapshot"


async def wait_for(condition, timeout=2.0):
    """Poll until condition() is true, so tests never depend on wall-clock timing."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.01)
    return False


def test_poll_once_fetches_and_stores():
    service = FakeService()

    asyncio.run(SnapshotPoller(service).poll_once())

    assert service.calls == 1


def test_unreachable_agent_does_not_raise():
    service = FakeService(errors=[AgentConnectionError("connection refused")])

    # Must not propagate: an exception here would kill the polling loop.
    asyncio.run(SnapshotPoller(service).poll_once())

    assert service.calls == 1


def test_missing_snapshot_does_not_raise():
    service = FakeService(errors=[LookupError("No snapshot available yet")])

    asyncio.run(SnapshotPoller(service).poll_once())

    assert service.calls == 1


def test_failure_is_logged_as_a_warning(caplog):
    service = FakeService(errors=[RuntimeError("agent returned 500")])

    with caplog.at_level("WARNING"):
        asyncio.run(SnapshotPoller(service).poll_once())

    assert "Snapshot poll failed" in caplog.text


def test_missing_snapshot_is_not_logged_as_a_warning(caplog):
    service = FakeService(errors=[LookupError("No snapshot available yet")])

    with caplog.at_level("WARNING"):
        asyncio.run(SnapshotPoller(service).poll_once())

    # An agent that has not collected yet is normal, not a problem to report.
    assert caplog.text == ""


def test_loop_polls_repeatedly():
    async def scenario():
        service = FakeService()
        poller = SnapshotPoller(service, interval_seconds=0.01)
        poller.start()

        polled = await wait_for(lambda: service.calls >= 3)
        await poller.stop()
        return polled

    assert asyncio.run(scenario())


def test_loop_survives_a_failing_poll():
    async def scenario():
        # First tick fails, the loop must keep going.
        service = FakeService(errors=[AgentConnectionError("down"), None])
        poller = SnapshotPoller(service, interval_seconds=0.01)
        poller.start()

        recovered = await wait_for(lambda: service.calls >= 3)
        await poller.stop()
        return recovered

    assert asyncio.run(scenario())


def test_stop_ends_the_loop():
    async def scenario():
        service = FakeService()
        poller = SnapshotPoller(service, interval_seconds=0.01)
        poller.start()
        await wait_for(lambda: service.calls >= 1)

        await poller.stop()
        assert not poller.running

        calls_at_stop = service.calls
        await asyncio.sleep(0.05)
        return calls_at_stop, service.calls

    calls_at_stop, calls_after = asyncio.run(scenario())
    assert calls_after == calls_at_stop


def test_start_is_idempotent():
    async def scenario():
        poller = SnapshotPoller(FakeService(), interval_seconds=0.01)
        poller.start()
        first = poller._task
        poller.start()
        second = poller._task

        await poller.stop()
        return first is second

    assert asyncio.run(scenario())


def test_stop_without_start_is_safe():
    asyncio.run(SnapshotPoller(FakeService()).stop())


def test_stop_is_idempotent():
    async def scenario():
        poller = SnapshotPoller(FakeService(), interval_seconds=0.01)
        poller.start()
        await poller.stop()
        await poller.stop()

    asyncio.run(scenario())


def test_blocking_call_does_not_stall_the_event_loop():
    async def scenario():
        import time

        class BlockingService:
            def __init__(self):
                self.calls = 0

            def get_snapshot(self):
                self.calls += 1
                time.sleep(0.2)  # a slow or hanging agent
                return "snapshot"

        poller = SnapshotPoller(BlockingService(), interval_seconds=0.01)
        poller.start()

        # If the blocking fetch ran on the event loop, this would not get to run
        # until it finished.
        ticks = 0
        for _ in range(10):
            await asyncio.sleep(0.01)
            ticks += 1

        await poller.stop()
        return ticks

    assert asyncio.run(scenario()) == 10


@pytest.mark.parametrize("interval", [0.01, 0.05])
def test_interval_is_configurable(interval):
    poller = SnapshotPoller(FakeService(), interval_seconds=interval)

    assert poller._interval_seconds == interval
