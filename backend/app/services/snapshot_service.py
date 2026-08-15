import logging
from typing import Optional

from app.client import AgentClient
from app.models.snapshot import Snapshot
from app.repositories import SnapshotStore
from config import settings

logger = logging.getLogger(__name__)


class SnapshotService:
    def __init__(self, client: Optional[AgentClient] = None, store: Optional[SnapshotStore] = None):
        self.client = client or AgentClient(settings.agent_base_url)
        self.store = store

    def get_snapshot(self) -> Snapshot:
        response = self.client.get_snapshot()
        snapshot = self._parse_response(response)
        self._persist(snapshot)
        return snapshot

    def _parse_response(self, response) -> Snapshot:
        if response.status_code == 204:
            raise LookupError("No snapshot available yet")

        if response.status_code != 200:
            raise RuntimeError(f"Agent returned status {response.status_code}")

        payload = response.json()
        return Snapshot.from_payload(payload)

    def _persist(self, snapshot):
        """Store the snapshot, but never fail the request because of it.

        Reading the agent is the caller's actual request; persistence is a side
        effect. A broken or missing database must not turn a working /snapshot
        into a 503, so failures are logged and swallowed.
        """
        if self.store is None:
            return

        try:
            self.store.save(snapshot)
        except Exception:
            logger.warning("Could not persist snapshot", exc_info=True)
