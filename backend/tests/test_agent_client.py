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


def test_get_snapshot_connection_error():
    client = AgentClient(BASE_URL)

    with pytest.raises(AgentConnectionError):
        client.get_snapshot()
