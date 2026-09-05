import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.client.errors import AgentConnectionError
from app.services.snapshot_poller import FAILURES_WORTH_REPEATING, SnapshotPoller


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
        asyncio.run(SnapshotPoller(service, agent_url="http://127.0.0.1:8080").poll_once())

    assert "Snapshot poll from http://127.0.0.1:8080 failed (1 in a row)" in caplog.text
    assert "agent returned 500" in caplog.text


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


class FakeStore:
    """Records prune cutoffs, so tests can assert on the retention window."""

    def __init__(self, error=None, removed=0):
        self.cutoffs = []
        self.error = error
        self.removed = removed

    def prune(self, older_than):
        self.cutoffs.append(older_than)
        if self.error is not None:
            raise self.error
        return self.removed


def poller_with(store, **kwargs):
    kwargs.setdefault("retention_days", 30)
    kwargs.setdefault("prune_interval_seconds", 3600)
    return SnapshotPoller(FakeService(), interval_seconds=0.01, store=store, **kwargs)


def test_prune_runs_on_the_first_pass():
    store = FakeStore()

    assert asyncio.run(poller_with(store).prune_if_due())
    assert len(store.cutoffs) == 1


def test_prune_cutoff_matches_the_retention_window():
    store = FakeStore()

    asyncio.run(poller_with(store, retention_days=7).prune_if_due())

    age = datetime.now(timezone.utc) - store.cutoffs[0]
    assert timedelta(days=7) - timedelta(minutes=1) < age < timedelta(days=7, minutes=1)


def test_prune_does_not_run_again_before_its_interval():
    async def scenario():
        store = FakeStore()
        poller = poller_with(store, prune_interval_seconds=3600)

        first = await poller.prune_if_due()
        second = await poller.prune_if_due()
        return first, second, len(store.cutoffs)

    first, second, calls = asyncio.run(scenario())

    # Pruning every tick would mean a DELETE every few seconds to remove nothing.
    assert first is True
    assert second is False
    assert calls == 1


def test_prune_runs_again_once_its_interval_has_passed():
    async def scenario():
        store = FakeStore()
        poller = poller_with(store, prune_interval_seconds=0.01)

        await poller.prune_if_due()
        await asyncio.sleep(0.05)
        await poller.prune_if_due()
        return len(store.cutoffs)

    assert asyncio.run(scenario()) == 2


def test_retention_of_zero_days_keeps_everything():
    store = FakeStore()

    assert asyncio.run(poller_with(store, retention_days=0).prune_if_due()) is False
    assert store.cutoffs == []


def test_prune_is_skipped_without_a_store():
    poller = SnapshotPoller(FakeService(), retention_days=30)

    assert asyncio.run(poller.prune_if_due()) is False


def test_prune_failure_does_not_raise(caplog):
    store = FakeStore(error=RuntimeError("database is locked"))

    with caplog.at_level("WARNING"):
        asyncio.run(poller_with(store).prune_if_due())

    assert "Snapshot pruning failed" in caplog.text


def test_prune_failure_does_not_stop_the_loop():
    async def scenario():
        store = FakeStore(error=RuntimeError("database is locked"))
        poller = poller_with(store, prune_interval_seconds=0.01)
        poller.start()

        kept_polling = await wait_for(lambda: poller._service.calls >= 3)
        await poller.stop()
        return kept_polling

    assert asyncio.run(scenario())


def test_removal_count_is_logged(caplog):
    store = FakeStore(removed=12)

    with caplog.at_level("INFO"):
        asyncio.run(poller_with(store).prune_if_due())

    assert "Pruned 12 snapshots" in caplog.text


class FakeEngine:
    """Records the snapshots handed to it, raising on demand."""

    def __init__(self, error=None):
        self.seen = []
        self.error = error

    def evaluate(self, snapshot):
        self.seen.append(snapshot)
        if self.error is not None:
            raise self.error


def test_alerts_are_evaluated_after_a_successful_poll():
    engine = FakeEngine()

    asyncio.run(SnapshotPoller(FakeService(), engine=engine).poll_once())

    assert engine.seen == ["snapshot"]


def test_alerts_are_not_evaluated_when_the_agent_is_unreachable():
    engine = FakeEngine()
    service = FakeService(errors=[AgentConnectionError("down")])

    asyncio.run(SnapshotPoller(service, engine=engine).poll_once())

    # Infrastructure failure must not raise a storm of false alerts.
    assert engine.seen == []


def test_alerts_are_not_evaluated_when_the_agent_has_no_snapshot_yet():
    engine = FakeEngine()
    service = FakeService(errors=[LookupError("nothing yet")])

    asyncio.run(SnapshotPoller(service, engine=engine).poll_once())

    assert engine.seen == []


def test_alert_evaluation_failure_is_logged_and_swallowed(caplog):
    engine = FakeEngine(error=RuntimeError("bad rule"))

    with caplog.at_level("WARNING"):
        asyncio.run(SnapshotPoller(FakeService(), engine=engine).poll_once())

    assert "Alert evaluation failed" in caplog.text


def test_alert_evaluation_failure_does_not_stop_the_loop():
    async def scenario():
        engine = FakeEngine(error=RuntimeError("bad rule"))
        poller = SnapshotPoller(FakeService(), interval_seconds=0.01, engine=engine)
        poller.start()

        kept_going = await wait_for(lambda: len(engine.seen) >= 3)
        await poller.stop()
        return kept_going

    assert asyncio.run(scenario())


def test_poller_without_an_engine_still_polls():
    service = FakeService()

    asyncio.run(SnapshotPoller(service).poll_once())

    assert service.calls == 1


# --- an outage should not bury the log ---------------------------------------


def poll_failing(poller, times):
    async def scenario():
        for _ in range(times):
            await poller.poll_once()

    asyncio.run(scenario())


def always_failing(**kwargs):
    class AlwaysDown:
        def get_snapshot(self):
            raise AgentConnectionError("connection refused")

    return SnapshotPoller(AlwaysDown(), agent_url="http://127.0.0.1:8080", **kwargs)


def failure_lines(caplog):
    return [r for r in caplog.records if "failed (" in r.getMessage()]


def test_a_long_outage_is_reported_a_handful_of_times(caplog):
    poller = always_failing()

    with caplog.at_level("WARNING"):
        poll_failing(poller, 600)

    # 600 ticks is under two hours at the default interval. One line each would
    # bury everything else the log had to say.
    assert len(failure_lines(caplog)) == len(FAILURES_WORTH_REPEATING)


def test_only_the_first_failure_carries_a_traceback(caplog):
    poller = always_failing()

    with caplog.at_level("WARNING"):
        poll_failing(poller, 10)

    lines = failure_lines(caplog)
    # After the first, the traceback is identical and the count is the news.
    # `not` rather than `is None`: logging stores exc_info=False verbatim.
    assert lines[0].exc_info
    assert all(not line.exc_info for line in lines[1:])


def test_the_message_says_how_long_it_has_been_going_on(caplog):
    poller = always_failing()

    with caplog.at_level("WARNING"):
        poll_failing(poller, 10)

    assert "failed (10 in a row)" in failure_lines(caplog)[-1].getMessage()


def test_the_message_names_the_agent(caplog):
    poller = always_failing()

    with caplog.at_level("WARNING"):
        poll_failing(poller, 1)

    # Two backends polling two agents have to be distinguishable in a log that
    # has been copied somewhere else.
    assert "http://127.0.0.1:8080" in caplog.text


def test_recovery_is_reported(caplog):
    service = FakeService(errors=[AgentConnectionError("down")] * 3)
    poller = SnapshotPoller(service, agent_url="http://127.0.0.1:8080")

    async def scenario():
        for _ in range(4):
            await poller.poll_once()

    with caplog.at_level("INFO"):
        asyncio.run(scenario())

    # Without this the log shows an agent going down and never says it came
    # back, which reads like an outage that is still running.
    assert "succeeded again after 3 failed attempts" in caplog.text


def test_an_agent_with_nothing_yet_counts_as_recovery(caplog):
    service = FakeService(errors=[AgentConnectionError("down"), LookupError("nothing yet")])
    poller = SnapshotPoller(service, agent_url="http://127.0.0.1:8080")

    async def scenario():
        await poller.poll_once()
        await poller.poll_once()

    with caplog.at_level("INFO"):
        asyncio.run(scenario())

    # It answered, so whatever was wrong is over — even though no snapshot came.
    assert "succeeded again after 1 failed attempts" in caplog.text


def test_the_count_restarts_after_a_recovery(caplog):
    service = FakeService(errors=[AgentConnectionError("down"), None, AgentConnectionError("down")])
    poller = SnapshotPoller(service, agent_url="http://127.0.0.1:8080")

    async def scenario():
        for _ in range(3):
            await poller.poll_once()

    with caplog.at_level("WARNING"):
        asyncio.run(scenario())

    counts = [line.getMessage() for line in failure_lines(caplog)]
    assert counts == [
        "Snapshot poll from http://127.0.0.1:8080 failed (1 in a row): down",
        "Snapshot poll from http://127.0.0.1:8080 failed (1 in a row): down",
    ]
