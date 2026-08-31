import asyncio
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 10.0
DEFAULT_PRUNE_INTERVAL_SECONDS = 3600.0


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
    ):
        self._service = service
        self._interval_seconds = interval_seconds
        self._store = store
        self._retention_days = retention_days
        self._prune_interval_seconds = prune_interval_seconds
        self._task = None
        self._last_prune = None
        # What the last tick did. Nothing else records it: poll_once() swallows
        # every failure by design, so without this the API has no way to tell
        # a healthy agent from one that has been unreachable for an hour.
        self._last_polled_at = None
        self._last_success_at = None
        self._last_error = None

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
            await asyncio.to_thread(self._service.get_snapshot)
        except LookupError:
            # The agent answered, it just has nothing collected yet. That is a
            # reachable agent, so it clears the error without counting as a
            # successful collection.
            logger.debug("Agent has no snapshot to collect yet")
            self._record(error=None)
        except Exception as exc:
            logger.warning("Snapshot poll failed", exc_info=True)
            self._record(error=f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__)
        else:
            self._record(error=None, collected=True)

    def _record(self, error, collected=False):
        now = datetime.now(timezone.utc)
        self._last_polled_at = now
        self._last_error = error
        if collected:
            self._last_success_at = now

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
