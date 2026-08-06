from typing import Optional

import httpx
from .errors import AgentConnectionError, AgentResponseError


class AgentClient:
    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_snapshot(self) -> httpx.Response:
        url = f"{self.base_url}/snapshot"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url)
                return response
        except httpx.RequestError as exc:
            raise AgentConnectionError(str(exc)) from exc

    def get_snapshot_optional(self) -> Optional[httpx.Response]:
        response = self.get_snapshot()
        if response.status_code == 204:
            return None
        if response.status_code != 200:
            raise AgentResponseError(
                f"Unexpected status code {response.status_code}: {response.text}"
            )
        return response
