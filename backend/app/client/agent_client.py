import httpx

from .errors import AgentConnectionError


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
