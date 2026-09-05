import httpx
import pytest
import respx

from app.client import AgentClient
from app.client.errors import AgentConnectionError


BASE_URL = "http://127.0.0.1:8080"


def test_get_snapshot_success():
    client = AgentClient(BASE_URL)

    with respx.mock as mock:
        mock.get(f"{BASE_URL}/snapshot").respond(200, json={"status": "ok"})
        response = client.get_snapshot()

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_snapshot_204():
    client = AgentClient(BASE_URL)

    with respx.mock as mock:
        mock.get(f"{BASE_URL}/snapshot").respond(204)
        response = client.get_snapshot()

    assert response.status_code == 204


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("All connection attempts failed"),
        httpx.ConnectTimeout("timed out"),
        httpx.ReadTimeout("timed out"),
        httpx.RemoteProtocolError("server disconnected"),
    ],
    ids=["refused", "connect timeout", "read timeout", "disconnected"],
)
def test_a_transport_failure_becomes_an_agent_connection_error(failure):
    """Every way httpx can fail to complete a request, not just a refusal.

    This used to make a real request to 127.0.0.1:8080 and rely on nothing
    listening there, so it failed on any machine actually running an agent —
    including the one most likely to be running the suite. The subject is the
    translation, so the failure is injected rather than arranged.
    """
    client = AgentClient(BASE_URL)

    with respx.mock as mock:
        mock.get(f"{BASE_URL}/snapshot").mock(side_effect=failure)

        with pytest.raises(AgentConnectionError) as raised:
            client.get_snapshot()

    # The detail travels with it: the poller logs this string, and "connection
    # error" on its own would not say which of these happened.
    assert str(failure) in str(raised.value)
