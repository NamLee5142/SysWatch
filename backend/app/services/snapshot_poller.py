import asyncio
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 10.0
DEFAULT_PRUNE_INTERVAL_SECONDS = 3600.0

# Which consecutive failure gets a log line. An agent that is down stays down,
# and at one line per tick a weekend outage writes tens of thousands of
# identical tracebacks — which buries every other thing the log had to say.
# The first is worth a traceback; after that the count is the news.
FAILURES_WORTH_REPEATING = (1, 2, 5, 10, 50, 100, 500)
FAILURE_REPORT_INTERVAL = 1000


class SnapshotPoller:
    """Pulls a snapshot from the agent on a fixed interval and stores it.

    Without this, snapshots are only persisted when someone calls /snapshot, so
    the history has gaps wherever nobody was looking.
    """

    def __init__(
        self,
        service,
        interval_seconds=DEFAULT_INTERVAL_SECONDS,
        store=None,
        retention_days=0,
        prune_interval_seconds=DEFAULT_PRUNE_INTERVAL_SECONDS,
        engine=None,
        agent_url=None,
    ):
        self._service = service
        self._interval_seconds = interval_seconds
        self._store = store
        self._retention_days = retention_days
        self._prune_interval_seconds = prune_interval_seconds
        # Optional: None when SYSWATCH_ALERTS_ENABLED is false.
        self._engine = engine
        # Only ever used in log messages, so that two backends polling two
        # agents are distinguishable in a log that has been copied somewhere.
        self._agent_url = agent_url or "the agent"
        self._task = None
        self._last_prune = None
        # What the last tick did. Nothing else records it: poll_once() swallows
        # every failure by design, so without this the API has no way to tell
        # a healthy agent from one that has been unreachable for an hour.
        self._last_polled_at = None
        self._last_success_at = None
        self._last_error = None
        self._consecutive_failures = 0

    @property
    def running(self):
        return self._task is not None and not self._task.done()

    @property
    def last_polled_at(self):
        """When the loop last completed a tick, successful or not."""
        return self._last_polled_at

    @property
    def last_success_at(self):
        """When a snapshot last actually arrived from the agent."""
        return self._last_success_at

    @property
    def last_error(self):
        """Why the last tick failed, or None if it reached the agent."""
        return self._last_error

    def start(self):
        """Begin polling in the background. Repeat calls are ignored."""
        if self.running:
            return

        self._task = asyncio.create_task(self._run(), name="snapshot-poller")
        logger.info("Snapshot poller started, interval %ss", self._interval_seconds)

    async def stop(self):
        """Cancel the loop and wait for it to finish."""
        if self._task is None:
            return

        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

        logger.info("Snapshot poller stopped")

    async def poll_once(self):
        """Fetch and store one snapshot, absorbing any failure.

        The agent being down, restarting, or not having collected yet are all
        normal conditions. None of them may kill the loop, or a single blip
        would stop collection until the process is restarted.
        """
        try:
            # get_snapshot() blocks on a socket, so it cannot run on the event
            # loop without stalling every request served by this process.
            snapshot = await asyncio.to_thread(self._service.get_snapshot)
        except LookupError:
            # The agent answered, it just has nothing collected yet. That is a
            # reachable agent, so it clears the error without counting as a
            # successful collection.
            logger.debug("Agent has no snapshot to collect yet")
            # It answered, so whatever was wrong is over.
            self._note_reachable()
            self._record(error=None)
        except Exception as exc:
            self._note_failure(exc)
            self._record(error=f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__)
        else:
            self._note_reachable()
            self._record(error=None, collected=True)
            # Only here — never after a failed or empty poll — so an unreachable
            # agent cannot raise a storm of false alerts. Agent-down is /status's
            # job, not the alert engine's.
            await self._evaluate_alerts(snapshot)

    def _note_failure(self, exc):
        """Report a failed poll, without reporting every one of them.

        The first failure carries a traceback because it says what broke.
        After that the traceback is identical and the only new information is
        how long it has been going on, so the line thins out as the outage
        lengthens.
        """
        self._consecutive_failures += 1
        count = self._consecutive_failures

        if count in FAILURES_WORTH_REPEATING or count % FAILURE_REPORT_INTERVAL == 0:
            logger.warning(
                "Snapshot poll from %s failed (%d in a row): %s",
                self._agent_url,
                count,
                exc,
                exc_info=count == 1,
            )

    def _note_reachable(self):
        """Say so when an outage ends, and forget the count."""
        if self._consecutive_failures:
            # Without this the log shows an agent going down and never says it
            # came back, which reads like an outage that is still running.
            logger.info(
                "Snapshot poll from %s succeeded again after %d failed attempts",
                self._agent_url,
                self._consecutive_failures,
            )
            self._consecutive_failures = 0

    def _record(self, error, collected=False):
        now = datetime.now(timezone.utc)
        self._last_polled_at = now
        self._last_error = error
        if collected:
            self._last_success_at = now

    async def _evaluate_alerts(self, snapshot):
        """Run the alert engine over a freshly collected snapshot.

        Failures are logged and swallowed, the same rule prune_if_due follows:
        alerting is a side effect of collection and must never be the reason it
        stops. The engine touches the database, so it runs off the event loop.
        """
        if self._engine is None:
            return

        try:
            await asyncio.to_thread(self._engine.evaluate, snapshot)
        except Exception:
            logger.warning("Alert evaluation failed", exc_info=True)

    async def prune_if_due(self):
        """Drop snapshots past the retention window, at most hourly.

        Pruning runs on the poll loop for simplicity, but on its own slower
        clock: deleting on every tick would mean a DELETE every few seconds to
        remove nothing.
        """
        if self._store is None or self._retention_days <= 0:
            return False

        now = asyncio.get_running_loop().time()
        if self._last_prune is not None and now - self._last_prune < self._prune_interval_seconds:
            return False

        self._last_prune = now
        await asyncio.to_thread(self._prune)
        return True

    def _prune(self):
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        try:
            removed = self._store.prune(cutoff)
        except Exception:
            # Same rule as a failed poll: retention is housekeeping and must not
            # take the loop down with it.
            logger.warning("Snapshot pruning failed", exc_info=True)
            return

        if removed:
            logger.info("Pruned %s snapshots older than %s days", removed, self._retention_days)

    async def _run(self):
        # Poll first, then wait, so startup does not begin with a dead interval.
        while True:
            await self.poll_once()
            await self.prune_if_due()
            await asyncio.sleep(self._interval_seconds)
