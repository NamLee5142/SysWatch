import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from config import Settings

DASHBOARD_ORIGIN = "http://localhost:5173"


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv("SYSWATCH_CORS_ORIGINS", raising=False)
    return monkeypatch


@pytest.fixture
def client(clean_env):
    # Built per test rather than at import: create_app() reads the origins once,
    # so an app made before monkeypatch would carry the wrong ones.
    return TestClient(create_app())


def preflight(client, origin, method="GET"):
    return client.options(
        "/health",
        headers={"Origin": origin, "Access-Control-Request-Method": method},
    )


def test_dashboard_origin_is_allowed_by_default(client):
    response = client.get("/health", headers={"Origin": DASHBOARD_ORIGIN})

    assert response.headers["access-control-allow-origin"] == DASHBOARD_ORIGIN


def test_loopback_spelling_of_the_dev_server_is_also_allowed(client):
    origin = "http://127.0.0.1:5173"

    response = client.get("/health", headers={"Origin": origin})

    # A browser treats this as a different origin from localhost, and developers
    # reach for either.
    assert response.headers["access-control-allow-origin"] == origin


def test_unknown_origin_gets_no_allow_header(client):
    response = client.get("/health", headers={"Origin": "http://evil.example"})

    # The request still succeeds server-side; the browser is what blocks it,
    # and it blocks on this header being absent.
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_preflight_succeeds_for_an_allowed_origin(client):
    response = preflight(client, DASHBOARD_ORIGIN)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == DASHBOARD_ORIGIN


def test_preflight_advertises_the_write_methods(client):
    response = preflight(client, DASHBOARD_ORIGIN)

    # GET for the reads, plus POST/PUT/DELETE for alert-rule management.
    methods = {m.strip() for m in response.headers["access-control-allow-methods"].split(",")}
    assert methods == {"GET", "POST", "PUT", "DELETE"}


def test_preflight_allows_a_write_method_from_an_allowed_origin(client):
    response = preflight(client, DASHBOARD_ORIGIN, method="POST")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == DASHBOARD_ORIGIN


def test_preflight_still_rejects_a_write_method_from_an_unknown_origin(client):
    response = preflight(client, "http://evil.example", method="POST")

    assert "access-control-allow-origin" not in response.headers


def test_credentials_are_not_allowed(client):
    response = client.get("/health", headers={"Origin": DASHBOARD_ORIGIN})

    # The API is unauthenticated. Allowing credentials would let a browser
    # attach cookies to these requests before Phase 4 adds any auth to check.
    assert "access-control-allow-credentials" not in response.headers


def test_origins_can_be_replaced_by_env(clean_env):
    clean_env.setenv("SYSWATCH_CORS_ORIGINS", "http://dash.internal")
    client = TestClient(create_app())

    allowed = client.get("/health", headers={"Origin": "http://dash.internal"})
    default = client.get("/health", headers={"Origin": DASHBOARD_ORIGIN})

    assert allowed.headers["access-control-allow-origin"] == "http://dash.internal"
    assert "access-control-allow-origin" not in default.headers


def test_comma_separated_origins_are_parsed(clean_env):
    clean_env.setenv("SYSWATCH_CORS_ORIGINS", "http://one.example, http://two.example")

    # pydantic-settings would otherwise JSON-decode a list field and reject
    # this, which is the spelling anyone would reach for in a shell.
    assert Settings().cors_origins == ["http://one.example", "http://two.example"]


def test_blank_entries_are_dropped(clean_env):
    clean_env.setenv("SYSWATCH_CORS_ORIGINS", "http://one.example,,  ,http://two.example")

    assert Settings().cors_origins == ["http://one.example", "http://two.example"]
