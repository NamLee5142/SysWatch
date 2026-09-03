"""A small fixed-window limiter for the login endpoint.

Deliberately in-process and deliberately small. It holds counters in a dict, so
it resets when the process restarts and each uvicorn worker keeps its own —
neither is a problem for a single-worker localhost deployment, and both are the
reason this is not sold as a general rate limiter. A deployment that fronts
several workers, or that needs limits to survive a restart, wants a shared store
and belongs in a later sprint.

Only failed attempts are counted. Someone logging in ten times legitimately is
not the thing being defended against, and locking them out would be a denial of
service delivered by the security feature.
"""
import threading
import time

# Ten wrong passwords in five minutes is far past a typo and far short of a
# useful guessing rate.
DEFAULT_LIMIT = 10
DEFAULT_WINDOW_SECONDS = 300

# Above this many tracked keys, expired entries are swept. Without a bound, an
# attacker rotating source addresses would grow the dict until the process died
# — the limiter becoming the outage it exists to prevent.
MAX_TRACKED_KEYS = 10_000


class LoginRateLimiter:
    def __init__(self, limit=DEFAULT_LIMIT, window_seconds=DEFAULT_WINDOW_SECONDS):
        self._limit = limit
        self._window = window_seconds
        # key -> (window start, failures in this window)
        self._failures = {}
        # Sync routes run in a threadpool, so two logins really can land here at
        # once.
        self._lock = threading.Lock()

    def retry_after(self, key):
        """Seconds the caller must wait, or None if the attempt is allowed.

        Read-only: an attempt is not charged until it actually fails.
        """
        with self._lock:
            started, failures = self._failures.get(key, (None, 0))

            if started is None or self._elapsed(started) >= self._window:
                return None

            if failures < self._limit:
                return None

            return max(1, int(self._window - self._elapsed(started)) + 1)

    def record_failure(self, key):
        """Charge one failed attempt against the key."""
        with self._lock:
            self._sweep_if_crowded()

            started, failures = self._failures.get(key, (None, 0))
            if started is None or self._elapsed(started) >= self._window:
                started, failures = time.monotonic(), 0

            self._failures[key] = (started, failures + 1)

    def reset(self, key):
        """Forget a key's failures. Called when it finally logs in."""
        with self._lock:
            self._failures.pop(key, None)

    def clear(self):
        """Drop every counter. For tests and for a deliberate operator reset."""
        with self._lock:
            self._failures.clear()

    def _elapsed(self, started):
        # monotonic, so a clock change cannot hand an attacker a fresh window.
        return time.monotonic() - started

    def _sweep_if_crowded(self):
        if len(self._failures) <= MAX_TRACKED_KEYS:
            return

        self._failures = {
            key: entry
            for key, entry in self._failures.items()
            if self._elapsed(entry[0]) < self._window
        }
