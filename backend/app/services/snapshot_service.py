from typing import Optional

from app.client import AgentClient
from app.models.snapshot import Snapshot
from config import settings


class SnapshotService:
    def __init__(self, client: Optional[AgentClient] = None):
        self.client = client or AgentClient(settings.agent_base_url)

    def get_snapshot(self) -> Snapshot:
        response = self.client.get_snapshot()
        return self._parse_response(response)

    def _parse_response(self, response) -> Snapshot:
        if response.status_code == 204:
            raise LookupError("No snapshot available yet")

        if response.status_code != 200:
            raise RuntimeError(f"Agent returned status {response.status_code}")

        payload = response.json()
        return Snapshot.from_payload(payload)
