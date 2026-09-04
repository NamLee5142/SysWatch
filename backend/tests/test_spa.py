import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.security import API_CONTENT_SECURITY_POLICY
from app.version import VERSION

INDEX_HTML = "<!doctype html><title>SysWatch</title><div id=root></div>"
ASSET_JS = "console.log('bundle')"


@pytest.fixture
def dashboard(tmp_path, monkeypatch):
    """A directory shaped like `npm run build` output."""
    (tmp_path / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text(ASSET_JS, encoding="utf-8")

    monkeypatch.setenv("SYSWATCH_DASHBOARD_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def client(database, dashboard):
    return TestClient(create_app())


# --- serving the app --------------------------------------------------------


def test_the_root_serves_the_dashboard(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.text == INDEX_HTML


def test_assets_are_served_as_themselves(client):
    response = client.get("/assets/app.js")

    assert response.status_code == 200
    assert response.text == ASSET_JS


@pytest.mark.parametrize("path", ["/alerts", "/cpu", "/system", "/history", "/login"])
def test_a_dashboard_route_falls_back_to_the_app(client, path):
    response = client.get(path)

    # These are not files. Without the fallback a refresh or a shared link
    # lands on nothing; the router in the browser is what knows these paths.
    assert response.status_code == 200
    assert response.text == INDEX_HTML


def test_a_nested_dashboard_route_falls_back_too(client):
    assert client.get("/alerts/some/deep/path").status_code == 200


# --- what must not fall back ------------------------------------------------


def test_an_unmatched_api_path_stays_a_json_404(client):
    response = client.get("/api/no-such-endpoint")

    # Answering this with index.html would give every client bug the same
    # symptom — HTML where JSON was expected — and hide which request was wrong.
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_a_real_api_route_is_unaffected(client):
    assert client.get("/api/health").json() == {"status": "ok", "version": VERSION}


def test_a_protected_api_route_still_answers_401_not_html(client):
    response = client.get("/api/alerts")

    assert response.status_code in (200, 401)
    assert "text/html" not in response.headers["content-type"]


def test_a_missing_asset_is_a_404_not_the_app(client):
    response = client.get("/assets/does-not-exist.js")

    # Returning HTML here surfaces in the browser as a syntax error inside a
    # module, which is a much longer way round to "that file is missing".
    assert response.status_code == 404


# --- the headers still apply ------------------------------------------------


def test_the_dashboard_carries_the_security_headers(client):
    response = client.get("/alerts")

    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_the_dashboard_gets_a_policy_that_lets_it_load(client):
    policy = client.get("/alerts").headers["Content-Security-Policy"]

    # The API's default-src 'none' forbids the page loading its own bundle:
    # it renders blank with a console full of CSP violations.
    assert "script-src 'self'" in policy
    assert "default-src 'none'" not in policy


def test_the_api_keeps_the_strict_policy(client):
    policy = client.get("/api/health").headers["Content-Security-Policy"]

    # Same process, opposite needs. JSON can load nothing at all.
    assert policy == API_CONTENT_SECURITY_POLICY


def test_an_asset_is_not_treated_as_a_page(client):
    policy = client.get("/assets/app.js").headers["Content-Security-Policy"]

    assert policy == API_CONTENT_SECURITY_POLICY


# --- not configured ---------------------------------------------------------


def test_nothing_is_mounted_when_the_setting_is_empty(database, monkeypatch):
    monkeypatch.delenv("SYSWATCH_DASHBOARD_DIR", raising=False)
    client = TestClient(create_app())

    # Exactly the behaviour before this existed: the API works, and no path
    # outside it does.
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 404
    assert client.get("/alerts").status_code == 404


def test_a_directory_without_an_index_is_refused_loudly(database, tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("SYSWATCH_DASHBOARD_DIR", str(tmp_path))

    with caplog.at_level("WARNING"):
        client = TestClient(create_app())

    # A typo here is otherwise silent: the API keeps working and the dashboard
    # is simply absent, with nothing saying why.
    assert "npm run build" in caplog.text
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 404


def test_a_missing_directory_does_not_stop_the_backend(database, tmp_path, monkeypatch):
    monkeypatch.setenv("SYSWATCH_DASHBOARD_DIR", str(tmp_path / "nope"))

    client = TestClient(create_app())

    assert client.get("/api/health").status_code == 200
