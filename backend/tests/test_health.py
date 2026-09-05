from fastapi.testclient import TestClient

from app.main import create_app
from app.version import VERSION

app = create_app()
client = TestClient(app, base_url="http://testserver/api")


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": VERSION}
